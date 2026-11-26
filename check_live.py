import urllib.request, json, time, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

base = 'https://quagtm.github.io/vnstock-analyzer/public/'
def fetch(name):
    req = urllib.request.Request(f'{base}{name}?t={int(time.time())}', headers={'Cache-Control': 'no-cache'})
    return json.loads(urllib.request.urlopen(req).read())

data = fetch('data.json')

# raw_stocks nằm trong file riêng (định dạng cũ: nằm trong data.json)
raw = data.get('__global__', {}).get('raw_stocks') or fetch(data.get('__global__', {}).get('raw_stocks_file', 'raw_stocks.json'))
print(f"raw_stocks total: {len(raw)} ma")

# Print sector values for sample stocks
samples = ['VCB', 'HPG', 'GAS', 'FPT', 'VHM', 'SSI', 'MWG']
print("\nSector trong raw_stocks:")
for sym in samples:
    if sym in raw:
        print(f"  {sym}: sector='{raw[sym].get('sector', 'EMPTY')}'")
    else:
        print(f"  {sym}: KHONG CO TRONG RAW_STOCKS")

# Check unique sectors in raw_stocks
unique_sectors = set(v.get('sector','') for v in raw.values() if v.get('sector'))
print(f"\nCac sector trong raw_stocks ({len(unique_sectors)} sector):")
for s in sorted(unique_sectors):
    print(f"  {s}")
