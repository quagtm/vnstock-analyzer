import urllib.request, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

req = urllib.request.Request("https://quagtm.github.io/vnstock-analyzer/public/data.json")
req.add_header('User-Agent', 'Mozilla/5.0')
resp = urllib.request.urlopen(req)
data = json.loads(resp.read())
vnindex = data.get('VNINDEX', {})
heatmap = vnindex.get('sector_heatmap', [])
for h in heatmap:
    print(f"{h['sector']}: {h['count']} CP -> {h.get('tickers', [])}")

print("\n---")
raw_stocks = data.get('__global__', {}).get('raw_stocks', {})
print(f"Total raw_stocks: {len(raw_stocks)}")
print("Does raw_stocks have GAS? ", 'GAS' in raw_stocks)
print("Does raw_stocks have PVD? ", 'PVD' in raw_stocks)
print("Does raw_stocks have PVS? ", 'PVS' in raw_stocks)
print("Does raw_stocks have BSR? ", 'BSR' in raw_stocks)
