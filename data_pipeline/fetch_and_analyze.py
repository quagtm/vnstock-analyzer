import os
import sys
import io
import json
import math
import traceback
import time
import warnings
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import ta
import requests
# vnstock v4 - thử import, nếu không có thì dùng direct API
import logging
import urllib.request
import concurrent.futures
warnings.filterwarnings('ignore')
logging.disable(logging.CRITICAL)

_HAS_VNSTOCK = False
try:
    from vnstock.explorer.vci import Quote as VCIQuote
    from vnstock.explorer.vci import Listing as VCIListing
    from vnstock.explorer.vci import Trading as VCITrading
    _HAS_VNSTOCK = True
    print("[INIT] vnstock available — using VCI API")
except ImportError:
    VCIQuote = None
    VCIListing = None
    VCITrading = None
    print("[INIT] vnstock NOT available — using direct VNDIRECT/Wifeed API")

from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import market_rules  # bộ rule luận giải nhận định thị trường


# ═══════════════════════════════════════════════════════════════════════
# DIRECT API REPLACEMENTS (no vnstock dependency)
# ═══════════════════════════════════════════════════════════════════════

def _vndirect_ohlcv(symbol, start_ts, end_ts):
    """Fetch OHLCV from VNDIRECT DChart API. Returns dict {t,o,h,l,c,v} or None."""
    url = f'https://dchart-api.vndirect.com.vn/dchart/history?resolution=D&symbol={symbol}&from={start_ts}&to={end_ts}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        if data.get('s') == 'ok' and data.get('c'):
            return data
    except Exception as e:
        print(f"  [VNDIRECT] Error fetching {symbol}: {e}")
    return None


def _vndirect_to_dataframe(data, symbol=None):
    """Convert VNDIRECT DChart response to DataFrame matching VCI format."""
    from datetime import datetime as dt
    df = pd.DataFrame({
        'time': [dt.fromtimestamp(t) for t in data['t']],
        'open': pd.Series(data['o'], dtype=float),
        'high': pd.Series(data['h'], dtype=float),
        'low': pd.Series(data['l'], dtype=float),
        'close': pd.Series(data['c'], dtype=float),
        'volume': pd.Series(data.get('v', [0]*len(data['c'])), dtype=float),
    })
    df.sort_values('time', inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def fetch_ohlcv_direct(symbol, days=730):
    """Fetch OHLCV history as DataFrame — tries VCI first, then VNDIRECT."""
    if _HAS_VNSTOCK:
        try:
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            end_date = datetime.now().strftime("%Y-%m-%d")
            q = VCIQuote(symbol=symbol, show_log=False)
            df = q.history(start=start_date, end=end_date, interval='1D')
            if df is not None and not df.empty:
                return df
        except Exception as e:
            print(f"  [VCI] Fallback to VNDIRECT for {symbol}: {e}")
    
    # Direct VNDIRECT API
    end_ts = int(time.time())
    start_ts = end_ts - days * 86400
    data = _vndirect_ohlcv(symbol, start_ts, end_ts)
    if data:
        return _vndirect_to_dataframe(data, symbol)
    return None


def fetch_price_board_direct(symbols_list):
    """Build price board DataFrame from VNDIRECT DChart (last 2 bars).
    Returns DataFrame with columns: listing_symbol, listing_code, match_match_price,
    listing_ref_price, change_pc — matching VCI price_board format."""
    end_ts = int(time.time())
    start_ts = end_ts - 10 * 86400  # last 10 days to ensure we get 2+ trading bars
    
    results = []
    
    def _fetch_one(sym):
        data = _vndirect_ohlcv(sym, start_ts, end_ts)
        if data and len(data.get('c', [])) >= 2:
            closes = data['c']
            ref_price = float(closes[-2])   # previous close = reference
            match_price = float(closes[-1]) # latest close = match price
            return {
                'listing_symbol': sym,
                'listing_code': sym,
                'match_match_price': match_price,
                'listing_ref_price': ref_price,
            }
        elif data and len(data.get('c', [])) == 1:
            p = float(data['c'][0])
            return {
                'listing_symbol': sym,
                'listing_code': sym,
                'match_match_price': p,
                'listing_ref_price': p,
            }
        return None
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(_fetch_one, s): s for s in symbols_list}
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception:
                pass
    
    if not results:
        return pd.DataFrame()
    
    df = pd.DataFrame(results)
    df['change_pc'] = ((df['match_match_price'] - df['listing_ref_price']) / 
                        df['listing_ref_price'].replace(0, float('nan')) * 100).fillna(0.0)
    return df


def fetch_hose_symbols_direct():
    """Get list of HOSE stock symbols without vnstock — tries Wifeed then fallback."""
    try:
        url = 'https://wifeed.vn/api/thong-tin-co-phieu/danh-sach-ma-chung-khoan'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        items = data.get('data', [])
        # Filter HOSE stocks (loaidn=1 is typically 'Cổ phiếu', san='HOSE')
        hose_syms = [item['code'] for item in items 
                     if item.get('san', '').upper() == 'HOSE']
        if hose_syms:
            print(f"[LISTING] Wifeed: {len(hose_syms)} HOSE stocks")
            return hose_syms
    except Exception as e:
        print(f"[LISTING] Wifeed failed: {e}")
    return None  # caller should use fallback


class _SafeEncoder(json.JSONEncoder):
    """JSON encoder xử lý numpy types và NaN/Inf."""
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            v = float(obj)
            return None if (math.isnan(v) or math.isinf(v)) else v
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        if isinstance(obj, np.bool_):
            return bool(obj)
        return super().default(obj)


sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Setup DeepSeek API - accept key from multiple possible secret names
api_key = (
    os.environ.get("DEEPSEEK_API_KEY") or
    os.environ.get("GROQ_API_KEY") or
    os.environ.get("OPENROUTER_API_KEY")
)
print(f"[CONFIG] API key found: {'YES (len=' + str(len(api_key)) + ')' if api_key else 'NO - will use rule-based fallback'}")

client = OpenAI(
    base_url="https://api.deepseek.com",
    api_key=api_key or "dummy_key",
) if api_key else None

def ask_ai(prompt, system_prompt="Bạn là chuyên gia phân tích chứng khoán."):
    """Gọi DeepSeek API, trả về None nếu thất bại để dùng rule-based fallback."""
    if not api_key or not client:
        print("  ⚠ No API key — using rule-based fallback.")
        return None

    models_to_try = [
        "deepseek-chat",    # DeepSeek V4-Flash — nhanh, rẻ, chất lượng tốt
        "deepseek-reasoner", # DeepSeek R1 — mạnh hơn, dùng khi Flash fail
    ]

    for i, model in enumerate(models_to_try):
        for attempt in range(3):  # retry 3 lần với exponential backoff
            try:
                print(f"  → Calling DeepSeek [{model}] attempt {attempt+1}...")
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=2000,
                    stream=False
                )
                result = response.choices[0].message.content
                print(f"  ✓ DeepSeek [{model}] success ({len(result)} chars)")
                return result
            except Exception as e:
                err_str = str(e).lower()
                if 'rate' in err_str or '429' in err_str or 'limit' in err_str:
                    wait = 30 * (2 ** attempt)  # 30s, 60s, 120s
                    print(f"  ⏳ Rate limit hit. Waiting {wait}s before retry...")
                    time.sleep(wait)
                else:
                    wait = 5 + attempt * 5
                    print(f"  ✗ DeepSeek [{model}] error: {e}. Wait {wait}s...")
                    time.sleep(wait)
                    break  # lỗi khác thì thử model tiếp theo

    print("  ✗ All DeepSeek models failed — using rule-based fallback.")
    return None


def calculate_technical_indicators(df):
    if df is None or df.empty:
        return None
        
    # Sắp xếp thời gian
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'])
        df.sort_values(by='time', inplace=True)
        
    close = df['close']
    high = df['high']
    low = df['low']
    volume = df['volume']
    
    # Moving Averages
    df['ma5']  = close.rolling(window=5).mean()
    df['ma10']  = close.rolling(window=10).mean()
    df['ma20']  = close.rolling(window=20).mean()
    df['ma50']  = close.rolling(window=50).mean()
    df['ma100'] = close.rolling(window=100).mean()
    df['ma200'] = close.rolling(window=200).mean()

    # ROC — Rate of Change (động lượng thị trường)
    df['roc10']  = ta.momentum.ROCIndicator(close=close, window=10).roc()   # ngắn hạn
    df['roc20']  = ta.momentum.ROCIndicator(close=close, window=20).roc()   # trung hạn

    # RSI
    df['rsi5']  = ta.momentum.RSIIndicator(close=close, window=5).rsi()
    df['rsi14'] = ta.momentum.RSIIndicator(close=close, window=14).rsi()

    # Bollinger Bands
    indicator_bb = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
    df['bb_upper']  = indicator_bb.bollinger_hband()
    df['bb_middle'] = indicator_bb.bollinger_mavg()
    df['bb_lower']  = indicator_bb.bollinger_lband()

    # Pivot Points
    df['prev_high']  = high.shift(1)
    df['prev_low']   = low.shift(1)
    df['prev_close'] = close.shift(1)
    df['pivot'] = (df['prev_high'] + df['prev_low'] + df['prev_close']) / 3

    # Volume indicators
    df['cmf']  = ta.volume.ChaikinMoneyFlowIndicator(high=high, low=low, close=close, volume=volume).chaikin_money_flow()
    df['vwap'] = ta.volume.VolumeWeightedAveragePrice(high=high, low=low, close=close, volume=volume).volume_weighted_average_price()
    try:
        df['obv'] = ta.volume.OnBalanceVolumeIndicator(close=close, volume=volume).on_balance_volume()
    except:
        df['obv'] = 0

    # Trend / Volatility
    df['adx'] = ta.trend.ADXIndicator(high=high, low=low, close=close).adx()
    df['atr'] = ta.volatility.AverageTrueRange(high=high, low=low, close=close).average_true_range()

    indicator_keltner = ta.volatility.KeltnerChannel(high=high, low=low, close=close)
    df['keltner_h'] = indicator_keltner.keltner_channel_hband()
    df['keltner_l'] = indicator_keltner.keltner_channel_lband()

    # MACD (12, 26, 9)
    macd_ind = ta.trend.MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    df['macd']        = macd_ind.macd()
    df['macd_signal'] = macd_ind.macd_signal()
    df['macd_diff']   = macd_ind.macd_diff()  # histogram

    # Stochastic %K / %D
    stoch_ind = ta.momentum.StochasticOscillator(high=high, low=low, close=close, window=14, smooth_window=3)
    df['stoch_k'] = stoch_ind.stoch()
    df['stoch_d'] = stoch_ind.stoch_signal()

    # Bollinger Band %B  (0 = lower band, 1 = upper band, 0.5 = middle)
    bb_ind = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
    df['bb_pct'] = bb_ind.bollinger_pband()  # %B

    return df.iloc[-1]

def build_trend_assessment(close, ma_vals):
    """Tạo chuỗi nhận định xu hướng kết hợp tất cả MAs."""
    short_mas  = [(n, v) for n, v in ma_vals if n in ('MA10', 'MA20') and v > 0]
    mid_mas    = [(n, v) for n, v in ma_vals if n == 'MA50' and v > 0]
    long_mas   = [(n, v) for n, v in ma_vals if n in ('MA100', 'MA200') and v > 0]

    def direction(pairs):
        above = [n for n, v in pairs if close >= v]
        below = [n for n, v in pairs if close < v]
        if len(above) == len(pairs) and pairs: return "tăng", above
        if len(below) == len(pairs) and pairs: return "giảm", below
        return "hỗn hợp", []

    lines = []
    if short_mas:
        d, mns = direction(short_mas)
        label = f"{', '.join([n for n,_ in short_mas])}"
        lines.append(f"- **Ngắn hạn** ({label}): xu hướng **{d}**")
    if mid_mas:
        d, mns = direction(mid_mas)
        lines.append(f"- **Trung hạn** (MA50): xu hướng **{d}**")
    if long_mas:
        d, mns = direction(long_mas)
        label = f"{', '.join([n for n,_ in long_mas])}"
        lines.append(f"- **Dài hạn** ({label}): xu hướng **{d}**")

    # Kết hợp tất cả
    all_valid = [(n, v) for n, v in ma_vals if v > 0]
    all_above = all(close >= v for _, v in all_valid)
    all_below = all(close < v for _, v in all_valid)
    if all_valid:
        if all_above:
            lines.append(f"- ✅ **Kết hợp**: Chỉ số **trên tất cả MAs** — xu hướng tăng ở mọi khung thời gian")
        elif all_below:
            lines.append(f"- ❌ **Kết hợp**: Chỉ số **dưới tất cả MAs** — xu hướng giảm ở mọi khung thời gian")
        else:
            lines.append(f"- ⚠️ **Kết hợp**: Chỉ số đang trong vùng **phân kỳ xu hướng** — cần thêm tín hiệu xác nhận")

    return "\n".join(lines) if lines else "Không đủ dữ liệu MA."


