import urllib.request, json, time, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

url = f'https://quagtm.github.io/vnstock-analyzer/public/data.json?t={int(time.time())}'
req = urllib.request.Request(url, headers={'Cache-Control': 'no-cache'})
data = json.loads(urllib.request.urlopen(req).read())

# Check raw_stocks sector field
raw = data.get('__global__', {}).get('raw_stocks', {})
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
