"""Build frontend/public/ssi_top_stocks.json from raw/top_stocks.json.

raw/top_stocks.json is written by a Claude session calling the SSI MCP tool
marketdata_list_top_stocks (see README.md). Plain Python, no network.

    python data_pipeline/ssi_mcp/build_ssi_top_stocks.py
"""
import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw", "top_stocks.json")
OUT = os.path.join(HERE, "..", "..", "frontend", "public", "ssi_top_stocks.json")

# criteria của SSI MCP -> khóa trong file frontend
LISTS = {
    "topIncreaseByPercent": "gainers",
    "topDecreaseByPercent": "losers",
    "topbytradingamount": "hot",
}


def clean(row):
    return {
        "symbol": row["symbol"],
        "change": float(row.get("change_by_value") or 0),
        "change_pct": float(row.get("change_by_percent") or 0),
        "avg_volume": float(row.get("avg_volume") or 0),
        "avg_value": float(row.get("avg_trading_amount") or 0),
    }


def main():
    with open(RAW, encoding="utf-8") as f:
        raw = json.load(f)

    exchanges = {}
    for ex, lists in raw.get("lists", {}).items():
        out = {}
        for crit, key in LISTS.items():
            rows = [clean(r) for r in lists.get(crit, [])]
            # Ngày chưa có phiên, SSI trả toàn 0 theo thứ tự ABC: coi như rỗng.
            if key != "hot" and not any(r["change_pct"] for r in rows):
                rows = []
            out[key] = rows
        exchanges[ex] = out

    params = raw.get("params", {})
    result = {
        "source": "SSI MCP (marketdata_list_top_stocks)",
        "as_of": raw.get("asOfUtc"),
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "range": params.get("range"),
        "to_date": params.get("toDate"),
        "note": "range=1d: SSI gộp 2 ngày dương lịch (toDate-1 và toDate)",
        "exchanges": exchanges,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(f"Wrote {sum(len(v) for e in exchanges.values() for v in e.values())} rows -> {os.path.relpath(OUT)}")


if __name__ == "__main__":
    main()