# ══════════════════════════════════════════════════════════════════
#  CANDLE PATTERN RECOGNITION
# ══════════════════════════════════════════════════════════════════
def detect_candle_patterns(df):
    """Nhận diện mẫu nến Nhật từ 3 phiên gần nhất — rule-based, không dùng AI."""
    if df is None or len(df) < 3:
        return []
    patterns = []

    def _float(v): return float(v) if pd.notna(v) else 0.0

    c1 = {k: _float(df.iloc[-1][k]) for k in ['open','high','low','close']}
    c2 = {k: _float(df.iloc[-2][k]) for k in ['open','high','low','close']}
    c3 = {k: _float(df.iloc[-3][k]) for k in ['open','high','low','close']}

    def body(c):         return abs(c['close'] - c['open'])
    def upper_sh(c):     return c['high'] - max(c['close'], c['open'])
    def lower_sh(c):     return min(c['close'], c['open']) - c['low']
    def rng(c):          return c['high'] - c['low']
    def bullish(c):      return c['close'] > c['open']
    def bearish(c):      return c['close'] < c['open']

    r1 = rng(c1)
    if r1 <= 0:
        return []

    # 1. Doji — thân nến < 10% biên độ
    if body(c1) / r1 < 0.10:
        patterns.append({'name': 'Doji', 'type': 'neutral',
                         'desc': 'Thị trường do dự, chờ xác nhận chiều'})

    # 2. Hammer — đuôi dưới dài ≥ 2x thân, đuôi trên ngắn
    elif lower_sh(c1) >= 2 * max(body(c1), 0.001*c1['close']) and upper_sh(c1) <= 0.2 * r1:
        patterns.append({'name': 'Hammer 🔨', 'type': 'bullish',
                         'desc': 'Tín hiệu đảo chiều tăng tiềm năng'})

    # 3. Shooting Star — đuôi trên dài ≥ 2x thân, đuôi dưới ngắn
    elif upper_sh(c1) >= 2 * max(body(c1), 0.001*c1['close']) and lower_sh(c1) <= 0.2 * r1:
        patterns.append({'name': 'Shooting Star ⭐', 'type': 'bearish',
                         'desc': 'Tín hiệu đảo chiều giảm tiềm năng'})

    # 4. Marubozu tăng — thân ≥ 90% biên độ, hướng tăng
    elif bullish(c1) and body(c1) / r1 >= 0.90:
        patterns.append({'name': 'Marubozu Tăng', 'type': 'bullish',
                         'desc': 'Lực mua áp đảo, xu hướng tăng mạnh'})

    # 5. Marubozu giảm
    elif bearish(c1) and body(c1) / r1 >= 0.90:
        patterns.append({'name': 'Marubozu Giảm', 'type': 'bearish',
                         'desc': 'Lực bán áp đảo, xu hướng giảm mạnh'})

    # 6. Bullish Engulfing (2 nến)
    if bearish(c2) and bullish(c1) and c1['close'] > c2['open'] and c1['open'] < c2['close']:
        patterns.append({'name': 'Bullish Engulfing', 'type': 'bullish',
                         'desc': 'Bao phủ tăng — đảo chiều mạnh'})

    # 7. Bearish Engulfing
    elif bullish(c2) and bearish(c1) and c1['close'] < c2['open'] and c1['open'] > c2['close']:
        patterns.append({'name': 'Bearish Engulfing', 'type': 'bearish',
                         'desc': 'Bao phủ giảm — đảo chiều mạnh'})

    # 8. Morning Star (3 nến)
    if (bearish(c3) and body(c2) < 0.35 * body(c3)
            and bullish(c1) and c1['close'] > (c3['open'] + c3['close']) / 2):
        patterns.append({'name': 'Morning Star 🌅', 'type': 'bullish',
                         'desc': 'Sao mai — khả năng đảo chiều tăng trung hạn'})

    # 9. Evening Star (3 nến)
    elif (bullish(c3) and body(c2) < 0.35 * body(c3)
            and bearish(c1) and c1['close'] < (c3['open'] + c3['close']) / 2):
        patterns.append({'name': 'Evening Star 🌆', 'type': 'bearish',
                         'desc': 'Sao hôm — khả năng đảo chiều giảm trung hạn'})

    return patterns[:3]   # tối đa 3 patterns


# ══════════════════════════════════════════════════════════════════
#  SUPPORT / RESISTANCE ZONES
# ══════════════════════════════════════════════════════════════════
def find_sr_zones(df, close, window=5, n_zones=6):
    """Tìm vùng hỗ trợ/kháng cự từ swing high/low 52 tuần."""
    if df is None or len(df) < 50:
        return []
    sub = df.tail(252).copy()
    highs = sub['high'].values.tolist()  # convert sang Python float list
    lows  = sub['low'].values.tolist()
    close = float(close)

    sw_highs, sw_lows = [], []
    for i in range(window, len(highs) - window):
        if all(highs[i] >= highs[j] for j in range(i - window, i + window + 1) if j != i):
            sw_highs.append(float(highs[i]))
        if all(lows[i] <= lows[j] for j in range(i - window, i + window + 1) if j != i):
            sw_lows.append(float(lows[i]))

    all_levels = sorted(sw_highs + sw_lows)
    zones, used = [], set()

    for level in all_levels:
        if id(level) in used:
            continue
        cluster = [l for l in all_levels if abs(l - level) / max(level, 1) < 0.012]
        for l in cluster:
            used.add(id(l))
        avg = sum(cluster) / len(cluster)
        dist_pct = (avg - close) / close * 100
        zones.append({
            'level':    float(round(avg, 2)),
            'type':     'resistance' if avg > close else 'support',
            'strength': int(len(cluster)),
            'dist_pct': float(round(dist_pct, 2)),
            'near':     bool(abs(dist_pct) < 1.5),
        })

    zones.sort(key=lambda z: abs(z['dist_pct']))
    return zones[:n_zones]


# ══════════════════════════════════════════════════════════════════
#  HISTORICAL TAS (rolling 20 phiên — zero extra API calls)
# ══════════════════════════════════════════════════════════════════
def compute_tas_history_fast(df, n=50):
    """Tính TAS score cho N phiên gần nhất từ df đã có indicators.
    Mỗi record bao gồm giá OHLCV + các chỉ báo để frontend vẽ biểu đồ."""
    history = []
    if df is None or len(df) < 25:
        return history
    vol_ma20 = df['volume'].rolling(20).mean()

    start_idx = max(-n, -len(df))
    for i in range(start_idx, 0):
        try:
            row = df.iloc[i]
            close_i = float(row.get('close', 0) or 0)
            if close_i <= 0:
                continue

            def _s(k):
                v = row.get(k, None)
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    return 0.0
                try:
                    return float(v)
                except:
                    return 0.0

            vol_i    = _s('volume')
            vma_i    = float(vol_ma20.iloc[i]) if pd.notna(vol_ma20.iloc[i]) else vol_i
            vdiff_i  = ((vol_i - vma_i) / vma_i * 100) if vma_i > 0 else 0

            pseudo = {
                'cmf': _s('cmf'), 'vwap': _s('vwap'),
                'roc10': _s('roc10'), 'roc20': _s('roc20'),
                'adx': _s('adx'), 'keltner_h': _s('keltner_h'), 'keltner_l': _s('keltner_l'),
                'rsi14': _s('rsi14'),
                'macd': _s('macd'), 'macd_signal': _s('macd_signal'), 'macd_diff': _s('macd_diff'),
                'stoch_k': _s('stoch_k'), 'stoch_d': _s('stoch_d'),
                'bb_pct': _s('bb_pct'),
            }
            mas_i = [('MA20', _s('ma20')), ('MA50', _s('ma50')), ('MA200', _s('ma200'))]
            tas_i = compute_tas(close_i, pseudo, vdiff_i, mas_i)

            date_str = str(row['time']).split(' ')[0] if 'time' in row.index else f'D{i}'
            history.append({
                'date':  date_str,
                'score': tas_i['score'],
                'label': tas_i['label'],
                # OHLCV cho biểu đồ giá
                'open':   _s('open'),
                'high':   _s('high'),
                'low':    _s('low'),
                'close':  close_i,
                'volume': vol_i,
                # Indicators cho sub-chart
                'ma20':   _s('ma20'),
                'ma50':   _s('ma50'),
                'bb_upper': _s('bb_upper'),
                'bb_lower': _s('bb_lower'),
                'rsi14':    _s('rsi14'),
                'macd':     _s('macd'),
                'macd_signal': _s('macd_signal'),
                'macd_diff':   _s('macd_diff'),
                'stoch_k':  _s('stoch_k'),
                'stoch_d':  _s('stoch_d'),
                'bb_pct':   _s('bb_pct'),
            })
        except Exception:
            continue
    return history


# ══════════════════════════════════════════════════════════════════
#  SECTOR HEATMAP — Dynamic ICB mapping from VCI API
# ══════════════════════════════════════════════════════════════════

# Fallback hardcoded nếu API ICB không khả dụng
SECTOR_MAP_FALLBACK = {
    'Ngân hàng':         ['VCB','BID','CTG','MBB','TCB','VPB','ACB','HDB','SHB','STB','TPB','LPB','VIB','OCB','MSB','NAB','BAB','KLB','PGB','BVB','SSB','ABB','SGB','VAB','VBB','EIB'],
    'Bất động sản':      ['VHM','VIC','NVL','PDR','DXG','KDH','HDC','DIG','NTL','TDC','NLG','SCR','AGG','HDG','KBC','SJS','DPG','IJC','CEO','LDG','NBB','QCG','HQC','CII','BCG','VRE','API','LHG','DXS','PHR','TDH','NTT','ITA','SZC','BCM','KOS','IDC'],
    'Thép - Xây dựng':   ['HPG','NKG','TLH','POM','HSG','VGS','HT1','BMP','TLG','CTD','HBC','VCG','VGC','C4G','LCG','FCN','CRE','HHV','PC1','REE','DRC','CSM','SRC','DQC','CTR'],
    'Dầu khí':           ['GAS','PLX','PVD','PVS','OIL','BSR','PVC','PVT','PVB','PVG','PXS','PET'],
    'Bán lẻ - Tiêu dùng':['MWG','FRT','MSN','SAB','VNM','MCH','PNJ','VHC','ANV','DGW','HAG','QNS','KDC','SBT','LSS','LTG','BAF','MML','VHE','AAM','AGM','ASM','APF','CMX','NAF','SGN'],
    'Vận tải - Logistics':['HVN','VJC','GMD','HAH','TCH','SCS','VTO','VOS','VNA','STG','ACV','NCT','SGP','PAN','TMS','VSC','DVP'],
    'Công nghệ - Viễn thông':['FPT','CMG','VGI','ELC','SGT','FOX','ITD','MFS','SAM','VTC','ONE'],
    'Điện - Nước - Khí': ['POW','PPC','VSH','BWE','GEG','TTA','NT2','HDG','EVG','EVF','HND','TMP','CHP','SBA','TVS','SHP','APH','GAS','SJD','TBC','PGV','QTP','VSB','CNG','HWS'],
    'Chứng khoán':       ['SSI','VND','HCM','VCI','BSI','AGR','SHS','VIX','CTS','TVB','ORS','APS','DSE','FTS','MBS','TVS','PSI','KIS','EVS','BMS','IVS','WSS','HAC','APG'],
    'Bảo hiểm':          ['BVH','PVI','BMI','BIC','MIG','ABI','PTI','BLI','VNR'],
    'Hóa chất - Phân bón':['DPM','DCM','DGC','CSV','DHC','LAS','BFC','NFC','HVT','DDV','SFG','PMB'],
    'Thủy sản':          ['VHC','ANV','IDI','FMC','ABT','ACL','CMX','AGF','MPC','TS4'],
    'Dệt may - Da giày': ['TCM','TNG','VGT','MSH','STK','GMC','GIL','TVT','ADS','PPH','TET','HDM','VIT','EVE'],
    'Cao su - Gỗ':       ['GVR','PHR','DPR','TRC','TNC','SRC','BRC','HRC','RDP','ACG','GDT','TTF','PTB'],
    'Khoáng sản':        ['MSR','KSV','BMC','DHA','NGC','KSB','NNC','LBM','MIM'],
}


def fetch_icb_mapping():
    """Lấy mapping symbol → sector từ VCI ICB API (Level 2).
    Returns dict {symbol: sector_name} hoặc {} nếu thất bại."""
    if not _HAS_VNSTOCK:
        return {}
    try:
        _listing = VCIListing(show_log=False)
        df_icb = _listing.symbols_by_industries(lang='vi')
        # Lấy ICB Level 2 — đủ chi tiết nhưng không quá nhỏ lẻ
        lv2 = df_icb[df_icb['icb_level'] == 2][['symbol', 'icb_name']].drop_duplicates(subset='symbol')
        mapping = dict(zip(lv2['symbol'], lv2['icb_name']))
        print(f"[ICB] Fetched {len(mapping)} symbol-to-sector mappings (Level 2)")
        return mapping
    except Exception as e:
        print(f"[ICB] Failed to fetch ICB mapping: {e}")
        return {}


def _fallback_sector_mapping():
    """Tạo mapping symbol → sector từ hardcode fallback."""
    mapping = {}
    for sector, tickers in SECTOR_MAP_FALLBACK.items():
        for t in tickers:
            mapping[t] = sector
    return mapping


def get_sector_mapping():
    """Lấy mapping từ custom_sectors.json > VCI API > fallback."""
    import os
    import json
    
    # 1. Ưu tiên đọc từ file custom_sectors.json do người dùng tự nhập
    # Tìm file ở nhiều vị trí: cùng thư mục script, thư mục cha, hoặc CWD
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _parent_dir = os.path.dirname(_script_dir)
    _search_paths = [
        os.path.join(_script_dir, 'custom_sectors.json'),   # data_pipeline/custom_sectors.json
        os.path.join(_parent_dir, 'custom_sectors.json'),   # root/custom_sectors.json
        'custom_sectors.json',                               # CWD
    ]
    for custom_path in _search_paths:
        if os.path.exists(custom_path):
            try:
                with open(custom_path, 'r', encoding='utf-8') as f:
                    custom_map = json.load(f)
                # Các nhóm "tổng hợp" không được ghi đè ngành chuyên biệt
                GENERAL_BUCKETS = {'Tất cả HOSE', 'VN30', 'VN100'}
                mapping = {}
                # Pass 1: ngành chuyên biệt trước
                for sector, tickers in custom_map.items():
                    if sector in GENERAL_BUCKETS:
                        continue
                    for t in tickers:
                        mapping[t] = sector
                # Pass 2: nhóm tổng hợp chỉ điền vào các mã chưa có ngành
                for sector, tickers in custom_map.items():
                    if sector not in GENERAL_BUCKETS:
                        continue
                    for t in tickers:
                        if t not in mapping:
                            mapping[t] = sector
                print(f"[ICB] Loaded custom sector mapping from {custom_path}")
                return mapping
            except Exception as e:
                print(f"[ICB] Error reading {custom_path}: {e}")
            
    # 2. Lấy từ VCI API
    mapping = fetch_icb_mapping()
    if mapping:
        return mapping
        
    # 3. Fallback
    print("[ICB] Using hardcoded fallback mapping")
    return _fallback_sector_mapping()


