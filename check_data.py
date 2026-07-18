import warnings, logging, sys, io
warnings.filterwarnings('ignore')
logging.disable(logging.CRITICAL)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import pandas as pd
from vnstock.explorer.vci import Trading

def _normalize_board(raw):
    raw.columns = [str(c).strip() for c in raw.columns]
    
    cp = 'match_match_price' if 'match_match_price' in raw.columns else next((c for c in raw.columns if c in ('close', 'price') or ('match_price' in c and 'ato' not in c and 'atc' not in c)), None)
    rp = 'listing_ref_price' if 'listing_ref_price' in raw.columns else next((c for c in raw.columns if c in ('ref', 'ref_price') or 'ref_price' in c), None)
    
    if cp and rp:
        raw[cp] = raw.apply(lambda row: row[rp] if pd.isna(row[cp]) or row[cp] == 0 else row[cp], axis=1)
        raw['change_pc'] = (raw[cp] - raw[rp]) / raw[rp].replace(0, float('nan')) * 100
        if 'match_match_price' not in raw.columns:
            raw['match_match_price'] = raw[cp]
        if 'listing_ref_price' not in raw.columns:
            raw['listing_ref_price'] = raw[rp]
    else:
        raw['change_pc'] = 0.0
    return raw

def test_heatmap():
    t = Trading()
    syms = ['PLX', 'PVD', 'GAS', 'BSR', 'PVS', 'FPT', 'HPG', 'SSI']
    raw = t.price_board(symbols_list=syms)
    board = _normalize_board(raw)
    
    ticker_col = next((c for c in board.columns
                       if 'code' in c.lower() or 'ticker' in c.lower() or 'symbol' in c.lower()), None)
    
    raw_stocks = {}
    import math
    for _, row in board.iterrows():
        sym = str(row[ticker_col])
        raw_stocks[sym] = row.to_dict()
    
    print(f"raw_stocks size: {len(raw_stocks)}")
    print(f"raw_stocks keys: {list(raw_stocks.keys())}")

test_heatmap()
