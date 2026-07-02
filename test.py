import pandas as pd
import numpy as np

df = pd.DataFrame({
    'close': np.random.rand(100) * 100,
    'volume': np.random.rand(100) * 1000
})

df['ma20'] = df['close'].rolling(20).mean()
row = df.iloc[-1]

def _s(k): return float(row.get(k, 0)) if pd.notna(row.get(k)) else 0.0

print(_s('ma20'))