def compute_sector_heatmap(price_board, icb_mapping=None):
    """Tính % thay đổi TB mỗi ngành từ price_board + ICB mapping."""
    if price_board is None or price_board.empty:
        return []

    ticker_col = next((c for c in price_board.columns
                       if 'code' in c.lower() or 'ticker' in c.lower() or 'symbol' in c.lower()), None)
    if ticker_col is None:
        return []

    # Dùng ICB mapping nếu có, không thì fallback
    if not icb_mapping:
        icb_mapping = _fallback_sector_mapping()

    price_board = price_board.copy()
    price_board['_sector'] = price_board[ticker_col].map(icb_mapping)
    # Bỏ những mã không có sector
    mapped = price_board[price_board['_sector'].notna()]
    if mapped.empty:
        return [], {}

    def _num(val):
        try:
            v = float(val)
            return 0.0 if math.isnan(v) or math.isinf(v) else v
        except:
            return 0.0

    # Lưu raw_stocks cho TẤT CẢ mã trong board (không chỉ mã có sector)
    # Để frontend có thể dùng khi user thêm mã vào custom sector
    raw_stocks = {}
    for _, row in price_board.iterrows():
        sym = str(row[ticker_col])
        raw_stocks[sym] = {
            'change_pc': _num(row.get('change_pc')),
            'match_price': _num(row.get('match_match_price')),
            'listed_share': _num(row.get('listing_listed_share')),
            'accumulated_value': _num(row.get('match_accumulated_value')),
            'sector': str(row.get('_sector', '')) if pd.notna(row.get('_sector')) else ""
        }

    result = []
    for sector, grp in mapped.groupby('_sector'):
        avg_chg = grp['change_pc'].mean()
        if pd.isna(avg_chg):
            avg_chg = 0.0

        # Tính tổng giá trị giao dịch (Tỷ VNĐ)
        total_val = 0
        if 'match_accumulated_value' in grp.columns:
            total_val = (grp['match_accumulated_value'].fillna(0).sum()) / 1000  # Triệu -> Tỷ VNĐ

        # Tính Market Cap dòng tiền
        cap_up = 0
        cap_down = 0
        cap_ref = 0
        
        has_market_cap = 'listing_listed_share' in grp.columns and 'match_match_price' in grp.columns
        
        for _, row in grp.iterrows():
            chg = float(row.get('change_pc', 0) or 0)
            mc = 0
            if has_market_cap:
                mc = float(row.get('listing_listed_share', 0) or 0) * float(row.get('match_match_price', 0) or 0) / 1e9
            
            if chg > 0:
                cap_up += mc
            elif chg < 0:
                cap_down += mc
            else:
                cap_ref += mc

        result.append({
            'sector':     sector,
            'avg_change': float(round(float(avg_chg), 2)),
            'count':      int(len(grp)),
            'tickers':    grp[ticker_col].tolist(),
            'total_val':  float(round(total_val, 2)),
            'cap_up':     float(round(cap_up, 2)),
            'cap_down':   float(round(cap_down, 2)),
            'cap_ref':    float(round(cap_ref, 2))
        })

    # Lọc bỏ nhóm 'Tất cả HOSE' khỏi heatmap/bảng phân tích
    result = [s for s in result if s['sector'] != 'Tất cả HOSE']
    
    # Sắp xếp theo avg_change giảm dần
    result = sorted(result, key=lambda x: x['avg_change'], reverse=True)
    return result, raw_stocks


def build_trend_narrative(close, ma5, ma10, ma20, return_5d, return_20d, mom5, rsi5, adx20):
    """
    Sinh nhận định ngắn/trung hạn dựa trên template PTKT — 100% rule-based, không dùng AI.
    """
    # A. Trạng thái ngắn hạn
    if close > ma5 and close > ma10:
        st_short = 'Tăng'
        pos_short = 'trên'
    elif close < ma5 and close < ma10:
        st_short = 'Giảm'
        pos_short = 'dưới'
    else:
        st_short = 'Đi ngang'
        pos_short = 'gần'

    mom5_sign = 'Dương' if mom5 >= 0 else 'Âm'
    mom5_str  = f'+{mom5:.2f}' if mom5 >= 0 else f'{mom5:.2f}'
    r5_str    = f'+{return_5d:.2f}%' if return_5d >= 0 else f'{return_5d:.2f}%'
    momentum_quality = 'mạnh' if (st_short == 'Tăng' and mom5 > 0) or (st_short == 'Giảm' and mom5 < 0) else 'suy yếu'
    da_str = 'Tăng' if return_5d >= 0 else 'Giảm'

    # C. RSI5
    if rsi5 >= 70:
        rsi_phrase = 'cho thấy vùng quá mua, cảnh báo khả năng điều chỉnh kỹ thuật.'
    elif rsi5 <= 30:
        rsi_phrase = 'cho thấy vùng quá bán, cơ hội xuất hiện nhịp hồi kỹ thuật.'
    else:
        rsi_phrase = 'ở mức trung tính, xu hướng tiếp diễn ổn định.'

    line1 = (
        f"• **Ngắn hạn ({st_short}):** Giá **{close:.2f}** đang nằm {pos_short} cả đường xu hướng 5 phiên "
        f"(**{ma5:.2f}**) và đường xu hướng 10 phiên (**{ma10:.2f}**). "
        f"Đà {da_str.lower()} 5 phiên ({r5_str}) và Mom5 {mom5_sign} ({mom5_str}) "
        f"xác nhận động lực ngắn hạn **{momentum_quality}**. "
        f"Tín hiệu hưng phấn (5 phiên) ở **{rsi5:.1f}** {rsi_phrase}"
    )

    # B. Trạng thái trung hạn
    if close > ma20:
        st_mid   = 'Tăng'
        pos_mid  = 'vượt trên'
        dir_mid  = 'tăng'
    else:
        st_mid   = 'Giảm'
        pos_mid  = 'nằm dưới'
        dir_mid  = 'giảm'
    r20_str = f'+{return_20d:.2f}%' if return_20d >= 0 else f'{return_20d:.2f}%'

    # D. ADX20
    if adx20 < 20:
        adx_phrase = 'cho thấy xu hướng yếu hoặc đang tích lũy đi ngang.'
    elif adx20 < 25:
        adx_phrase = 'cho thấy xu hướng đang hình thành (từ mức yếu).'
    else:
        adx_phrase = 'xác nhận xu hướng hiện tại đang có độ mạnh rất tốt.'

    line2 = (
        f"• **Trung hạn ({st_mid}):** Giá {pos_mid} đường xu hướng 20 phiên (**{ma20:.2f}**) "
        f"và {dir_mid} **{r20_str}** trong 20 phiên. "
        f"Độ mạnh xu hướng (20 phiên) ở **{adx20:.1f}** {adx_phrase}"
    )

    return line1 + '\n\n' + line2


def compute_tas(close, latest, vol_diff, mas):
    """
    Trend Agreement Score (TAS): tính điểm đồng thuận xu hướng từ 9 chỉ báo.
    Mỗi chỉ báo: Bullish=+1 | Neutral=0 | Bearish=-1
    Tổng: đưa về % (-100 → +100)
    """
    def sf(key): return float(latest.get(key, 0) or 0) if pd.notna(latest.get(key, 0)) else 0.0

    ma_map = dict(mas)
    ma20  = ma_map.get('MA20',  0)
    ma50  = ma_map.get('MA50',  0)
    ma200 = ma_map.get('MA200', 0)
    ma100 = ma_map.get('MA100', 0)
    cmf   = sf('cmf')
    roc10 = sf('roc10')
    roc20 = sf('roc20')
    adx   = sf('adx')
    vwap  = sf('vwap')
    kh    = sf('keltner_h')
    kl    = sf('keltner_l')
    rsi14    = sf('rsi14')
    macd     = sf('macd')
    macd_sig = sf('macd_signal')
    stoch_k  = sf('stoch_k')
    stoch_d  = sf('stoch_d')
    bb_pct   = sf('bb_pct')

    indicators = []

    # ── Nhóm 1: Cấu trúc MA (3 chỉ báo) ─────────────────────────────
    if ma20 > 0:
        s = 1 if close > ma20 else -1
        indicators.append({'group': 'Cấu trúc (MA)', 'name': f'Giá vs MA20 ({ma20:.0f})',
                           'status': 'Bullish' if s > 0 else 'Bearish', 'score': s})
    if ma50 > 0:
        s = 1 if close > ma50 else -1
        indicators.append({'group': 'Cấu trúc (MA)', 'name': f'Giá vs MA50 ({ma50:.0f})',
                           'status': 'Bullish' if s > 0 else 'Bearish', 'score': s})
    if ma200 > 0:
        s = 1 if close > ma200 else -1
        indicators.append({'group': 'Cấu trúc (MA)', 'name': f'Giá vs MA200 ({ma200:.0f})',
                           'status': 'Bullish' if s > 0 else 'Bearish', 'score': s})

    # ── Nhóm 2: Động lượng (3 chỉ báo) ─────────────────────────────
    if roc10 > 1.5:
        s, st = 1, 'Bullish'
    elif roc10 < -1.5:
        s, st = -1, 'Bearish'
    else:
        s, st = 0, 'Neutral'
    indicators.append({'group': 'Động lượng', 'name': f'ROC10 ({roc10:+.1f}%)', 'status': st, 'score': s})

    if roc20 > 2:
        s, st = 1, 'Bullish'
    elif roc20 < -2:
        s, st = -1, 'Bearish'
    else:
        s, st = 0, 'Neutral'
    indicators.append({'group': 'Động lượng', 'name': f'ROC20 ({roc20:+.1f}%)', 'status': st, 'score': s})

    # Keltner channel position
    if kh > 0 and kl > 0:
        if close > kh:
            s, st = 1, 'Bullish'
        elif close < kl:
            s, st = -1, 'Bearish'
        else:
            mid_k = (kh + kl) / 2
            s, st = (1, 'Bullish') if close > mid_k else (-1, 'Bearish')
        indicators.append({'group': 'Động lượng', 'name': f'Keltner ({kl:.0f}–{kh:.0f})', 'status': st, 'score': s})

    # ── Nhóm 3: Dòng tiền (3 chỉ báo) ─────────────────────────────
    if cmf > 0.05:
        s, st = 1, 'Bullish'
    elif cmf < -0.05:
        s, st = -1, 'Bearish'
    else:
        s, st = 0, 'Neutral'
    indicators.append({'group': 'Dòng tiền', 'name': f'CMF ({cmf:+.3f})', 'status': st, 'score': s})

    if vwap > 0:
        s = 1 if close > vwap else -1
        indicators.append({'group': 'Dòng tiền', 'name': f'Giá vs VWAP ({vwap:.0f})',
                           'status': 'Bullish' if s > 0 else 'Bearish', 'score': s})

    # Volume vs MA20 Vol
    if vol_diff > 10:
        s, st = 1, 'Bullish'
    elif vol_diff < -10:
        s, st = -1, 'Bearish'
    else:
        s, st = 0, 'Neutral'
    indicators.append({'group': 'Dòng tiền', 'name': f'Vol vs MA20 ({vol_diff:+.0f}%)', 'status': st, 'score': s})

    # ── Nhóm 4: MACD ─────────────────────────────────────────────
    if macd != 0 or macd_sig != 0:
        if macd > macd_sig:
            s, st = 1, 'Bullish'
        else:
            s, st = -1, 'Bearish'
        cross = 'MACD > Signal' if s > 0 else 'MACD < Signal'
        indicators.append({'group': 'MACD', 'name': f'MACD vs Signal ({macd:.2f}/{macd_sig:.2f})', 'status': st, 'score': s})

        # MACD histogram hướng
        if macd_diff := sf('macd_diff'):
            if macd_diff > 0:
                s, st = 1, 'Bullish'
            else:
                s, st = -1, 'Bearish'
            indicators.append({'group': 'MACD', 'name': f'MACD Histogram ({macd_diff:+.2f})', 'status': st, 'score': s})

    # ── Nhóm 5: Stochastic & RSI ────────────────────────────────
    if stoch_k > 0:
        if stoch_k < 20:
            s, st = 1, 'Oversold (cơ hội)'
        elif stoch_k > 80:
            s, st = -1, 'Overbought (thận trọng)'
        else:
            s, st = (1 if stoch_k > stoch_d else -1), ('Bullish' if stoch_k > stoch_d else 'Bearish')
        indicators.append({'group': 'Stochastic', 'name': f'Stoch %K/%D ({stoch_k:.1f}/{stoch_d:.1f})', 'status': st, 'score': s})

    if rsi14 > 0:
        if rsi14 < 30:
            s, st = 1, 'Oversold'
        elif rsi14 > 70:
            s, st = -1, 'Overbought'
        elif rsi14 >= 50:
            s, st = 1, 'Bullish'
        else:
            s, st = -1, 'Bearish'
        indicators.append({'group': 'Stochastic', 'name': f'RSI14 ({rsi14:.1f})', 'status': st, 'score': s})

    # ── Nhóm 6: Bollinger %B ────────────────────────────────────
    if bb_pct != 0:
        if bb_pct < 0.2:
            s, st = 1, 'Gần Lower Band (cơ hội)'
        elif bb_pct > 0.8:
            s, st = -1, 'Gần Upper Band (thận trọng)'
        else:
            s, st = (1 if bb_pct >= 0.5 else -1), ('Bullish' if bb_pct >= 0.5 else 'Bearish')
        indicators.append({'group': 'Bollinger', 'name': f'BB %B ({bb_pct:.2f})', 'status': st, 'score': s})

    # ── Tổng hợp TAS ───────────────────────────────────
    max_score = len(indicators)
    total     = sum(i['score'] for i in indicators)
    pct       = round(total / max(max_score, 1) * 100)

    if pct >= 67:   label = 'STRONG BULLISH'
    elif pct >= 34: label = 'BULLISH'
    elif pct >= 1:  label = 'WEAK BULLISH'
    elif pct == 0:  label = 'NEUTRAL'
    elif pct >= -33: label = 'WEAK BEARISH'
    elif pct >= -66: label = 'BEARISH'
    else:            label = 'STRONG BEARISH'

    return {
        'score': pct,
        'label': label,
        'total_raw': total,
        'max_raw': max_score,
        'indicators': indicators
    }


