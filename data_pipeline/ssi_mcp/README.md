# Dữ liệu ngành từ SSI MCP

`frontend/public/ssi_sectors.json` chứa chỉ số định giá bình quân theo ngành ICB cấp 2
và nhận định ngành của SSI Research, lấy qua connector **SSI MCP**. Frontend
(`frontend/ssi_sectors.js`) đọc file này và hiển thị bảng "Định giá ngành (SSI)"
trong mục Phân tích Ngành. `frontend/public/ssi_top_stocks.json` chứa top tăng, top giảm
và top giá trị giao dịch (cổ phiếu hot) của HOSE và HNX, hiển thị ở khung "Top cổ phiếu (SSI)"
phía trên dashboard (`frontend/ssi_top_stocks.js`).

GitHub Actions không gọi được MCP, nên pipeline hằng đêm (`fetch_and_analyze.py`)
**không** đụng tới file này. File được làm mới bởi một phiên Claude có SSI MCP.

## Quy trình làm mới

1. Gọi `marketdata_list_icb_industry` với `icbLevel=2`, `pageSize=100`.
   Ghi `data.industries` (giữ các dòng `VNINDEX`, `HNXINDEX`, và `HOHAUP` khi ngành
   không có số liệu `VNINDEX`) cùng `meta.asOfUtc` vào `raw/icb_industry.json`:
   `{"asOfUtc": "...", "industries": [ {icb_code, exchange, pe, pb, ...}, ... ]}`.
2. Gọi `research_get_ssi100_industry_assessment` cho từng mã ngành:
   500, 1300, 1700, 2300, 2700, 3300, 3500, 4500, 5300, 5500, 5700, 6500, 7500,
   8300, 8500, 8600, 8700, 9500 (gọi tối đa 2–3 mã một lúc, API giới hạn tốc độ).
   Ghi vào `raw/industry_assessment.json`:
   `{"asOfUtc": "...", "industries": [ {icb_code, icb_name, assessment}, ... ]}`.
3. Gọi `marketdata_list_top_stocks` với `range=1d`, `limit=10`, `toDate` = ngày giao dịch
   gần nhất (DD/MM/YYYY; bỏ trống trước phiên sẽ trả toàn số 0), cho `exchange` HOSE và HNX
   và `criteria` `topIncreaseByPercent`, `topDecreaseByPercent`, `topbytradingamount`.
   Ghi vào `raw/top_stocks.json`:
   `{"asOfUtc": "...", "params": {"range": "1d", "toDate": "...", "limit": 10},
     "lists": {"HOSE": {"topIncreaseByPercent": [...], ...}, "HNX": {...}}}`.
4. Chạy `python data_pipeline/ssi_mcp/build_ssi_sectors.py` và
   `python data_pipeline/ssi_mcp/build_ssi_top_stocks.py`.
5. Commit `raw/*.json`, `frontend/public/ssi_sectors.json` và
   `frontend/public/ssi_top_stocks.json`, push lên `main`
   (push sẽ kích hoạt workflow deploy GitHub Pages).

Các dòng SSI trả toàn số 0 (chưa có dữ liệu) bị bỏ qua. ROE, ROA, biên lợi nhuận,
tăng trưởng doanh thu là phân số (0,15 = 15%); vốn hóa tính bằng VND.
