import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
d = json.load(open('output/data.json', encoding='utf-8'))
raw_stocks = d['__global__']['raw_stocks']
print(f'raw_stocks: {len(raw_stocks)} ma')
for h in d['VNINDEX']['sector_heatmap']:
    print(f"  {h['sector']}: {h['count']} CP -> {h['tickers'][:5]}...")