def compute_breadth_from_board(board_vn30):
    """
    Tính breadth metrics từ price_board — ZERO extra API calls.
    Price_board có sẵn: match_match_price, listing_ref_price, match_52w_high, match_52w_low
    và các trường khác có thể dùng để xấp xỉ MA.
    """
    if board_vn30 is None or board_vn30.empty:
        return None

    cols = board_vn30.columns.tolist()
    print(f"  [BREADTH] Available board columns: {cols[:20]}...")

    results = []
    for _, row in board_vn30.iterrows():
        try:
            cur = float(row.get('match_match_price', 0) or 0)
            ref = float(row.get('listing_ref_price', 0) or 0)
            if cur <= 0 or ref <= 0:
                continue

            # Tìm các cột 52w high/low nếu có
            w52h = None
            w52l = None
            for col in cols:
                if '52' in col and ('high' in col.lower() or 'h' == col[-1]):
                    try: w52h = float(row[col] or 0) or None
                    except: pass
                if '52' in col and ('low' in col.lower() or 'l' == col[-1]):
                    try: w52l = float(row[col] or 0) or None
                    except: pass

            entry = {
                'change_pc': float(row.get('change_pc', 0) or 0),
                'above20': None,   # không thể tính được chính xác
                'above50': None,
                'above200': None,
            }

            # Xấp xỉ: nếu giá hiện tại cách đỉnh 52w < 15% → khả năng cao đang trên MA200
            if w52h and w52l and w52h > 0:
                pct_from_52h = (cur - w52h) / w52h * 100  # âm = dưới đỉnh
                pct_from_52l = (cur - w52l) / max(w52l, 1) * 100
                mid52 = (w52h + w52l) / 2
                entry['above200'] = cur > mid52   # proxy: trử giữ tốt hơn nửa năm

            results.append(entry)
        except Exception as e:
            continue

    n = len(results)
    if n == 0:
        return None

    n_up   = sum(1 for r in results if r['change_pc'] > 0)
    n_down = sum(1 for r in results if r['change_pc'] < 0)
    n_flat = sum(1 for r in results if r['change_pc'] == 0)
    # proxy MA200 breadth từ 52w mid
    n_above_proxy200 = sum(1 for r in results if r['above200'] is True)
    pct_proxy200 = round(n_above_proxy200 / n * 100, 1) if n > 0 else 0

    return {
        'total': n,
        'n_up': n_up, 'n_down': n_down, 'n_flat': n_flat,
        'ratio': round(n_up / max(n_down, 1), 2),
        'pct_proxy_above_mid52': pct_proxy200,  # proxy cho long-term breadth
        'has_exact_ma': False,   # chưa có MA chính xác
    }


def _smc_overlap(bull_obs, bear_obs, wichlap="Recent"):
    """Remove overlapping order blocks matching BigBeluga overlap() logic."""
    def _is_overlap(a, b):
        return (
            (a['btm'] > b['btm'] and a['btm'] < b['top']) or
            (a['top'] < b['top'] and a['btm'] > b['btm']) or
            (a['top'] > b['top'] and a['btm'] < b['btm']) or
            (a['top'] < b['top'] and a['top'] > b['btm'])
        )

    if len(bull_obs) > 1:
        current = bull_obs[0]
        for i in range(len(bull_obs) - 1, 0, -1):
            if _is_overlap(bull_obs[i], current):
                v = i if wichlap == "Recent" else 0
                if v < len(bull_obs):
                    bull_obs.pop(v)
                    if v == 0 and bull_obs:
                        current = bull_obs[0]

    if len(bear_obs) > 1:
        current = bear_obs[0]
        for i in range(len(bear_obs) - 1, 0, -1):
            if _is_overlap(bear_obs[i], current):
                v = i if wichlap == "Recent" else 0
                if v < len(bear_obs):
                    bear_obs.pop(v)
                    if v == 0 and bear_obs:
                        current = bear_obs[0]

    if bull_obs and bear_obs:
        current = bear_obs[0]
        for i in range(len(bull_obs) - 1, -1, -1):
            if _is_overlap(bull_obs[i], current):
                v = 0 if wichlap == "Recent" else i
                if v < len(bull_obs):
                    bull_obs.pop(v)

    if bull_obs and bear_obs:
        current = bull_obs[0]
        for i in range(len(bear_obs) - 1, -1, -1):
            if _is_overlap(bear_obs[i], current):
                v = 0 if wichlap == "Recent" else i
                if v < len(bear_obs):
                    bear_obs.pop(v)


def _smc_overlap_fvg(bl_fvg, br_fvg):
    """Remove overlapping FVGs matching BigBeluga overlapFVG() logic."""
    def _is_overlap(a, b):
        return (
            (a['btm'] > b['btm'] and a['btm'] < b['top']) or
            (a['top'] < b['top'] and a['btm'] > b['btm']) or
            (a['top'] > b['top'] and a['btm'] < b['btm']) or
            (a['top'] < b['top'] and a['top'] > b['btm'])
        )

    if len(bl_fvg) > 1:
        cur = bl_fvg[0]
        for i in range(len(bl_fvg) - 1, 0, -1):
            if _is_overlap(bl_fvg[i], cur):
                bl_fvg.pop(i)

    if len(br_fvg) > 1:
        cur = br_fvg[0]
        for i in range(len(br_fvg) - 1, 0, -1):
            if _is_overlap(br_fvg[i], cur):
                br_fvg.pop(i)

    if bl_fvg and br_fvg:
        cur = br_fvg[0]
        for i in range(len(bl_fvg) - 1, -1, -1):
            if _is_overlap(bl_fvg[i], cur):
                bl_fvg.pop(i)

    if bl_fvg and br_fvg:
        cur = bl_fvg[0]
        for i in range(len(br_fvg) - 1, -1, -1):
            if _is_overlap(br_fvg[i], cur):
                br_fvg.pop(i)


def build_smc_interpretation(symbol, close, trend, last_event, bos_level, choch_level,
                             bull_obs, bear_obs, bull_fvgs, bear_fvgs, recent_sweeps):
    """Sinh luận giải chi tiết bằng tiếng Việt cho chỉ báo BigBeluga Smart Money Concepts."""
    trend_label = "TĂNG (Bullish Structure)" if trend == 1 else ("GIẢM (Bearish Structure)" if trend == -1 else "TRUNG TÍNH")
    trend_emoji = "🟢" if trend == 1 else ("🔴" if trend == -1 else "🟡")

    lines = []
    lines.append(f"### 1. Cấu trúc Thị trường (Market Structure) — {symbol}")
    lines.append(
        f"{trend_emoji} **Cấu trúc chủ đạo:** **{trend_label}** tại vùng giá **{close:,.2f}**."
    )

    if last_event:
        ev_type = last_event['txt']
        ev_dir = "Tăng (Bullish)" if last_event['dir'] == 'bull' else "Giảm (Bearish)"
        ev_mean = (
            "xác nhận tiếp diễn xu hướng" if ev_type == "BOS"
            else ("tín hiệu đảo chiều cấu trúc quan trọng" if ev_type == "CHoCH" else "cú quét thanh khoản (Liquidity Sweep)")
        )
        lines.append(
            f"- **Tín hiệu cấu trúc gần nhất:** **{ev_type} {ev_dir}** tại mốc **{last_event['y']:,.2f}** (phiên `{last_event['x2_date']}`), cho thấy {ev_mean}."
        )

    if choch_level is not None:
        dist_choch = (choch_level - close) / close * 100 if close > 0 else 0
        choch_role = "ngưỡng hỗ trợ bảo vệ xu hướng Tăng (nếu đóng cửa thủng mốc này → đảo chiều sang Giảm)" if trend == 1 else "ngưỡng kháng cự đảo chiều (nếu đóng cửa vượt mốc này → đảo chiều sang Tăng)"
        lines.append(f"- **Mốc CHoCH hiện tại:** `{choch_level:,.2f}` ({dist_choch:+.2f}% so với giá hiện tại) — {choch_role}.")

    if bos_level is not None:
        dist_bos = (bos_level - close) / close * 100 if close > 0 else 0
        bos_role = "đỉnh cấu trúc cần đóng cửa vượt qua để xác nhận BOS Tăng tiếp diễn" if trend == 1 else "đáy cấu trúc cần chú ý để tránh kích hoạt BOS Giảm tiếp diễn"
        lines.append(f"- **Mốc BOS hiện tại:** `{bos_level:,.2f}` ({dist_bos:+.2f}% so với giá hiện tại) — {bos_role}.")

    # Liquidity Sweeps
    lines.append("\n### 2. Quét Thanh khoản (Liquidity Sweep `x`)")
    if recent_sweeps:
        sw = recent_sweeps[0]
        if sw['dir'] == 'bull':
            lines.append(
                f"- ⚠️ **Cảnh báo Bull-side Sweep (`x`)** phiên `{sw['x2_date']}` quanh **{sw['y']:,.2f}**: "
                f"Giá đã chọc râu vượt đỉnh cũ nhưng đóng cửa quay đầu xuống dưới — dấu hiệu Smart Money quét thanh khoản phe mua (Bull Trap ngắn hạn)."
            )
        else:
            lines.append(
                f"- 🟢 **Tín hiệu Bear-side Sweep (`x`)** phiên `{sw['x2_date']}` quanh **{sw['y']:,.2f}**: "
                f"Giá rút chân quét thủng đáy cũ rồi đóng cửa bật trở lại — dấu hiệu Smart Money gom hàng / rũ bỏ (Spring / Bear Trap)."
            )
    else:
        lines.append("- Chưa ghi nhận cú quét thanh khoản (`x`) mới trong các phiên gần nhất; cấu trúc giá vận động thuần theo phá vỡ thân nến.")

    # Volumetric Order Blocks
    lines.append("\n### 3. Vùng Order Block Khối lượng lớn (Volumetric OB)")
    near_bull_ob = None
    near_bear_ob = None

    if bull_obs:
        top_b = bull_obs[0]
        dist_b = (close - top_b['top']) / close * 100 if close > 0 else 0
        in_zone = (top_b['btm'] <= close <= top_b['top'] * 1.015)
        if in_zone:
            near_bull_ob = top_b
        lines.append(
            f"- 🟢 **Bullish OB gần nhất (Vùng Cầu tổ chức):** `{top_b['btm']:,.2f} – {top_b['top']:,.2f}` "
            f"(Mid-line: `{top_b['avg']:,.2f}`, chiếm **{top_b['vol_pct']}%** tỷ trọng KL trong top 5 OB, hình thành `{top_b['date']}`)."
            + (" ⚡ **Giá đang tiếp cận/kiểm định trực tiếp vùng Cầu này!**" if in_zone else f" (Cách giá hiện tại {dist_b:+.2f}%).")
        )
    else:
        lines.append("- 🟢 **Bullish OB:** Hiện chưa có vùng Bullish OB còn hiệu lực (các vùng cầu cũ đã bị xuyên thủng/mitigate).")

    if bear_obs:
        top_s = bear_obs[0]
        dist_s = (top_s['btm'] - close) / close * 100 if close > 0 else 0
        in_zone = (top_s['btm'] * 0.985 <= close <= top_s['top'])
        if in_zone:
            near_bear_ob = top_s
        lines.append(
            f"- 🔴 **Bearish OB gần nhất (Vùng Cung tổ chức):** `{top_s['btm']:,.2f} – {top_s['top']:,.2f}` "
            f"(Mid-line: `{top_s['avg']:,.2f}`, chiếm **{top_s['vol_pct']}%** tỷ trọng KL trong top 5 OB, hình thành `{top_s['date']}`)."
            + (" ⚡ **Giá đang chạm vùng Cung kháng cự mạnh này!**" if in_zone else f" (Cách giá hiện tại {dist_s:+.2f}%).")
        )
    else:
        lines.append("- 🔴 **Bearish OB:** Hiện chưa có vùng Bearish OB cản phía trên (không gian tăng thoáng hoặc đã hấp thụ hết cung cũ).")

    # FVG
    lines.append("\n### 4. Khoảng trống Giá trị Hợp lý (Fair Value Gap — FVG)")
    if bull_fvgs or bear_fvgs:
        if bull_fvgs:
            f = bull_fvgs[0]
            lines.append(f"- 🟢 **Bullish FVG chưa lấp:** `{f['btm']:,.2f} – {f['top']:,.2f}` (`{f['date']}`) — đóng vai trò vùng đệm hỗ trợ / hút giá khi điều chỉnh.")
        if bear_fvgs:
            f = bear_fvgs[0]
            lines.append(f"- 🔴 **Bearish FVG chưa lấp:** `{f['btm']:,.2f} – {f['top']:,.2f}` (`{f['date']}`) — đóng vai trò vùng kháng cự / mục tiêu hồi phục nếu giá bật tăng.")
    else:
        lines.append("- Không còn khoảng trống FVG mất cân bằng lớn chưa được lấp quanh vùng giá hiện tại.")

    # Actionable synthesis
    lines.append("\n### 5. Luận giải & Chiến lược Hành động")
    if trend == 1:
        if near_bull_ob:
            lines.append(
                f"➡️ **Ưu tiên Canh Mua / Nắm giữ:** Cấu trúc đang **Bullish** và giá đang kiểm định **Bullish OB** (`{near_bull_ob['btm']:,.2f}–{near_bull_ob['top']:,.2f}`). "
                f"Nếu xuất hiện nến rút chân giữ vững trên `{near_bull_ob['btm']:,.2f}`, xác suất cao tiếp tục hướng lên phá **BOS**."
            )
        elif near_bear_ob:
            lines.append(
                f"➡️ **Thận trọng Chốt lời từng phần:** Dù cấu trúc vẫn **Bullish**, giá đang tiến sát vùng **Bearish OB** (`{near_bear_ob['btm']:,.2f}–{near_bear_ob['top']:,.2f}`). "
                f"Hạn chế mua đuổi, chờ hấp thụ xong vùng cung này hoặc đợi nhịp pullback về hỗ trợ."
            )
        else:
            lines.append(
                f"➡️ **Theo dõi Xu hướng Tăng:** Cấu trúc **Bullish** được duy trì chừng nào giá không đóng cửa dưới mốc **CHoCH** (`{choch_level:,.2f}` nếu có). "
                f"Điểm vào tối ưu là các nhịp hồi kiểm định lại vùng **Bullish OB** hoặc **Mid-line OB**."
            )
    else:
        if near_bear_ob:
            lines.append(
                f"➡️ **Cảnh giác Áp lực Bán:** Cấu trúc đang **Bearish** và giá vừa hồi lên vùng **Bearish OB** (`{near_bear_ob['btm']:,.2f}–{near_bear_ob['top']:,.2f}`). "
                f"Đây là vùng cung tiềm ẩn lực bán của tổ chức; chỉ đảo chiều tích cực nếu đóng cửa vượt dứt khoát **CHoCH**."
            )
        elif near_bull_ob:
            lines.append(
                f"➡️ **Theo dõi Phản ứng Tạo đáy:** Cấu trúc vẫn **Bearish**, nhưng giá đã về tới vùng **Bullish OB** (`{near_bull_ob['btm']:,.2f}–{near_bull_ob['top']:,.2f}`). "
                f"Chờ tín hiệu xác nhận **CHoCH Tăng** hoặc **Liquidity Sweep đáy (`x`)** trước khi giải ngân mới."
            )
        else:
            lines.append(
                f"➡️ **Phòng thủ / Chờ Xác nhận:** Cấu trúc **Bearish** vẫn chi phối. Ưu tiên quản trị rủi ro và chờ giá đóng cửa vượt **CHoCH** (`{choch_level:,.2f}` nếu có) để xác nhận đảo chiều xu hướng."
            )

    return "\n".join(lines)


