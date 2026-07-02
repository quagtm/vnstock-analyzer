import urllib.request, json

url = "https://quagtm.github.io/vnstock-analyzer/public/data.json"
with urllib.request.urlopen(url) as r:
    d = json.loads(r.read())

for sym in ["VNINDEX", "VN30", "VN100"]:
    if sym in d:
        txt = d[sym].get("general_markdown", "")
        is_fallback = "\u26a0" in txt or "b\u1ea3o tr\u00ec" in txt
        print(f"{sym}: date={d[sym]['date']}, is_fallback={is_fallback}")
        print(f"  First 150 chars: {txt[:150]}")
        print(f"  Last 100 chars: {txt[-100:]}")
        print()
