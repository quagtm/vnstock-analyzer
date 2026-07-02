import pandas as pd
import numpy as np

def compute_tas(close, latest, vol_diff, mas):
    def sf(key): return float(latest.get(key, 0) or 0) if pd.notna(latest.get(key, 0)) else 0.0

    ma_map = dict(mas)
    ma20  = ma_map.get('MA20',  0)
    ma50  = ma_map.get('MA50',  0)
    ma200 = ma_map.get('MA200', 0)
    cmf   = sf('cmf')
    roc10 = sf('roc10')
    roc20 = sf('roc20')
    adx   = sf('adx')
    vwap  = sf('vwap')
    kh    = sf('keltner_h')
    kl    = sf('keltner_l')

    indicators = []
    if ma20 > 0: indicators.append({'score': 1 if close > ma20 else -1})
    if ma50 > 0: indicators.append({'score': 1 if close > ma50 else -1})
    if ma200 > 0: indicators.append({'score': 1 if close > ma200 else -1})

    if roc10 > 1.5: s = 1
    elif roc10 < -1.5: s = -1
    else: s = 0
    indicators.append({'score': s})

    if roc20 > 2: s = 1
    elif roc20 < -2: s = -1
    else: s = 0
    indicators.append({'score': s})

    if kh > 0 and kl > 0:
        if close > kh: s = 1
        elif close < kl: s = -1
        else:
            mid_k = (kh + kl) / 2
            s = 1 if close > mid_k else -1
        indicators.append({'score': s})

    if cmf > 0.05: s = 1
    elif cmf < -0.05: s = -1
    else: s = 0
    indicators.append({'score': s})

    if vwap > 0: indicators.append({'score': 1 if close > vwap else -1})

    if vol_diff > 10: s = 1
    elif vol_diff < -10: s = -1
    else: s = 0
    indicators.append({'score': s})

    max_score = len(indicators)
    total     = sum(i['score'] for i in indicators)
    pct       = round(total / max(max_score, 1) * 100)
    return pct, max_score, indicators

df = pd.DataFrame({
    'close': np.random.rand(100) * 100,
    'volume': np.random.rand(100) * 1000
})
df['ma20'] = df['close'].rolling(20).mean()
df['ma50'] = df['close'].rolling(50).mean()
df['ma200'] = df['close'].rolling(200).mean()
df['roc10'] = np.random.rand(100) * 10 - 5
df['roc20'] = np.random.rand(100) * 10 - 5
df['cmf'] = np.random.rand(100) * 0.2 - 0.1
df['vwap'] = np.random.rand(100) * 100
df['keltner_h'] = df['close'] + 5
df['keltner_l'] = df['close'] - 5
df['adx'] = np.random.rand(100) * 50

vol_ma20 = df['volume'].rolling(20).mean()

for i in range(-5, 0):
    row = df.iloc[i]
    close_i = float(row.get('close', 0) or 0)
    vol_i    = float(row.get('volume', 0) or 0)
    vma_i    = float(vol_ma20.iloc[i]) if pd.notna(vol_ma20.iloc[i]) else vol_i
    vdiff_i  = ((vol_i - vma_i) / vma_i * 100) if vma_i > 0 else 0

    def _s(k): return float(row.get(k, 0)) if pd.notna(row.get(k)) else 0.0
    pseudo = {
        'cmf': _s('cmf'), 'vwap': _s('vwap'),
        'roc10': _s('roc10'), 'roc20': _s('roc20'),
        'adx': _s('adx'), 'keltner_h': _s('keltner_h'), 'keltner_l': _s('keltner_l'),
    }
    mas_i = [('MA20', _s('ma20')), ('MA50', _s('ma50')), ('MA200', _s('ma200'))]
    pct, max_score, indicators = compute_tas(close_i, pseudo, vdiff_i, mas_i)
    print(f"i={i}, max_score={max_score}, pct={pct}")