def compute_bigbeluga_smc(df, symbol="", mslen=5, oblast=5, fvg_num=5, swing_limit=100):
    """
    Python port của chỉ báo BigBeluga - Smart Money Concepts [1.0.0] (Pine Script v5).
    Tính Market Structure (BOS, CHoCH, Sweep x), Volumetric Order Blocks và Fair Value Gaps.
    """
    if df is None or len(df) < 20:
        return None

    try:
        df_s = df.sort_values('time').reset_index(drop=True)
        n = len(df_s)
        dates = [str(t).split(' ')[0] for t in df_s['time']]
        opens = df_s['open'].astype(float).values
        highs = df_s['high'].astype(float).values
        lows = df_s['low'].astype(float).values
        closes = df_s['close'].astype(float).values
        vols = df_s['volume'].astype(float).values if 'volume' in df_s.columns else np.zeros(n)

        # ATR(200) using Wilder's RMA (matching ta.atr(200))
        prev_close = np.roll(closes, 1)
        prev_close[0] = closes[0]
        tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev_close), np.abs(lows - prev_close)))
        atr200 = pd.Series(tr).ewm(alpha=1.0 / 200.0, adjust=False).mean().values

        # Helper matching ms.find(use_max, sweep=False, useob)
        def _find_extreme(i, start_bar, use_max, useob):
            start_bar = max(0, min(i, start_bar))
            end_offset = (i - start_bar) - 1
            if end_offset < 0:
                end_offset = i - start_bar
            max_v = -1.0
            min_v = 1e18
            idx = 0
            if use_max:
                for off in range(0, end_offset + 1):
                    b = i - off
                    if highs[b] > max_v:
                        max_v = highs[b]
                        min_v = lows[b]
                        idx = off
                if useob and (i - (idx + 1)) >= 0:
                    if highs[i - (idx + 1)] > highs[i - idx]:
                        idx = idx + 1
            else:
                for off in range(0, end_offset + 1):
                    b = i - off
                    if lows[b] < min_v:
                        min_v = lows[b]
                        max_v = highs[b]
                        idx = off
                if useob and (i - (idx + 1)) >= 0:
                    if lows[i - (idx + 1)] < lows[i - idx]:
                        idx = idx + 1
            return idx

        def _add_ob(block, is_bull, cords, idx, i):
            b = max(0, i - idx)
            top_v = float(cords) if is_bull else float(highs[b])
            btm_v = float(lows[b]) if is_bull else float(cords)
            if top_v < btm_v:
                top_v, btm_v = btm_v, top_v
            block.insert(0, {
                'bull': bool(is_bull),
                'top': round(top_v, 2),
                'btm': round(btm_v, 2),
                'avg': round((top_v + btm_v) / 2.0, 2),
                'bar': b,
                'date': dates[b],
                'vol': float(vols[b]),
                'dir': 1 if closes[b] > opens[b] else -1,
                'isbb': False,
            })

        ms = {
            'bos': None, 'choch': None, 'loc': 0, 'temp': 0,
            'trend': 0, 'start': 0, 'main': None, 'xloc': 0, 'txt': None
        }
        blob = []
        brob = []
        bldw = []
        brdw = []
        bl_fvg = []
        br_fvg = []

        up = None
        dn = None
        phn, php = [], []
        pln, plp = [], []

        for i in range(n):
            h, l, c, o = float(highs[i]), float(lows[i]), float(closes[i]), float(opens[i])
            crossup = False
            crossdn = False

            # Pivot high/low with left=mslen, right=mslen
            if i >= mslen * 2:
                piv_idx = i - mslen
                w_h = highs[piv_idx - mslen: piv_idx + mslen + 1]
                w_l = lows[piv_idx - mslen: piv_idx + mslen + 1]
                if highs[piv_idx] == np.max(w_h) and np.sum(w_h == highs[piv_idx]) == 1:
                    phn.insert(0, piv_idx)
                    php.insert(0, float(highs[piv_idx]))
                if lows[piv_idx] == np.min(w_l) and np.sum(w_l == lows[piv_idx]) == 1:
                    pln.insert(0, piv_idx)
                    plp.insert(0, float(lows[piv_idx]))

            if php and h > php[0]:
                php.clear()
                phn.clear()
            if plp and l < plp[0]:
                plp.clear()
                pln.clear()

            if up is None:
                up = h
            if dn is None:
                dn = l
            if h > up:
                up = h
                dn = l
                crossup = True
            if l < dn:
                up = h
                dn = l
                crossdn = True

            idbull = _find_extreme(i, ms['loc'], False, True)
            idbear = _find_extreme(i, ms['loc'], True, True)
            b_bear = max(0, i - idbear)
            b_bull = max(0, i - idbull)
            btmP = max(lows[b_bear], highs[b_bear] - atr200[b_bear])
            topP = min(highs[b_bull], lows[b_bull] + atr200[b_bull])

            if ms['start'] == 0:
                ms = {
                    'bos': h, 'choch': l, 'loc': i, 'temp': i,
                    'trend': 0, 'start': 1, 'main': None, 'xloc': i, 'txt': None
                }
                bldw.insert(0, {'x1': i, 'x2': i, 'x1_date': dates[i], 'x2_date': dates[i], 'y': round(h, 2), 'txt': 'CHoCH', 'dir': 'bull', 'style': 'dashed'})
                brdw.insert(0, {'x1': i, 'x2': i, 'x1_date': dates[i], 'x2_date': dates[i], 'y': round(l, 2), 'txt': 'CHoCH', 'dir': 'bear', 'style': 'dashed'})

            elif ms['start'] == 1:
                if l <= ms['choch'] and c >= ms['choch']:
                    ms['choch'] = l
                    ms['xloc'] = i
                    brdw[0]['x2'] = i
                    brdw[0]['x2_date'] = dates[i]
                    brdw[0]['style'] = 'dotted'
                    brdw[0]['txt'] = 'x'
                    brdw.insert(0, {'x1': i, 'x2': i, 'x1_date': dates[i], 'x2_date': dates[i], 'y': round(l, 2), 'txt': 'CHoCH', 'dir': 'bear', 'style': 'dashed'})
                elif h >= ms['bos'] and c <= ms['bos']:
                    ms['bos'] = h
                    ms['xloc'] = i
                    bldw[0]['x2'] = i
                    bldw[0]['x2_date'] = dates[i]
                    bldw[0]['style'] = 'dotted'
                    bldw[0]['txt'] = 'x'
                    bldw.insert(0, {'x1': i, 'x2': i, 'x1_date': dates[i], 'x2_date': dates[i], 'y': round(h, 2), 'txt': 'CHoCH', 'dir': 'bull', 'style': 'dashed'})
                elif c <= ms['choch']:
                    ms['txt'] = 'choch'
                    _add_ob(blob, True, topP, idbull, i)
                    ms['trend'] = -1
                    ms['choch'] = ms['bos']
                    ms['bos'] = None
                    ms['start'] = 2
                    ms['loc'] = i
                    ms['main'] = l
                    ms['temp'] = i
                    ms['xloc'] = i
                    brdw[0]['x2'] = i
                    brdw[0]['x2_date'] = dates[i]
                    brdw[0]['style'] = 'solid'
                elif c >= ms['bos']:
                    ms['txt'] = 'choch'
                    _add_ob(brob, False, btmP, idbear, i)
                    ms['trend'] = 1
                    ms['bos'] = None
                    ms['start'] = 2
                    ms['loc'] = i
                    ms['main'] = h
                    ms['temp'] = i
                    ms['xloc'] = i
                    bldw[0]['x2'] = i
                    bldw[0]['x2_date'] = dates[i]
                    bldw[0]['style'] = 'solid'

            elif ms['start'] == 2:
                if ms['trend'] == -1:
                    if l <= ms['main']:
                        ms['main'] = l
                        ms['temp'] = i

                    if i % mslen == 0 and ms['bos'] is not None and php:
                        if php[0] < ms['choch']:
                            ms['choch'] = php[0]
                            ms['loc'] = phn[0]
                            ms['xloc'] = phn[0]
                            ms['temp'] = phn[0]
                            bldw[0]['x1'] = phn[0]
                            bldw[0]['x1_date'] = dates[phn[0]]
                            bldw[0]['x2'] = i
                            bldw[0]['x2_date'] = dates[i]
                            bldw[0]['y'] = round(php[0], 2)

                    if ms['bos'] is None and i > 0:
                        if crossup and c > o and closes[i - 1] > opens[i - 1]:
                            ms['bos'] = ms['main']
                            ms['loc'] = ms['temp']
                            ms['xloc'] = ms['loc']
                            brdw.insert(0, {'x1': ms['loc'], 'x2': i, 'x1_date': dates[ms['loc']], 'x2_date': dates[i], 'y': round(float(lows[ms['loc']]), 2), 'txt': 'BOS', 'dir': 'bear', 'style': 'dashed'})

                    if ms['bos'] is not None and brdw:
                        brdw[0]['x2'] = i
                        brdw[0]['x2_date'] = dates[i]
                    if bldw:
                        bldw[0]['x2'] = i
                        bldw[0]['x2_date'] = dates[i]

                    if ms['bos'] is not None:
                        if l <= ms['bos'] and c >= ms['bos']:
                            ms['bos'] = l
                            ms['xloc'] = i
                            brdw[0]['x2'] = i
                            brdw[0]['x2_date'] = dates[i]
                            brdw[0]['style'] = 'dotted'
                            brdw[0]['txt'] = 'x'
                            brdw.insert(0, {'x1': i, 'x2': i, 'x1_date': dates[i], 'x2_date': dates[i], 'y': round(l, 2), 'txt': 'BOS', 'dir': 'bear', 'style': 'dashed'})
                        elif c <= ms['bos']:
                            ms['txt'] = 'bos'
                            _add_ob(brob, False, btmP, idbear, i)
                            idx_h = _find_extreme(i, ms['loc'], True, False)
                            b_h = max(0, i - idx_h)
                            ms['xloc'] = i
                            ms['bos'] = None
                            ms['choch'] = float(highs[b_h])
                            ms['loc'] = b_h
                            brdw[0]['x2'] = i
                            brdw[0]['x2_date'] = dates[i]
                            brdw[0]['style'] = 'solid'
                            bldw[0]['x1'] = b_h
                            bldw[0]['x1_date'] = dates[b_h]
                            bldw[0]['x2'] = i
                            bldw[0]['x2_date'] = dates[i]
                            bldw[0]['y'] = round(float(highs[b_h]), 2)

                    if h >= ms['choch'] and c <= ms['choch']:
                        ms['choch'] = h
                        ms['xloc'] = i
                        bldw[0]['x2'] = i
                        bldw[0]['x2_date'] = dates[i]
                        bldw[0]['style'] = 'dotted'
                        bldw[0]['txt'] = 'x'
                        bldw.insert(0, {'x1': i, 'x2': i, 'x1_date': dates[i], 'x2_date': dates[i], 'y': round(h, 2), 'txt': 'CHoCH', 'dir': 'bull', 'style': 'dashed'})
                    elif c >= ms['choch']:
                        ms['txt'] = 'choch'
                        _add_ob(blob, True, topP, idbull, i)
                        idx_l = _find_extreme(i, ms['loc'], False, False)
                        b_l = max(0, i - idx_l)
                        if ms['bos'] is None:
                            ms['choch'] = float(lows[b_l])
                            brdw.insert(0, {'x1': ms['temp'], 'x2': i, 'x1_date': dates[ms['temp']], 'x2_date': dates[i], 'y': round(l, 2), 'txt': 'BOS', 'dir': 'bear', 'style': 'dashed'})
                        else:
                            ms['choch'] = ms['bos']
                        ms['bos'] = None
                        ms['main'] = h
                        ms['trend'] = 1
                        ms['loc'] = i
                        ms['xloc'] = i
                        ms['temp'] = i
                        bldw[0]['x2'] = i
                        bldw[0]['x2_date'] = dates[i]
                        bldw[0]['txt'] = 'CHoCH'
                        bldw[0]['style'] = 'solid'
                        brdw[0]['x2'] = i
                        brdw[0]['x2_date'] = dates[i]
                        brdw[0]['y'] = round(ms['choch'], 2)
                        brdw[0]['txt'] = 'CHoCH'

                elif ms['trend'] == 1:
                    if h >= ms['main']:
                        ms['main'] = h
                        ms['temp'] = i

                    if ms['bos'] is None and i > 0:
                        if crossdn and c < o and closes[i - 1] < opens[i - 1]:
                            ms['bos'] = ms['main']
                            ms['loc'] = ms['temp']
                            ms['xloc'] = ms['loc']
                            bldw.insert(0, {'x1': ms['loc'], 'x2': i, 'x1_date': dates[ms['loc']], 'x2_date': dates[i], 'y': round(float(highs[ms['loc']]), 2), 'txt': 'BOS', 'dir': 'bull', 'style': 'dashed'})

                    if i % mslen == 0 and ms['bos'] is not None and plp:
                        if plp[0] > ms['choch']:
                            ms['choch'] = plp[0]
                            ms['loc'] = pln[0]
                            ms['xloc'] = pln[0]
                            ms['temp'] = pln[0]
                            brdw[0]['x1'] = pln[0]
                            brdw[0]['x1_date'] = dates[pln[0]]
                            brdw[0]['x2'] = i
                            brdw[0]['x2_date'] = dates[i]
                            brdw[0]['y'] = round(plp[0], 2)

                    if ms['bos'] is not None and bldw:
                        bldw[0]['x2'] = i
                        bldw[0]['x2_date'] = dates[i]
                    if brdw:
                        brdw[0]['x2'] = i
                        brdw[0]['x2_date'] = dates[i]

                    if ms['bos'] is not None:
                        if h >= ms['bos'] and c <= ms['bos']:
                            ms['bos'] = h
                            ms['xloc'] = i
                            bldw[0]['x2'] = i
                            bldw[0]['x2_date'] = dates[i]
                            bldw[0]['style'] = 'dotted'
                            bldw[0]['txt'] = 'x'
                            bldw.insert(0, {'x1': i, 'x2': i, 'x1_date': dates[i], 'x2_date': dates[i], 'y': round(h, 2), 'txt': 'BOS', 'dir': 'bull', 'style': 'dashed'})
                        elif c >= ms['bos']:
                            ms['txt'] = 'bos'
                            _add_ob(blob, True, topP, idbull, i)
                            idx_l = _find_extreme(i, ms['loc'], False, False)
                            b_l = max(0, i - idx_l)
                            ms['xloc'] = i
                            ms['bos'] = None
                            ms['choch'] = float(lows[b_l])
                            ms['loc'] = b_l
                            bldw[0]['x2'] = i
                            bldw[0]['x2_date'] = dates[i]
                            bldw[0]['style'] = 'solid'
                            brdw[0]['x1'] = b_l
                            brdw[0]['x1_date'] = dates[b_l]
                            brdw[0]['x2'] = i
                            brdw[0]['x2_date'] = dates[i]
                            brdw[0]['y'] = round(float(lows[b_l]), 2)

                    if l <= ms['choch'] and c >= ms['choch']:
                        ms['choch'] = l
                        ms['xloc'] = i
                        brdw[0]['x2'] = i
                        brdw[0]['x2_date'] = dates[i]
                        brdw[0]['style'] = 'dotted'
                        brdw[0]['txt'] = 'x'
                        brdw.insert(0, {'x1': i, 'x2': i, 'x1_date': dates[i], 'x2_date': dates[i], 'y': round(l, 2), 'txt': 'CHoCH', 'dir': 'bear', 'style': 'dashed'})
                    elif c <= ms['choch']:
                        ms['txt'] = 'choch'
                        _add_ob(brob, False, btmP, idbear, i)
                        idx_h = _find_extreme(i, ms['loc'], True, False)
                        b_h = max(0, i - idx_h)
                        if ms['bos'] is None:
                            ms['choch'] = float(highs[b_h])
                            bldw.insert(0, {'x1': ms['temp'], 'x2': i, 'x1_date': dates[ms['temp']], 'x2_date': dates[i], 'y': round(h, 2), 'txt': 'BOS', 'dir': 'bull', 'style': 'dashed'})
                        else:
                            ms['choch'] = ms['bos']
                        ms['bos'] = None
                        ms['main'] = l
                        ms['trend'] = -1
                        ms['loc'] = i
                        ms['temp'] = i
                        ms['xloc'] = i
                        brdw[0]['x2'] = i
                        brdw[0]['x2_date'] = dates[i]
                        brdw[0]['txt'] = 'CHoCH'
                        brdw[0]['style'] = 'solid'
                        bldw[0]['x2'] = i
                        bldw[0]['x2_date'] = dates[i]
                        bldw[0]['y'] = round(ms['choch'], 2)
                        bldw[0]['txt'] = 'CHoCH'

            # OB Mitigation (Close method, obshowbb=False)
            blob = [ob for ob in blob if min(c, o) >= ob['btm']]
            brob = [ob for ob in brob if max(c, o) <= ob['top']]
            _smc_overlap(blob, brob, wichlap="Recent")

            # FVG detection & mitigation (Close method)
            if i >= 3:
                if lows[i - 1] > highs[i - 3] and closes[i - 2] > lows[i - 2]:
                    bl_fvg.insert(0, {
                        'top': round(float(lows[i - 1]), 2),
                        'btm': round(float(highs[i - 3]), 2),
                        'avg': round(float((lows[i - 1] + highs[i - 3]) / 2.0), 2),
                        'bar': i - 3,
                        'date': dates[i - 3],
                        'bull': True
                    })
                if lows[i - 3] > highs[i - 1] and closes[i - 2] < highs[i - 2]:
                    br_fvg.insert(0, {
                        'top': round(float(lows[i - 3]), 2),
                        'btm': round(float(highs[i - 1]), 2),
                        'avg': round(float((lows[i - 3] + highs[i - 1]) / 2.0), 2),
                        'bar': i - 3,
                        'date': dates[i - 3],
                        'bull': False
                    })
            bl_fvg = [f for f in bl_fvg if min(c, o) >= f['btm']]
            br_fvg = [f for f in br_fvg if max(c, o) <= f['top']]
            _smc_overlap_fvg(bl_fvg, br_fvg)

        # Finalize top OBs with volume % share
        def _prep_obs(obs):
            sub = obs[:oblast]
            tot_v = sum(x['vol'] for x in sub)
            out = []
            for x in sub:
                pct = int(math.floor(x['vol'] / tot_v * 100)) if tot_v > 0 else 0
                out.append({
                    'bull': x['bull'],
                    'top': x['top'],
                    'btm': x['btm'],
                    'avg': x['avg'],
                    'date': x['date'],
                    'vol': int(x['vol']),
                    'vol_pct': pct,
                    'dist_pct': round((x['avg'] - closes[-1]) / closes[-1] * 100, 2) if closes[-1] > 0 else 0
                })
            return out

        bull_obs_out = _prep_obs(blob)
        bear_obs_out = _prep_obs(brob)
        bull_fvgs_out = bl_fvg[:fvg_num]
        bear_fvgs_out = br_fvg[:fvg_num]

        # Collect structure events (solid confirmed + sweeps + active dashed)
        all_events = [e for e in (bldw[:swing_limit] + brdw[:swing_limit]) if e['style'] in ('solid', 'dotted')]
        all_events.sort(key=lambda e: e['x2'], reverse=True)
        confirmed_events = [e for e in all_events if e['style'] == 'solid']
        recent_sweeps = [e for e in all_events if e['style'] == 'dotted' and e['x2'] >= n - 10]
        last_event = all_events[0] if all_events else None

        # Chart series (last 80 bars for crisp web visualization)
        chart_bars = min(80, n)
        start_c = n - chart_bars
        chart_series = []
        for idx_c in range(start_c, n):
            chart_series.append({
                'date': dates[idx_c],
                'open': round(float(opens[idx_c]), 2),
                'high': round(float(highs[idx_c]), 2),
                'low': round(float(lows[idx_c]), 2),
                'close': round(float(closes[idx_c]), 2),
                'volume': int(vols[idx_c])
            })

        # Filter events visible in chart window
        chart_events = [
            {
                'x1_date': e['x1_date'],
                'x2_date': e['x2_date'],
                'y': e['y'],
                'txt': e['txt'],
                'dir': e['dir'],
                'style': e['style']
            }
            for e in (bldw[:30] + brdw[:30])
            if e['x2'] >= start_c
        ]

        bos_lvl = round(float(ms['bos']), 2) if ms['bos'] is not None else None
        choch_lvl = round(float(ms['choch']), 2) if ms['choch'] is not None else None
        cur_close = round(float(closes[-1]), 2)

        interpretation_md = build_smc_interpretation(
            symbol=symbol,
            close=cur_close,
            trend=ms['trend'],
            last_event=last_event,
            bos_level=bos_lvl,
            choch_level=choch_lvl,
            bull_obs=bull_obs_out,
            bear_obs=bear_obs_out,
            bull_fvgs=bull_fvgs_out,
            bear_fvgs=bear_fvgs_out,
            recent_sweeps=recent_sweeps
        )

        return {
            'trend': int(ms['trend']),
            'trend_label': 'Bullish' if ms['trend'] == 1 else ('Bearish' if ms['trend'] == -1 else 'Neutral'),
            'bos_level': bos_lvl,
            'choch_level': choch_lvl,
            'last_event': last_event,
            'recent_sweeps': recent_sweeps[:5],
            'events': all_events[:15],
            'chart_events': chart_events,
            'bull_obs': bull_obs_out,
            'bear_obs': bear_obs_out,
            'bull_fvgs': bull_fvgs_out,
            'bear_fvgs': bear_fvgs_out,
            'chart_series': chart_series,
            'interpretation_markdown': interpretation_md
        }
    except Exception as e:
        print(f"  [SMC] Error computing SMC for {symbol}: {e}")
        return None


