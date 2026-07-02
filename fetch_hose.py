import requests
import json
import urllib3
urllib3.disable_warnings()

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}
try:
    res = requests.get('https://fwtapi1.fpts.com.vn/api/Data/market/HOSE', headers=headers, timeout=10, verify=False)
    data = res.json()
    stocks = [s['RowKey'] for s in data if len(s['RowKey']) == 3]
    if len(stocks) > 300:
        with open('hose_stocks_fallback.json', 'w') as f:
            json.dump(stocks, f)
        print(f"FPTS Success: {len(stocks)} stocks saved.")
    else:
        print("FPTS returned too few.")
except Exception as e:
    print("FPTS failed:", e)
