import urllib.request, json, time, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
url = f'https://quagtm.github.io/vnstock-analyzer/public/data.json?t={time.time()}'
d = json.loads(urllib.request.urlopen(url).read())
print(f"raw_stocks: {len(d['__global__']['raw_stocks'])} mã")
print(f"Sectors: {len(d['VNINDEX']['sector_heatmap'])} ngành")
for h in d['VNINDEX']['sector_heatmap']:
    print(f"  {h['sector']}: {h['count']} CP")