def process_symbol(symbol, index_board=None, ma_breadth=None):
    print(f"Processing {symbol}...")
    try:
        # ── Lấy lịch sử giá — ưu tiên VCI, fallback VNDIRECT DChart ──
        df = fetch_ohlcv_direct(symbol, days=730)

        if df is None or df.empty:
            print(f"No data for {symbol}")
            return None
            
        latest = calculate_technical_indicators(df)
        # time_val = ngày phiên từ dữ liệu lịch sử (chỉ lấy phần ngày)
        candle_date = str(latest['time']).split(' ')[0] if 'time' in latest else datetime.now().strftime('%Y-%m-%d')
        # run_time = thời điểm pipeline thực sự chạy (ICT = UTC+7)
        run_time_ict = datetime.utcnow() + timedelta(hours=7)
        time_val = run_time_ict.strftime('%Y-%m-%d %H:%M') + ' (ICT)'
        
        def safe_float(val):
            return float(val) if pd.notna(val) else 0.0
            
        # Tính MA20 của Volume
        vol_20 = df['volume'].rolling(20).mean().iloc[-1]
        current_vol = safe_float(latest.get('volume', 0))
        vol_diff = ((current_vol - vol_20) / vol_20) * 100 if vol_20 > 0 else 0
        vol_status = f"cao hơn {vol_diff:.2f}%" if vol_diff > 0 else f"thấp hơn {abs(vol_diff):.2f}%"

        # Tính return và momentum để dùng trong narrative & TAS
        close_series = df['close']
        _c    = safe_float(close_series.iloc[-1])
        _c5   = safe_float(close_series.iloc[-6])  if len(close_series) >= 6  else _c
        _c20  = safe_float(close_series.iloc[-21]) if len(close_series) >= 21 else _c
        return_5d  = ((_c - _c5)  / _c5  * 100) if _c5  > 0 else 0.0
        return_20d = ((_c - _c20) / _c20 * 100) if _c20 > 0 else 0.0
        mom5       = _c - _c5  # điểm thay đổi tuyệt đối 5 phiên

        # Đánh giá Hỗ trợ / Kháng cự từ MAs
        close = safe_float(latest['close'])
        def eval_ma(c, ma_val):
            return "Hỗ trợ" if c >= ma_val else "Kháng cự"
            
        mas = [
            ("MA10",  safe_float(latest.get('ma10',  0))),
            ("MA20",  safe_float(latest.get('ma20',  0))),
            ("MA50",  safe_float(latest.get('ma50',  0))),
            ("MA100", safe_float(latest.get('ma100', 0))),
            ("MA200", safe_float(latest.get('ma200', 0))),
        ]
        mas_sorted = sorted([m for m in mas if m[1] > 0], key=lambda x: abs(close - x[1]))
        ma_str = ", ".join([f"{name} ({eval_ma(close, val)} tại {val:.2f})" for name, val in mas_sorted])

        # ROC — động lượng
        roc10 = safe_float(latest.get('roc10', 0))
        roc20 = safe_float(latest.get('roc20', 0))
        roc_str = (
            f"ROC10 = {roc10:+.2f}% (ngắn hạn), ROC20 = {roc20:+.2f}% (trung hạn)"
        )
        roc_signal = "Động lượng TÍCH CỰC" if roc10 > 0 and roc20 > 0 else (
            "Động lượng TIÊU CỰC" if roc10 < 0 and roc20 < 0 else "Động lượng PHÂN KỲ")

        # Trend assessment tổng hợp 5 MAs
        trend_assessment = build_trend_assessment(close, mas)
        
        # ── Sector mapping (dùng fallback mapping đầy đủ) ────────────
        SECTOR_MAP = _fallback_sector_mapping()

        # ── Dùng pre-fetched board từ main() theo đúng index ─────────
        top_movers_str   = ""
        market_breadth_str = ""
        sector_flow_str  = ""
        ma_breadth_str   = ""
        breadth_nums     = None   # dùng cho bộ rule nhận định
        sector_perf_list = []
        try:
            board = index_board  # đã được fetch sẵn cho đúng group
            if board is None or board.empty:
                raise ValueError("Empty board")

            group_label = symbol  # VN30 / VN100 / VNINDEX

            # Top movers — chỉ thống kê, không phân tích lý do
            top5 = board.head(5)[['listing_symbol', 'change_pc']]
            bot5 = board.tail(5)[['listing_symbol', 'change_pc']]
            top_lines = ", ".join([f"{r['listing_symbol']} ({r['change_pc']:+.2f}%)" for _, r in top5.iterrows()])
            bot_lines  = ", ".join([f"{r['listing_symbol']} ({r['change_pc']:.2f}%)"  for _, r in bot5.iterrows()])
            top_movers_str = (
                f"**Top 5 tăng mạnh nhất ({group_label}):** {top_lines}\n"
                f"**Top 5 giảm mạnh nhất ({group_label}):** {bot_lines}"
            )

            # Market Breadth (advance/decline)
            n_up   = int((board['change_pc'] > 0).sum())
            n_down = int((board['change_pc'] < 0).sum())
            n_flat = int((board['change_pc'] == 0).sum())
            total  = len(board)
            ratio  = round(n_up / max(n_down, 1), 2)
            breadth_nums = {'n_up': n_up, 'n_down': n_down, 'n_flat': n_flat, 'total': total}
            if n_up > n_down:
                breadth_signal = "Bên mua chiếm ưu thế"
            elif n_down > n_up:
                breadth_signal = "Bên bán chiếm ưu thế"
            else:
                breadth_signal = "Cân bằng"
            market_breadth_str = (
                f"**Market Breadth ({group_label} — {total} mã):** "
                f"🟢 Tăng: **{n_up}** | 🔴 Giảm: **{n_down}** | ➖ Đứng: **{n_flat}**\n"
                f"Tỷ lệ A/D: **{ratio}** — {breadth_signal}"
            )

            # MA breadth từ price_board — zero extra API calls
            if ma_breadth:
                b = ma_breadth
                pct_proxy = b.get('pct_proxy_above_mid52', 'N/A')
                ma_breadth_str = (
                    f"**Độ rộng thị trường VN30 (từ price board):**\n"
                    f"| Chỉ số | Giá trị |\n|---|---|\n"
                    f"| Mã tăng giá (> 0%) | **{b['n_up']} / {b['total']}** = {round(b['n_up']/b['total']*100,1)}% |\n"
                    f"| Mã giảm giá (< 0%) | **{b['n_down']} / {b['total']}** = {round(b['n_down']/b['total']*100,1)}% |\n"
                    f"| Mã đứng giá | **{b['n_flat']} / {b['total']}** |\n"
                    f"| Tỷ lệ Advance/Decline | **{b['ratio']}** |\n"
                    f"| % mã trên trung điểm 52 tuần (proxy MA200) | **{pct_proxy}%** |"
                )

            # Sector money flow (dùng SECTOR_MAP — chủ yếu chính xác với VN30)
            board['sector'] = board['listing_symbol'].map(SECTOR_MAP).fillna('Khác')
            sector_perf = board.groupby('sector')['change_pc'].mean().sort_values(ascending=False)
            sector_perf_list = [(str(k), float(v)) for k, v in sector_perf.items()]
            attract = sector_perf[sector_perf > 0]
            drain   = sector_perf[sector_perf < 0]
            attract_lines = ", ".join([f"{s} (+{v:.2f}%)" for s, v in attract.items()]) if not attract.empty else "Không có"
            drain_lines   = ", ".join([f"{s} ({v:.2f}%)"  for s, v in drain.items()])   if not drain.empty  else "Không có"
            sector_flow_str = (
                f"**Nhóm ngành thu hút dòng tiền:** {attract_lines}\n"
                f"**Nhóm ngành bị rút dòng tiền:** {drain_lines}"
            )
            print(f"  [{symbol}] Breadth: +{n_up}/-{n_down}/={n_flat} (total {total})")
        except Exception as e:
            top_movers_str = f"Dữ liệu {symbol} board không khả dụng."
            print(f"Error using {symbol} price board: {e}")


        # ── TÍNH TOÁN CÁC BIẾN CHO KỊCH BẢN THỊ TRƯỜNG ──
        sr_zones_res = find_sr_zones(df, close)
        support_zone = next((z for z in sr_zones_res if z['type'] == 'support'), None)
        resistance_zone = next((z for z in sr_zones_res if z['type'] == 'resistance'), None)
        support_price = support_zone['level'] if support_zone else 0
        resistance_price = resistance_zone['level'] if resistance_zone else 0
        support_distance = support_zone['dist_pct'] if support_zone else 0
        resistance_distance = resistance_zone['dist_pct'] if resistance_zone else 0

        sub_20 = df.tail(20)
        highest_20 = float(sub_20['high'].max()) if not sub_20.empty else close
        lowest_20 = float(sub_20['low'].min()) if not sub_20.empty else close
        volatility_value = round((highest_20 - lowest_20) / close * 100, 2) if close > 0 else 0

        tas_res = compute_tas(close, latest, vol_diff, mas)
        tas_score = tas_res['score']
        tas_status = tas_res['label']

        # ── NHẬN ĐỊNH THEO BỘ RULE (data_pipeline/market_rules.py) ──
        smc_res = compute_bigbeluga_smc(df, symbol)
        prev_close = safe_float(latest.get('prev_close', 0)) or close
        obv_series = df['obv'] if 'obv' in df.columns else None
        obv_change_10 = (safe_float(obv_series.iloc[-1]) - safe_float(obv_series.iloc[-11])
                         if obv_series is not None and len(obv_series) > 11 else None)
        snap = {
            'symbol': symbol, 'close': close, 'prev_close': prev_close,
            'change_pc': (close - prev_close) / prev_close * 100 if prev_close > 0 else 0.0,
            'high': safe_float(latest['high']), 'low': safe_float(latest['low']),
            'volume': current_vol, 'vol_diff': vol_diff,
            'ma': dict(mas),
            'roc10': roc10, 'roc20': roc20,
            'rsi14': safe_float(latest.get('rsi14', 0)),
            'adx': safe_float(latest.get('adx', 0)),
            'atr': safe_float(latest.get('atr', 0)),
            'keltner_h': safe_float(latest.get('keltner_h', 0)),
            'keltner_l': safe_float(latest.get('keltner_l', 0)),
            'cmf': safe_float(latest.get('cmf', 0)),
            'vwap': safe_float(latest.get('vwap', 0)),
            'obv': safe_float(latest.get('obv', 0)),
            'obv_change_10': obv_change_10,
            'tas_score': int(tas_score), 'tas_label': tas_status,
            'smc': smc_res, 'breadth': breadth_nums, 'sector_perf': sector_perf_list,
            'sr_zones': sr_zones_res,
        }
        commentary = market_rules.build_commentary(
            snap,
            market_stats_md=top_movers_str if breadth_nums else "",
            breadth_md="\n\n".join(filter(None, [market_breadth_str, ma_breadth_str])),
            volatility_value=volatility_value,
        )
        general_markdown  = commentary['general_markdown']
        scenario_markdown = commentary['scenario_markdown']
        volume_markdown   = commentary['volume_markdown']
        trend_markdown    = commentary['trend_markdown']
        if smc_res and smc_res.get('interpretation_markdown'):
            smc_res['interpretation_markdown'] = market_rules.replace_smc_strategy(
                smc_res['interpretation_markdown'], snap, commentary['_v'])
        print(f"  [{symbol}] Nhận định: {commentary['verdict']['regime']} → {commentary['verdict']['action']} "
              f"(rule {commentary['verdict']['rule_no']}, tin cậy {commentary['verdict']['confidence']})")

        # Delay giữa các symbol để tránh rate limit nguồn dữ liệu
        time.sleep(5)

        return {
            "symbol": symbol,
            "date": str(time_val),
            "close": close,
            "change": close - safe_float(latest['prev_close']),
            "change_pc": ((close - safe_float(latest['prev_close'])) / safe_float(latest['prev_close']) * 100) if safe_float(latest['prev_close']) > 0 else 0,
            "volume": current_vol,
            "technical": {
                "ma20": safe_float(latest.get('ma20', 0)),
                "pivot": safe_float(latest.get('pivot', 0)),
                "cmf": safe_float(latest.get('cmf', 0)),
                "adx": safe_float(latest.get('adx', 0))
            },
            "general_markdown": general_markdown,
            "scenario_markdown": scenario_markdown,
            "volume_markdown": volume_markdown,
            "trend_markdown": trend_markdown,
            "commentary": commentary['verdict'],
            "tas": {
                **tas_res,
                "history": compute_tas_history_fast(df)
            },
            "candle_patterns": detect_candle_patterns(df),
            "sr_zones":        sr_zones_res,
            "smc":             smc_res,
        }

        
    except Exception as e:
        print(f"Error processing {symbol}: {e}")
        traceback.print_exc()
        return None

