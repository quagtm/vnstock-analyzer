"""Build frontend/public/ssi_sectors.json from raw SSI MCP responses.

The raw files in ./raw/ are written by a Claude session that calls the SSI MCP
connector (GitHub Actions cannot call MCP). This script only reshapes them, so
it runs anywhere with plain Python and no network.

    python data_pipeline/ssi_mcp/build_ssi_sectors.py

See README.md in this folder for the refresh procedure.
"""
import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
OUT = os.path.join(HERE, "..", "..", "frontend", "public", "ssi_sectors.json")

# Tên ngành ICB cấp 2 (tiếng Việt). SSI Research dùng tên hẹp hơn cho vài
# ngành (VD 1700 "Kim loại"), tên đó được giữ ở assessment.title.
ICB2_NAMES = {
    "0500": "Dầu khí",
    "1300": "Hóa chất",
    "1700": "Tài nguyên cơ bản",
    "2300": "Xây dựng và Vật liệu",
    "2700": "Hàng & Dịch vụ Công nghiệp",
    "3300": "Ô tô và phụ tùng",
    "3500": "Thực phẩm và đồ uống",
    "3700": "Hàng cá nhân & Gia dụng",
    "4500": "Y tế",
    "5300": "Bán lẻ",
    "5500": "Truyền thông",
    "5700": "Du lịch và Giải trí",
    "6500": "Viễn thông",
    "7500": "Điện, nước & xăng dầu khí đốt",
    "8300": "Ngân hàng",
    "8500": "Bảo hiểm",
    "8600": "Bất động sản",
    "8700": "Dịch vụ tài chính",
    "9500": "Công nghệ Thông tin",
}

# Rổ dùng để tính bình quân; rổ đầu tiên có dữ liệu là rổ chính của ngành.
EXCHANGE_PRIORITY = ["VNINDEX", "HOHAUP", "HNXINDEX"]

METRICS = [
    "pe", "pb", "ps", "eps", "roe", "roa", "market_cap", "sale_growth_rate",
    "net_profit_margin", "ev_to_ebitda", "total_liabilities_to_equity",
    "close_index",
]


def norm_code(code):
    return str(code).strip().zfill(4)


def to_num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load(name):
    with open(os.path.join(RAW, name), encoding="utf-8") as f:
        return json.load(f)


def main():
    icb = load("icb_industry.json")
    assess = load("industry_assessment.json")

    by_code = {}
    for row in icb.get("industries", []):
        code = norm_code(row.get("icb_code"))
        if code not in ICB2_NAMES:
            continue
        vals = {k: to_num(row.get(k)) for k in METRICS}
        # SSI trả dòng toàn số 0 khi chưa có dữ liệu: bỏ qua.
        if not any(vals.values()):
            continue
        by_code.setdefault(code, {})[row.get("exchange")] = vals

    notes = {}
    for a in assess.get("industries", []):
        text = (a.get("assessment") or "").strip()
        if text:
            notes[norm_code(a.get("icb_code"))] = {
                "title": a.get("icb_name", ""),
                "text": text,
            }

    sectors = []
    for code, name in ICB2_NAMES.items():
        metrics = by_code.get(code, {})
        if not metrics and code not in notes:
            continue
        primary = next((e for e in EXCHANGE_PRIORITY if e in metrics), None)
        sectors.append({
            "icb_code": code,
            "name": name,
            "primary_exchange": primary,
            "metrics": metrics,
            "assessment": notes.get(code),
        })

    def cap(s):
        m = s["metrics"].get(s["primary_exchange"] or "", {})
        return m.get("market_cap") or 0

    sectors.sort(key=cap, reverse=True)

    out = {
        "source": "SSI MCP (marketdata_list_icb_industry, research_get_ssi100_industry_assessment)",
        "as_of": icb.get("asOfUtc"),
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "exchanges": [e for e in EXCHANGE_PRIORITY
                      if any(e in s["metrics"] for s in sectors)],
        "units": {
            "market_cap": "VND",
            "roe,roa,net_profit_margin,sale_growth_rate": "fraction (0.15 = 15%)",
        },
        "sectors": sectors,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"Wrote {len(sectors)} sectors -> {os.path.relpath(OUT)}")


if __name__ == "__main__":
    main()
