import warnings, logging, sys, io
warnings.filterwarnings('ignore')
logging.disable(logging.CRITICAL)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import pandas as pd
from vnstock.explorer.vci import Trading

def _normalize_board(raw):
    if hasattr(raw.columns, 'levels'):
        raw.columns = ['_'.join(str(x) for x in col if str(x))
                       for col in raw.columns.values]
    raw.columns = [str(c).strip() for c in raw.columns]
    
    cp = 'match_match_price' if 'match_match_price' in raw.columns else next((c for c in raw.columns if c in ('close', 'price') or ('match_price' in c and 'ato' not in c and 'atc' not in c)), None)
    rp = 'listing_ref_price' if 'listing_ref_price' in raw.columns else next((c for c in raw.columns if c in ('ref', 'ref_price') or 'ref_price' in c), None)
    
    print(f"cp selected: {cp}")
    print(f"rp selected: {rp}")
    
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

t = Trading()
board = t.price_board(symbols_list=['PLX'])
norm = _normalize_board(board)

print("\nResult:")
for col in ['listing_symbol', cp, rp, 'change_pc']:
    try:
        print(f"  {col}: {norm.iloc[0][col]}")
    except:
        pass