def fetch_historical_vndirect(sym, start_ts, end_ts):
    import urllib.request
    import json
    url = f'https://dchart-api.vndirect.com.vn/dchart/history?resolution=D&symbol={sym}&from={start_ts}&to={end_ts}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read())
        return sym, data
    except Exception as e:
        return sym, None

def enrich_raw_stocks_with_breadth(raw_stocks):
    import time, concurrent.futures, datetime
    import pandas as pd
    from collections import defaultdict
    
    end_ts = int(time.time())
    start_ts = end_ts - 365*24*3600
    symbols = list(raw_stocks.keys())
    
    print(f"[BREADTH] Fetching 1Y history for {len(symbols)} stocks via VNDIRECT API...")
    
    # Per-date advance/decline tracking for A/D line
    date_advance = defaultdict(int)
    date_decline = defaultdict(int)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(fetch_historical_vndirect, sym, start_ts, end_ts): sym for sym in symbols}
        for future in concurrent.futures.as_completed(futures):
            sym = futures[future]
            try:
                _, data = future.result()
                if not data or 'c' not in data or len(data['c']) == 0:
                    continue
                
                closes = pd.Series(data['c'], dtype=float)
                highs = pd.Series(data['h'], dtype=float)
                lows = pd.Series(data['l'], dtype=float)
                volumes = pd.Series(data.get('v', []), dtype=float)
                timestamps = data.get('t', [])
                
                if len(closes) < 10:
                    continue
                    
                cur_close = float(closes.iloc[-1])
                
                # SMA
                sma20 = float(closes.rolling(window=20).mean().iloc[-1]) if len(closes) >= 20 else cur_close
                sma50 = float(closes.rolling(window=50).mean().iloc[-1]) if len(closes) >= 50 else cur_close
                sma200 = float(closes.rolling(window=200).mean().iloc[-1]) if len(closes) >= 200 else cur_close
                
                # 52W High/Low (1 year roughly 250 trading days)
                high_52w = float(highs.max())
                low_52w = float(lows.min())
                
                # Flags
                is_new_high_52w = bool(cur_close >= high_52w * 0.99)
                is_new_low_52w = bool(cur_close <= low_52w * 1.01)
                
                is_above_sma50 = bool(cur_close > sma50)
                is_above_sma200 = bool(cur_close > sma200)
                is_uptrend = bool(cur_close > sma50 and sma50 > sma200)
                is_strong = bool(cur_close > sma20 and sma20 > sma50 and sma50 > sma200)
                
                # Cập nhật vào raw_stocks
                raw_stocks[sym]['is_above_sma50'] = is_above_sma50
                raw_stocks[sym]['is_above_sma200'] = is_above_sma200
                raw_stocks[sym]['is_uptrend'] = is_uptrend
                raw_stocks[sym]['is_strong'] = is_strong
                raw_stocks[sym]['is_new_high_52w'] = is_new_high_52w
                raw_stocks[sym]['is_new_low_52w'] = is_new_low_52w
                
                # ── Accurate Swing Trading System (Pine Script port) ──
                # no = 5
                # res = highest(high, no), sup = lowest(low, no)
                # avd = iff(close > res[1], 1, iff(close < sup[1], -1, 0))
                # avn = valuewhen(avd != 0, avd, 0)
                # tsl = iff(avn == 1, sup, res)
                # Buy = crossover(close, tsl) AND volume > volume_sma5
                # Sell = crossunder(close, tsl) AND volume > volume_sma5
                swing_period = 5
                if len(closes) >= swing_period + 2:
                    h_s = highs.values
                    l_s = lows.values
                    c_s = closes.values
                    n_b = len(c_s)
                    
                    roll_res = highs.rolling(window=swing_period).max().values
                    roll_sup = lows.rolling(window=swing_period).min().values
                    
                    # Điều kiện Volume: Khối lượng phiên hôm nay > Khối lượng trung bình 5 phiên gần nhất
                    vol_breakout = True
                    if len(volumes) >= 5:
                        vol_sma5 = float(volumes.rolling(window=5).mean().iloc[-1])
                        cur_vol = float(volumes.iloc[-1])
                        if vol_sma5 > 0:
                            vol_breakout = bool(cur_vol > vol_sma5)
                    
                    avn_state = 0
                    tsl_val = c_s[0]
                    buy_today = False
                    sell_today = False
                    
                    for idx in range(swing_period, n_b):
                        res_p = roll_res[idx - 1]
                        sup_p = roll_sup[idx - 1]
                        c_val = c_s[idx]
                        
                        if c_val > res_p:
                            avd = 1
                        elif c_val < sup_p:
                            avd = -1
                        else:
                            avd = 0
                            
                        prev_avn = avn_state
                        if avd != 0:
                            avn_state = avd
                            
                        if avn_state == 1:
                            cur_tsl = roll_sup[idx]
                        else:
                            cur_tsl = roll_res[idx]
                            
                        if idx == n_b - 1:
                            tsl_val = cur_tsl
                            prev_c = c_s[idx - 1]
                            prev_tsl = roll_sup[idx - 1] if prev_avn == 1 else roll_res[idx - 1]
                            
                            # Tín hiệu Mua/Bán chỉ chấp nhận khi khối lượng vượt TB 5 phiên
                            if c_val > cur_tsl and prev_c <= prev_tsl and vol_breakout:
                                buy_today = True
                            elif c_val < cur_tsl and prev_c >= prev_tsl and vol_breakout:
                                sell_today = True
                                
                    cur_vol = float(volumes.iloc[-1]) if len(volumes) > 0 else 0
                    vol_sma5 = float(volumes.rolling(window=5).mean().iloc[-1]) if len(volumes) >= 5 else cur_vol
                    vol_sma20 = float(volumes.rolling(window=20).mean().iloc[-1]) if len(volumes) >= 20 else cur_vol
                    vol_ratio_20 = round(cur_vol / vol_sma20, 2) if vol_sma20 > 0 else 1.0

                    raw_stocks[sym]['volume'] = int(cur_vol)
                    raw_stocks[sym]['vol_sma5'] = int(vol_sma5)
                    raw_stocks[sym]['vol_sma20'] = int(vol_sma20)
                    raw_stocks[sym]['vol_ratio_20'] = vol_ratio_20
                    raw_stocks[sym]['is_vol_breakout_5'] = bool(cur_vol > vol_sma5) if vol_sma5 > 0 else False
                    raw_stocks[sym]['is_vol_breakout_20'] = bool(vol_ratio_20 >= 1.5)
                    
                    raw_stocks[sym]['swing_buy'] = bool(buy_today)
                    raw_stocks[sym]['swing_sell'] = bool(sell_today)
                    raw_stocks[sym]['swing_trend'] = 'BUY' if avn_state == 1 else 'SELL'
                    raw_stocks[sym]['swing_tsl'] = round(float(tsl_val), 1)
                
                # Tính A/D daily từ daily returns
                if len(timestamps) == len(closes) and len(closes) >= 2:
                    daily_ret = closes.diff()
                    # Chỉ lấy 55 phiên gần nhất để tính A/D line
                    recent_ret = daily_ret.iloc[-55:]
                    recent_ts  = timestamps[-55:]
                    for ts, ret in zip(recent_ts, recent_ret):
                        if pd.isna(ret):
                            continue
                        date_str = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime('%Y-%m-%d')
                        if ret > 0:
                            date_advance[date_str] += 1
                        elif ret < 0:
                            date_decline[date_str] += 1
                
            except Exception as e:
                pass

    print("[BREADTH] Historical data fetch & compute completed.")
    
    # Build A/D line: sorted dates, cumulative (advance - decline)
    all_dates = sorted(set(date_advance.keys()) | set(date_decline.keys()))
    all_dates = all_dates[-50:]  # Lấy 50 phiên gần nhất
    
    ad_history = []
    cumulative = 0
    for d in all_dates:
        net = date_advance.get(d, 0) - date_decline.get(d, 0)
        cumulative += net
        ad_history.append({
            'date': d,
            'advance': date_advance.get(d, 0),
            'decline': date_decline.get(d, 0),
            'net': net,
            'cumulative': cumulative
        })
    
    # Build Swing trading signals summary
    buy_signals = []
    sell_signals = []
    uptrend_signals = []
    
    for sym, info in raw_stocks.items():
        item = {
            'ticker': sym,
            'price': info.get('match_price') or info.get('close') or 0,
            'tsl': info.get('swing_tsl', 0),
            'change_pc': round(info.get('change_pc', 0), 2),
            'sector': info.get('sector', 'Khác'),
            'is_strong': info.get('is_strong', False),
            'is_uptrend': info.get('is_uptrend', False)
        }
        if info.get('swing_buy'):
            buy_signals.append(item)
        elif info.get('swing_sell'):
            sell_signals.append(item)
        elif info.get('swing_trend') == 'BUY':
            uptrend_signals.append(item)
            
    buy_signals.sort(key=lambda x: x['change_pc'], reverse=True)
    sell_signals.sort(key=lambda x: x['change_pc'])
    
    swing_signals = {
        'buy_today': buy_signals,
        'sell_today': sell_signals,
        'uptrend_count': len(uptrend_signals) + len(buy_signals),
        'downtrend_count': len(raw_stocks) - (len(uptrend_signals) + len(buy_signals)),
        'total': len(raw_stocks)
    }
    
    print(f"[SWING] Signals today: {len(buy_signals)} BUY | {len(sell_signals)} SELL | {swing_signals['uptrend_count']}/{len(raw_stocks)} in Uptrend")
    print(f"[BREADTH] A/D Line: {len(ad_history)} phiên computed")
    return raw_stocks, ad_history, swing_signals

