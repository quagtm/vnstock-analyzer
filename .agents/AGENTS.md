# Project Rules — vnstock-analyzer

## Auto Deploy Schedule
- Web tự động update dữ liệu lúc **15:30 VN hàng ngày** (thứ 2 - thứ 6)
- Cron GitHub Actions: `30 8 * * 1-5` (08:30 UTC = 15:30 ICT)
- File: `.github/workflows/deploy.yml`
- Khi sửa workflow, **không thay đổi cron này** trừ khi user yêu cầu

## Data Pipeline
- Pipeline chạy từ `data_pipeline/fetch_and_analyze.py`
- `custom_sectors.json` ở root và `data_pipeline/` — cả hai phải được sync khi cập nhật
- Sector mapping hiện tại: 21 ngành theo danh sách user định nghĩa (không dùng VCI ICB API)

## Sector Mapping
- User muốn tự nhập danh sách CP theo ngành — gửi qua chat, không dùng UI tùy chỉnh trên web
- Sau khi nhận danh sách: cập nhật `custom_sectors.json` → sync sang `data_pipeline/` → commit → push

## Deployment
- GitHub Pages: repo `quagtm/vnstock-analyzer`, branch `gh-pages`
- Sau khi push `main`, GitHub Actions tự build và deploy (khoảng 2-3 phút)
- Để xem thay đổi ngay: Ctrl+Shift+R (hard reload) hoặc tab ẩn danh