def main():
    symbols = ["VNINDEX", "VN30", "VN100", "HNXINDEX"]
    all_data = {}

    # ── Pre-fetch price boards cho từng index (3 calls, không lặp) ───
    # Mapping: symbol -> group name dùng trong symbols_by_group
    GROUP_MAP = {
        "VNINDEX":  "VN100",   # dùng VN100 làm proxy (100 mã đại diện tốt)
        "VN30":     "VN30",
        "VN100":    "VN100",
        "HNXINDEX": None,      # HNX — không cần price_board HOSE
    }
    # VN30/VN100 fallback (nếu API không lấy được group syms)
    VN30_FALLBACK = [
        'ACB','BCM','BID','BVH','CTG','FPT','GAS','GVR','HDB','HPG',
        'MBB','MSN','MWG','NVL','PDR','PLX','POW','SAB','SHB','SSB',
        'SSI','STB','TCB','TPB','VCB','VHM','VIB','VIC','VJC','VNM',
    ]
    VN100_FALLBACK = VN30_FALLBACK + [
        'AAA','AGG','AGR','ANV','BAF','BCG','BSI','BWE','C4G','CAV',
        'CII','CMG','CRE','CSV','CTD','DBC','DCM','DGC','DGW','DHC',
        'DIG','DPM','DQC','DRC','DXG','EIB','EVF','FCN','FRT','GEX',
        'GMD','GTC','HAH','HCM','HDC','HDG','HSG','HT1','IMP','IPA',
        'KBC','KDC','KDH','KHG','KOS','LCG','LPB','LTG','MCH','MIG',
        'MSB','NAB','NAV','NKG','NT2','NTL','OCB','OGC','PAN','PC1',
        'PNJ','PSH','PVD','PVT','QNS','REE','SBT','SCS','SJS','SKG',
        'SRC','SZC','TCH','TDH','TDM','TIP','TLG','TMP','TNH','VCI',
    ]
    
    def fetch_hose_stocks_fallback():
        """Lấy danh sách mã chứng khoán HOSE dự phòng."""
        import json
        import os
        hardcoded = []
        try:
            _script_dir = os.path.dirname(os.path.abspath(__file__))
            _parent_dir = os.path.dirname(_script_dir)
            _paths = [
                os.path.join(_script_dir, 'custom_sectors.json'),
                os.path.join(_parent_dir, 'custom_sectors.json'),
                'custom_sectors.json'
            ]
            for p in _paths:
                if os.path.exists(p):
                    with open(p, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        for sector, syms in data.items():
                            hardcoded.extend(syms)
                    break
            hardcoded = list(set(hardcoded + VN100_FALLBACK))
            print(f"  [BOARDS] Fallback to custom_sectors + VN100: {len(hardcoded)} mã")
            return hardcoded
        except Exception as e:
            print(f"  [BOARDS] Fallback failed: {e}")
            return VN100_FALLBACK

    price_boards = {}
    print("[BOARDS] Pre-fetching index price boards...")
    sys.stdout.flush()

    def _normalize_board(raw):
        """Chuẩn hoá columns price_board."""
        if hasattr(raw.columns, 'levels'):
            raw.columns = ['_'.join(str(x) for x in col if str(x))
                           for col in raw.columns.values]
        raw.columns = [str(c).strip() for c in raw.columns]
        cp = 'match_match_price' if 'match_match_price' in raw.columns else next((c for c in raw.columns if c in ('close', 'price') or ('match_price' in c and 'ato' not in c and 'atc' not in c)), None)
        rp = 'listing_ref_price' if 'listing_ref_price' in raw.columns else next((c for c in raw.columns if c in ('ref', 'ref_price') or 'ref_price' in c), None)
        if cp and rp:
            # Nếu cổ phiếu chưa có giao dịch, VCI trả về match_price = 0
            # Cần gán lại bằng giá tham chiếu để thay đổi = 0%, tránh bị lỗi -100%
            raw[cp] = raw.apply(lambda row: row[rp] if pd.isna(row[cp]) or row[cp] == 0 else row[cp], axis=1)
            
            raw['change_pc'] = (raw[cp] - raw[rp]) / raw[rp].replace(0, float('nan')) * 100
            if 'match_match_price' not in raw.columns:
                raw['match_match_price'] = raw[cp]
            if 'listing_ref_price' not in raw.columns:
                raw['listing_ref_price'] = raw[rp]
        else:
            raw['change_pc'] = 0.0
        
        # Lấp đầy các giá trị NaN để không bị drop
        raw['change_pc'] = raw['change_pc'].fillna(0.0)
        tc = next((c for c in raw.columns
                   if 'code' in c.lower() or c in ('ticker', 'symbol')), None)
        if tc and 'listing_code' not in raw.columns:
            raw['listing_code'] = raw[tc]
        # Ensure listing_symbol exists
        if 'listing_symbol' not in raw.columns:
            if 'listing_code' in raw.columns:
                raw['listing_symbol'] = raw['listing_code']
        return raw

    if _HAS_VNSTOCK:
        # ─── Path A: vnstock available → use VCI Trading ───
        try:
            _listing  = VCIListing(show_log=False)
            _trading  = VCITrading(show_log=False)

            def _get_group_syms(group, fallback):
                try:
                    df_all = _listing.all_symbols()
                    grp_col = next(
                        (c for c in df_all.columns
                         if 'group' in c.lower() or 'index' in c.lower() or 'type' in c.lower()),
                        None
                    )
                    if grp_col:
                        filtered = df_all[df_all[grp_col].str.contains(group, case=False, na=False)]
                        ticker_col = next(
                            (c for c in filtered.columns
                             if 'ticker' in c.lower() or 'symbol' in c.lower() or 'code' in c.lower()),
                            filtered.columns[0]
                        )
                        syms = filtered[ticker_col].tolist()
                        if syms:
                            return syms
                except Exception as e:
                    err_str = str(e)
                    if 'hosting_service' not in err_str and 'Expecting value' not in err_str:
                        print(f"  [BOARDS] all_symbols filter failed: {err_str}")
                return fallback

            # Fetch VN30
            vn30_syms = _get_group_syms('VN30', VN30_FALLBACK)
            print(f"[BOARDS] VN30={len(vn30_syms)} mã")
            sys.stdout.flush()
            raw_vn30 = _trading.price_board(symbols_list=vn30_syms)
            price_boards['VN30'] = _normalize_board(raw_vn30).sort_values('change_pc', ascending=False)
            time.sleep(2)

            # Fetch VN100
            vn100_syms = _get_group_syms('VN100', VN100_FALLBACK)
            print(f"[BOARDS] VN100={len(vn100_syms)} mã")
            sys.stdout.flush()
            raw_vn100 = _trading.price_board(symbols_list=vn100_syms)
            price_boards['VN100'] = _normalize_board(raw_vn100).sort_values('change_pc', ascending=False)

            # Fetch VNINDEX (HOSE)
            vnindex_syms = []
            try:
                df_all = _listing.symbols_by_exchange()
                hose_stocks = df_all[
                    (df_all['exchange'].str.upper() == 'HOSE') &
                    (df_all['type'].str.upper() == 'STOCK')
                ]['symbol'].tolist()
                if hose_stocks:
                    vnindex_syms = hose_stocks
                    print(f"[BOARDS] HOSE stocks (excl CW/ETF): {len(vnindex_syms)} mã")
            except Exception as e:
                print(f"  [BOARDS] symbols_by_exchange for VNINDEX failed: {e}")
            
            if not vnindex_syms:
                vnindex_syms = fetch_hose_stocks_fallback()
            print(f"[BOARDS] VNINDEX={len(vnindex_syms)} mã")
            sys.stdout.flush()
            
            vnindex_dfs = []
            failed_syms = []
            chunks_50 = [vnindex_syms[i:i+50] for i in range(0, len(vnindex_syms), 50)]
            for chunk in chunks_50:
                try:
                    raw_chunk = _trading.price_board(symbols_list=chunk)
                    if not raw_chunk.empty:
                        vnindex_dfs.append(raw_chunk)
                    time.sleep(1)
                    continue
                except Exception as e:
                    print(f"  [BOARDS] Chunk 50 failed: {e}. Splitting to 10...")
                    chunks_10 = [chunk[i:i+10] for i in range(0, len(chunk), 10)]
                    for sub in chunks_10:
                        try:
                            raw_sub = _trading.price_board(symbols_list=sub)
                            if not raw_sub.empty:
                                vnindex_dfs.append(raw_sub)
                            time.sleep(0.5)
                            continue
                        except Exception as e2:
                            for sym in sub:
                                try:
                                    raw_ind = _trading.price_board(symbols_list=[sym])
                                    if not raw_ind.empty:
                                        vnindex_dfs.append(raw_ind)
                                    time.sleep(0.2)
                                except:
                                    failed_syms.append(sym)
                                    
            if failed_syms:
                print(f"  [BOARDS] Completely failed {len(failed_syms)} symbols: {failed_syms[:10]}...")
                
            if vnindex_dfs:
                raw_vnindex = pd.concat(vnindex_dfs, ignore_index=True)
                raw_vnindex = raw_vnindex.loc[raw_vnindex.astype(str).drop_duplicates().index]
                price_boards['VNINDEX'] = _normalize_board(raw_vnindex).sort_values('change_pc', ascending=False)
            else:
                if 'VN100' in price_boards:
                    price_boards['VNINDEX'] = price_boards['VN100'].copy()

            print(f"[BOARDS] Done (VCI): VN30={len(price_boards.get('VN30',[]))} | VN100={len(price_boards.get('VN100',[]))} | VNINDEX={len(price_boards.get('VNINDEX',[]))}")
            sys.stdout.flush()

        except Exception as e:
            print(f"[BOARDS] VCI failed: {e}")
            traceback.print_exc()
            sys.stdout.flush()
    
    # ─── Path B: No vnstock OR VCI failed → use VNDIRECT DChart API ───
    if not price_boards:
        print("[BOARDS] Using VNDIRECT DChart API (no vnstock)...")
        sys.stdout.flush()
        try:
            # VN30
            print(f"[BOARDS] VN30={len(VN30_FALLBACK)} mã (fallback)")
            raw_vn30 = fetch_price_board_direct(VN30_FALLBACK)
            if not raw_vn30.empty:
                price_boards['VN30'] = raw_vn30.sort_values('change_pc', ascending=False)

            # VN100
            print(f"[BOARDS] VN100={len(VN100_FALLBACK)} mã (fallback)")
            raw_vn100 = fetch_price_board_direct(VN100_FALLBACK)
            if not raw_vn100.empty:
                price_boards['VN100'] = raw_vn100.sort_values('change_pc', ascending=False)

            # VNINDEX (HOSE) — Wifeed or fallback
            vnindex_syms = fetch_hose_symbols_direct() or fetch_hose_stocks_fallback()
            print(f"[BOARDS] VNINDEX={len(vnindex_syms)} mã")
            sys.stdout.flush()
            raw_vnindex = fetch_price_board_direct(vnindex_syms)
            if not raw_vnindex.empty:
                price_boards['VNINDEX'] = raw_vnindex.sort_values('change_pc', ascending=False)
            elif 'VN100' in price_boards:
                price_boards['VNINDEX'] = price_boards['VN100'].copy()

            print(f"[BOARDS] Done (VNDIRECT): VN30={len(price_boards.get('VN30',[]))} | VN100={len(price_boards.get('VN100',[]))} | VNINDEX={len(price_boards.get('VNINDEX',[]))}")
            sys.stdout.flush()
        except Exception as e:
            print(f"[BOARDS] VNDIRECT fallback failed: {e}")
            traceback.print_exc()
            sys.stdout.flush()


    # ── Compute breadth từ VN30 board — ZERO extra API calls ─────────
    ma_breadth = None
    if 'VN30' in price_boards and not price_boards['VN30'].empty:
        ma_breadth = compute_breadth_from_board(price_boards['VN30'])
        if ma_breadth:
            print(f"[BREADTH] A/D={ma_breadth['n_up']}/{ma_breadth['n_down']} | proxy-MA200={ma_breadth['pct_proxy_above_mid52']}%")

    for sym in symbols:
        board = price_boards.get(sym)  # đúng board cho từng index
        data  = process_symbol(sym, index_board=board, ma_breadth=ma_breadth)
        if data:
            all_data[sym] = data

    if not all_data:
        print("No data collected!")
        sys.exit(1)

    out_dir = "output"
    os.makedirs(out_dir, exist_ok=True)

    # Sector heatmap từ VNINDEX board + ICB mapping — đầy đủ toàn sàn HOSE
    sector_heatmap = []
    raw_stocks = {}
    icb_mapping = get_sector_mapping()
    board_for_sector = price_boards.get('VNINDEX', price_boards.get('VN100'))
    if board_for_sector is not None and not board_for_sector.empty:
        sector_heatmap, raw_stocks = compute_sector_heatmap(board_for_sector, icb_mapping)
        print(f"[SECTOR] {len(sector_heatmap)} ngành computed from {len(board_for_sector)} stocks")
        raw_stocks, ad_history, swing_signals = enrich_raw_stocks_with_breadth(raw_stocks)
    else:
        ad_history = []
        swing_signals = {'buy_today': [], 'sell_today': [], 'uptrend_count': 0, 'downtrend_count': 0, 'total': 0}

    # Gắn sector_heatmap và swing_signals vào tất cả index
    for sym in all_data:
        all_data[sym]['sector_heatmap'] = sector_heatmap
        all_data[sym]['swing_signals']  = swing_signals
        
    all_data['__global__'] = {
        'raw_stocks': raw_stocks,
        'ad_history': ad_history,
        'swing_signals': swing_signals
    }
    
    def clean_nan(obj):
        if isinstance(obj, dict):
            return {k: clean_nan(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [clean_nan(v) for v in obj]
        elif isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return None
            return obj
        return obj
        
    all_data = clean_nan(all_data)

    with open(f"{out_dir}/data.json", "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2, cls=_SafeEncoder)
    print(f"Successfully generated {out_dir}/data.json")

if __name__ == "__main__":
    main()
