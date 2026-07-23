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
# vnstock v4 - dùng explorer.vci trực tiếp (API stable)
import logging
warnings.filterwarnings('ignore')
logging.disable(logging.CRITICAL)
from vnstock.explorer.vci import Quote as VCIQuote
from vnstock.explorer.vci import Listing as VCIListing
from vnstock.explorer.vci import Trading as VCITrading
from openai import OpenAI


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


def generate_rule_based_analysis(symbol, close, open_price, high, low, current_vol,
                                  vol_status, vol_diff, ma_str, mas_sorted,
                                  cmf, vwap, obv, adx, atr, keltner_h, keltner_l,
                                  top_movers_str, time_val, tab_type):
    """Tự sinh bài phân tích từ dữ liệu số khi AI không khả dụng."""
    change = close - open_price
    change_pc = (change / open_price * 100) if open_price > 0 else 0
    direction = "tăng" if change >= 0 else "giảm"
    direction_emoji = "🟢" if change >= 0 else "🔴"
    
    # Đánh giá vị trí MAs
    support_levels = [(name, val) for name, val in mas_sorted if close >= val]
    resist_levels = [(name, val) for name, val in mas_sorted if close < val]
    
    support_str = ", ".join([f"{n} ({v:.2f})" for n, v in support_levels]) if support_levels else "không có"
    resist_str = ", ".join([f"{n} ({v:.2f})" for n, v in resist_levels]) if resist_levels else "không có"
    
    if tab_type == "general":
        top_info = top_movers_str

        return f"""### 1. Diễn biến phiên giao dịch

{direction_emoji} **{symbol}** đóng cửa tại **{close:.2f}** điểm, **{direction} {abs(change):.2f} điểm ({abs(change_pc):.2f}%)** so với tham chiếu {open_price:.2f}.

Khối lượng giao dịch: **{current_vol:,.0f} CP** — {vol_status} so với trung bình 20 phiên.

**Vùng Hỗ trợ (từ gần đến xa):** {support_str}
**Vùng Kháng cự (từ gần đến xa):** {resist_str}

### 2. Thống kê Cổ phiếu & Nhóm ngành

{top_info}

---
*⚠️ Phân tích tự động từ dữ liệu kỹ thuật — AI đang được bảo trì.*"""

    elif tab_type == "volume":
        cmf_signal = "Tích cực (dòng tiền vào)" if cmf > 0.05 else ("Trung tính" if cmf > -0.05 else "Tiêu cực (dòng tiền rút ra)")
        vwap_signal = "Giá > VWAP → Xu hướng tích cực trong ngày" if close > vwap else "Giá < VWAP → Áp lực bán chiếm ưu thế"
        
        return f"""### 1. Thống kê Chỉ báo Khối lượng

| Chỉ báo | Giá trị | Nhận định |
|---|---|---|
| **CMF** | `{cmf:.4f}` | {cmf_signal} |
| **VWAP** | `{vwap:.2f}` | {vwap_signal} |
| **OBV** | `{obv:,.0f}` | {"Tích lũy — dòng tiền ròng vào" if obv > 0 else "Phân phối — dòng tiền ròng ra"} |
| **KL Hiện tại** | `{current_vol:,.0f} CP` | {vol_status} so với TB 20 phiên |

### 2. Nhận định Dòng tiền chung

{"🟢 **Dòng tiền ĐANG VÀO**" if cmf > 0 else "🔴 **Dòng tiền ĐANG RÚT RA**"} — CMF = `{cmf:.4f}` cho thấy {"áp lực mua" if cmf > 0 else "áp lực bán"} đang chiếm ưu thế.

{"Giá giao dịch trên VWAP (" + f"{vwap:.2f}" + "), tín hiệu tích cực cho xu hướng nội phiên." if close > vwap else "Giá dưới VWAP (" + f"{vwap:.2f}" + "), bên bán đang kiểm soát phiên giao dịch."}

{"Khối lượng " + vol_status + " cho thấy " + ("sự tham gia mạnh, có thể từ tổ chức." if abs(vol_diff) > 20 else "giao dịch bình thường, chủ yếu nhà đầu tư cá nhân.")}

---
*⚠️ Phân tích tự động từ dữ liệu kỹ thuật — AI đang được bảo trì.*"""

    elif tab_type == "trend":
        adx_signal = "Xu hướng MẠNH" if adx > 25 else ("Xu hướng TRUNG BÌNH" if adx > 15 else "Thị trường ĐI NGANG — không có xu hướng rõ")
        keltner_pos = "Giá > Keltner Upper → QUÁ MUA" if close > keltner_h else ("Giá < Keltner Lower → QUÁ BÁN" if close < keltner_l else "Giá trong kênh Keltner → Bình thường")
        
        return f"""### 1. Thống kê Xu hướng & Biến động

| Chỉ báo | Giá trị | Nhận định |
|---|---|---|
| **ADX** | `{adx:.2f}` | {adx_signal} |
| **ATR** | `{atr:.2f}` | Biến động trung bình {atr:.2f} điểm/phiên |
| **Keltner Upper** | `{keltner_h:.2f}` | {"⚠️ Giá đang vượt trên" if close > keltner_h else "Kháng cự trên"} |
| **Keltner Lower** | `{keltner_l:.2f}` | {"⚠️ Giá đang thủng dưới" if close < keltner_l else "Hỗ trợ dưới"} |

### 2. Nhận định Rủi ro & Hành động

**Xu hướng hiện tại:** {direction_emoji} {"Tăng" if change >= 0 else "Giảm"} — ADX = `{adx:.2f}` ({adx_signal}).

**Vị trí giá so với Keltner:** {keltner_pos}

**Mức biến động:** ATR = `{atr:.2f}` điểm — {"Biến động cao, cần cẩn thận với đòn bẩy." if atr > 30 else "Biến động bình thường, rủi ro được kiểm soát."}

**Khuyến nghị:** {"🟢 Tín hiệu giữ vị thế mua nếu ADX > 25 và giá trên " + (support_levels[0][0] if support_levels else "MA gần nhất") + "." if change >= 0 and adx > 20 else "🔴 Thận trọng, chờ tín hiệu xác nhận đảo chiều trước khi hành động."}

---
*⚠️ Phân tích tự động từ dữ liệu kỹ thuật — AI đang được bảo trì.*"""

    return "Không có dữ liệu phân tích."


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
                mapping = {}
                for sector, tickers in custom_map.items():
                    for t in tickers:
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

    result.sort(key=lambda x: x['avg_change'], reverse=True)
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


def process_symbol(symbol, index_board=None, ma_breadth=None):
    print(f"Processing {symbol}...")
    try:
        start_date = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
        end_date = datetime.now().strftime("%Y-%m-%d")
        # ── Lấy lịch sử giá bằng vnstock.explorer.vci (source code đã xác nhận) ──
        q = VCIQuote(symbol=symbol, show_log=False)
        df = q.history(start=start_date, end=end_date, interval='1D')

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
        try:
            board = index_board  # đã được fetch sẵn cho đúng group
            if board is None or board.empty:
                raise ValueError("Empty board")

            group_label = symbol  # VN30 / VN100 / VNINDEX

            # Top movers — chỉ thống kê, không phân tích lý do
            top5 = board.head(5)[['listing_symbol', 'change_pc']]
            bot5 = board.tail(5)[['listing_symbol', 'change_pc']]
            top_lines = ", ".join([f"{r['listing_symbol']} (+{r['change_pc']:.2f}%)" for _, r in top5.iterrows()])
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

        combined_market_str = "\n\n".join(filter(None, [top_movers_str, market_breadth_str, ma_breadth_str, sector_flow_str]))

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
        volatility_regime = "ELEVATED_VOL" if volatility_value > 10 else "LOW_VOL"

        tas_res = compute_tas(close, latest, vol_diff, mas)
        tas_score = tas_res['score']
        tas_status = tas_res['label']

        rb_args = dict(
            symbol=symbol, close=close, open_price=safe_float(latest['open']),
            high=safe_float(latest['high']), low=safe_float(latest['low']),
            current_vol=current_vol, vol_status=vol_status, vol_diff=vol_diff,
            ma_str=ma_str, mas_sorted=mas_sorted,
            cmf=safe_float(latest.get('cmf', 0)),
            vwap=safe_float(latest.get('vwap', 0)),
            obv=safe_float(latest.get('obv', 0)),
            adx=safe_float(latest.get('adx', 0)),
            atr=safe_float(latest.get('atr', 0)),
            keltner_h=safe_float(latest.get('keltner_h', 0)),
            keltner_l=safe_float(latest.get('keltner_l', 0)),
            top_movers_str=combined_market_str, time_val=time_val
        )

        # ── Phân tích MA divergence — cần thiết cho TAB:TREND ──────────
        short_mas  = [(n, v) for n, v in mas if n in ('MA10', 'MA20') and v > 0]
        mid_mas    = [(n, v) for n, v in mas if n == 'MA50' and v > 0]
        long_mas   = [(n, v) for n, v in mas if n in ('MA100', 'MA200') and v > 0]

        def _dir(pairs):
            if not pairs: return None
            above = all(close >= v for _, v in pairs)
            below = all(close < v for _, v in pairs)
            return 'up' if above else ('down' if below else 'mixed')

        d_short = _dir(short_mas)
        d_mid   = _dir(mid_mas)
        d_long  = _dir(long_mas)

        # Đư᨟ ng bảo vệ từ từng MA xuống (hỗ trợ) + khoảng cách %
        ma_distances = []
        for name, val in sorted(mas, key=lambda x: x[1], reverse=True):
            if val > 0:
                dist_pct = (close - val) / val * 100
                role = 'Hỗ trợ' if dist_pct >= 0 else 'Kháng cự'
                ma_distances.append(f"{name}={val:.2f} ({dist_pct:+.2f}% | {role})")
        ma_dist_str = ' | '.join(ma_distances)

        # Xác định tình trạng phân kỳ
        divergence_note = ""
        if d_short == 'down' and d_long == 'up':
            divergence_note = (
                f"PHÂN KỲ XU HƯỚNG: {symbol} giảm ngắn hạn TRONG xu hướng tăng dài hạn. "
                f"Cần đánh giá xu hướng tăng dài hạn có bị phá vỡ không."
            )
        elif d_short == 'up' and d_long == 'down':
            divergence_note = (
                f"PHÂN KỲ XU HƯỚNG: {symbol} tăng ngắn hạn NHƯNG xu hướng dài hạn vẫn giảm. "
                f"Cần đánh giá đây là hồi phục kỹ thuật hay đảo chiều thực sự."
            )
        elif d_short == d_mid == d_long == 'up':
            divergence_note = f"{symbol} trên tất cả MAs — xu hướng tăng đồng thuận toàn bộ khung thời gian."
        elif d_short == d_mid == d_long == 'down':
            divergence_note = f"{symbol} dưới tất cả MAs — xu hướng giảm đồng thuận toàn bộ khung thời gian."
        else:
            divergence_note = f"Tình trạng hỗn hợp: ngắn={'up' if d_short=='up' else 'down' if d_short else 'N/A'} | trung={'up' if d_mid=='up' else 'down' if d_mid else 'N/A'} | dài={'up' if d_long=='up' else 'down' if d_long else 'N/A'}"

        # ── 1 PROMPT DUY NHẤT cho cả 3 tabs ──────────────────────
        keltner_pos = ('Vượt trên Upper → quá mua' if close > safe_float(latest.get('keltner_h', 0))
                       else ('Thủng dưới Lower → quá bán' if close < safe_float(latest.get('keltner_l', 0))
                             else 'Trong kênh Keltner'))
        vwap_pos = 'trên' if close > safe_float(latest.get('vwap', 0)) else 'dưới'

        prompt_all = f"""Bạn là chuyên gia phân tích kỹ thuật thị trường chứng khoán Việt Nam.
Chỉ dùng số liệu được cung cấp. KHÔNG suy đoán nguyên nhân tăng/giảm của từng mã, KHÔNG đưa ra xác suất.

=== DỮ LIỆU {symbol} — {time_val} ===

[GIÁ & KHỐI LƯỢNG]
- Đóng cửa: {close:.2f} | Mở: {safe_float(latest['open']):.2f} | Cao: {safe_float(latest['high']):.2f} | Thấp: {safe_float(latest['low']):.2f}
- Khối lượng khớp lệnh: {current_vol/1_000_000:.3f} triệu CP — {vol_status} so với TB 20 phiên

[XU HƯỚNG MA & ĐỘNG LƯỢNG]
{trend_assessment}
- Khoảng cách tới từng MA: {ma_dist_str}
- Nhận xét phân kỳ: {divergence_note}
- ROC: {roc_str} → {roc_signal}
- ADX: {safe_float(latest['adx']):.2f} (>25: mạnh | 15-25: TB | <15: đi ngang)
- ATR: {safe_float(latest['atr']):.2f} điểm/phiên
- Keltner: Upper {safe_float(latest['keltner_h']):.2f} / Lower {safe_float(latest['keltner_l']):.2f} → {keltner_pos}

[DÒNG TIỀN]
- CMF: {safe_float(latest['cmf']):.4f} (>0: dòng tiền vào | <0: dòng tiền ra)
- VWAP: {safe_float(latest['vwap']):.2f} — Giá đang {vwap_pos} VWAP
- OBV: {safe_float(latest['obv']):.0f}

[{symbol} — THỊ TRƯỜNG]
{combined_market_str}

=== YÊU CẦU OUTPUT ===
Viết Markdown theo đúng cấu trúc sau (KHÔNG đổi tiêu đề, KHÔNG thêm block mới):

## [TAB:GENERAL]
### 1. Diễn biến phiên giao dịch
Giá đóng cửa, biến động so tham chiếu, khối lượng (triệu CP) vs TB 20 phiên.
### 2. Xu hướng & Động lượng
Liệt kê bullet points: từng mã MA (ngắn/trung/dài hạn), ROC, nhận xét tổng hợp.
### 3. Nhận định Xu hướng Tổng hợp
Viết theo đúng 7 mục dưới đây, mỗi mục 1–2 câu ngắn gọn, dùng đúng số liệu được cung cấp:

**Mở đầu:** Một câu đánh giá tổng quan xu hướng và tâm lý thị trường hiện tại ({divergence_note}), kèm lý do chính dựa trên MA và ROC.

**Độ rộng thị trường:** Dựa trên số mã tăng/giảm/đứng và tỷ lệ A/D trong dữ liệu đã cho — đà tăng/giảm có lan tỏa hay chỉ tập trung vào một số mã?

**Thanh khoản:** Khối lượng hiện tại {current_vol/1_000_000:.2f} triệu CP, {vol_status} so TB 20 phiên. Nhận xét mức độ thận trọng hay hưng phấn của dòng tiền.

**Sức khỏe thị trường:** Nhận xét về % mã trên MA20/50/200 từ dữ liệu breadth đã cho. Nếu không có số chính xác, nhận xét từ tỷ lệ A/D và vị trí giá so với MA. Đưa ra kết luận về mức độ lan tỏa của đợt phục hồi/điều chỉnh.

**Khuỳn nghị hành động:**
- *Cảnh báo:* Một câu cảnh báo chung dựa trên ADX={safe_float(latest['adx']):.1f}, CMF={safe_float(latest['cmf']):.4f}.
- *Chiến lược:* Giảm tỷ trọng / Đứng ngoài / Mua nhỏ lẻ / Chờ tín hiệu — chỉ chọn một phương án phù hợp nhất.

**Kết luận:** ➡️ **[Tạm đứng ngoài / Giảm tỷ trọng / Tăng tỷ trọng]** (chọn một) — một câu ngắn gói gọn trạng thái thị trường.

### 4. Thống kê Cổ phiếu & Nhóm ngành
Top 5 tăng/giảm kèm % theo đúng nhóm {symbol} | Ngành thu hút/rút tiền kèm % TB.
### 5. Market Breadth & Độ rộng thị trường
Số mã tăng/giảm/đứng, tỷ lệ A/D, phân tích độ phân hóa.

## [TAB:SCENARIO]
Bạn PHẢI trả về ĐẦY ĐỦ 3 KỊCH BẢN: TÍCH CỰC, TRUNG TÍNH, TIÊU CỰC. Kịch bản nào có xác suất xảy ra cao nhất, hãy thêm cụm "(Xác suất cao nhất)" vào tiêu đề kịch bản đó. Viết theo đúng cấu trúc Markdown sau:

### 1. KỊCH BẢN TÍCH CỰC [Thêm (Xác suất cao nhất) nếu đúng]
* **Xác suất xảy ra:** [Điền số]%
* **Độ tin cậy:** [Điền điểm]/10

**Điều kiện kích hoạt:**
- Giá vượt dứt khoát kháng cự {resistance_price} với độ rộng thị trường (Breadth) tích cực.
- [Thêm 1-2 điều kiện phụ dựa trên dữ liệu]

### 2. KỊCH BẢN TRUNG TÍNH (Dao động trong range {support_price} - {resistance_price}) [Thêm (Xác suất cao nhất) nếu đúng]
* **Xác suất xảy ra:** [Điền số]%
* **Độ tin cậy:** [Điền điểm]/10

**Điều kiện kích hoạt:**
- Giá tiếp tục dao động, không thể vượt {resistance_price} nhưng cũng không thủng {support_price}.
- Biến động duy trì ở mức {volatility_regime} và Trend Agreement Score duy trì [trên/dưới] mức 50.

### 3. KỊCH BẢN TIÊU CỰC [Thêm (Xác suất cao nhất) nếu đúng]
* **Xác suất xảy ra:** [Điền số]%
* **Độ tin cậy:** [Điền điểm]/10

**Điều kiện kích hoạt:**
- Giá thủng dứt khoát hỗ trợ {support_price} với khối lượng lớn, độ rộng thị trường tiêu cực.
- [Thêm 1-2 điều kiện phụ dựa trên dữ liệu]

### Dẫn chứng chung cho các kịch bản:
- **Volatility regime = {volatility_regime}:** Biên độ dao động (20 phiên) ≈ {volatility_value}% của giá, hỗ trợ cho kịch bản [sideway biên độ rộng / xu hướng rõ ràng].
- **Trend agreement score = {tas_score}/100 ({tas_status}):** Cho thấy xu hướng [giảm/tăng] vẫn chi phối, khiến mọi đợt [hồi/chỉnh] khó bền vững.
- **Khoảng đệm kỹ thuật:** Khoảng cách tới hỗ trợ/kháng cự hiện tại là {support_distance}% / {resistance_distance}% cho thấy thị trường đang ở vị trí "[giữa hai mốc / sát vùng ranh giới]" quan trọng.
- **Horizon (Tầm nhìn):** 5-15 phiên.

*Quy tắc đánh giá:* Nếu Tas_score thấp (<30) nhưng Volatility cao và giá nằm giữa range hỗ trợ/kháng cự, ưu tiên kịch bản Trung tính (45-55%) hoặc Tiêu cực. Nếu Tas_score > 70 và Breadth tích cực, ưu tiên kịch bản Tích cực. Độ tin cậy (Thang điểm 10): Chấm điểm dựa trên tính đồng thuận của dữ liệu. Nếu Volatility đồng nhất với cấu trúc giá và khoảng đệm rõ ràng -> Chấm điểm từ 7-9/10. Nếu các chỉ báo đá nhau (Nhiễu) -> Chấm dưới 6/10.


## [TAB:VOLUME]
### 1. Thống kê Chỉ báo Khối lượng
Bảng CMF/VWAP/OBV với giá trị thực và nhận định ngắn.
### 2. Nhận định Dòng tiền
Dòng tiền ròng vào/ra? Áp lực mua/bán vs VWAP? Dấu hiệu phân phối?

## [TAB:TREND]
### 1. Thống kê Xu hướng & Động lượng
Bảng: từng MA với giá trị, khoảng cách % tới giá hiện tại (hỗ trợ/kháng cự), ROC, ADX, ATR, Keltner.
### 2. Phân tích Xu hướng Chi tiết
Viết theo đúng 4 mục sau, dùng đúng số liệu được cung cấp:

**Tình trạng xu hướng:** Một câu mô tả rõ {symbol} đang trong xu hướng ngắn hạn/trung hạn/dài hạn gì (ví dụ: “Giảm ngắn và trung hạn, tăng dài hạn”). Phân kỳ: {divergence_note}

**Sức bền xu hướng dài hạn:** Dựa trên:
- ADX = {safe_float(latest['adx']):.1f} → sức mạnh xu hướng hiện tại (>25 mạnh, <15 yếu)
- CMF = {safe_float(latest['cmf']):.4f} → dòng tiền vào/ra
- Khối lượng: {vol_status} so TB 20 phiên
- Khoảng cách tới MA dài hạn: {ma_dist_str}
Đưa ra nhận xét: xu hướng dài hạn có dễ/khó bị phá vỡ không?

**Ngưỡng giá then chốt:** Liệt kê 2–3 mức hỗ trợ/kháng cự quan trọng nhất từ các MA, kèm giá trị.

**Kết luận:** ➡️ **[Tạm đứng ngoài / Giảm tỷ trọng / Tăng tỷ trọng]** — một câu ngắn gói gọn trạng thái và định hướng hành động.
"""


        ai_response = ask_ai(prompt_all,
            "Bạn là chuyên gia phân tích kỹ thuật và chiến lược thị trường chứng khoán. "
            "Dùng đúng số liệu được cung cấp, viết ngắn gọn súc tích, không thêm số liệu bẺ, "
            "không đưa ra xác suất hay kịch bản tự đoán ngoài yêu cầu. "
            "Output phải có đúng 4 block ## [TAB:GENERAL], ## [TAB:SCENARIO], ## [TAB:VOLUME], ## [TAB:TREND].")

        def parse_tab(response, tag):
            """Tách nội dung theo tag ## [TAB:XXX]"""
            if not response:
                return None
            import re
            pattern = rf'## \[TAB:{tag}\](.*?)(?=## \[TAB:|$)'
            match = re.search(pattern, response, re.DOTALL)
            return match.group(1).strip() if match else None

        if ai_response:
            general_markdown  = parse_tab(ai_response, "GENERAL") or generate_rule_based_analysis(**rb_args, tab_type="general")
            scenario_markdown = parse_tab(ai_response, "SCENARIO")
            volume_markdown   = parse_tab(ai_response, "VOLUME")  or generate_rule_based_analysis(**rb_args, tab_type="volume")
            trend_markdown    = parse_tab(ai_response, "TREND")   or generate_rule_based_analysis(**rb_args, tab_type="trend")
        else:
            general_markdown  = generate_rule_based_analysis(**rb_args, tab_type="general")
            scenario_markdown = None
            volume_markdown   = generate_rule_based_analysis(**rb_args, tab_type="volume")
            trend_markdown    = generate_rule_based_analysis(**rb_args, tab_type="trend")

        # Delay giữa các symbol để tránh rate limit
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
            "tas": {
                **tas_res,
                "history": compute_tas_history_fast(df)
            },
            "candle_patterns": detect_candle_patterns(df),
            "sr_zones":        sr_zones_res,
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
    import time, concurrent.futures
    import pandas as pd
    
    end_ts = int(time.time())
    start_ts = end_ts - 365*24*3600
    symbols = list(raw_stocks.keys())
    
    print(f"[BREADTH] Fetching 1Y history for {len(symbols)} stocks via VNDIRECT API...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(fetch_historical_vndirect, sym, start_ts, end_ts): sym for sym in symbols}
        for future in concurrent.futures.as_completed(futures):
            sym = futures[future]
            try:
                _, data = future.result()
                if not data or 'c' not in data or len(data['c']) == 0:
                    continue
                
                closes = pd.Series(data['c'])
                highs = pd.Series(data['h'])
                lows = pd.Series(data['l'])
                
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
                # Giá >= đỉnh 52T hoặc cách đỉnh 1%
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
                
            except Exception as e:
                pass
    print("[BREADTH] Historical data fetch & compute completed.")
    return raw_stocks

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
    try:
        _listing  = VCIListing(show_log=False)
        _trading  = VCITrading(show_log=False)

        # Lấy danh sách mã — fallback sang hardcode nếu API không có phương thức
        def _get_group_syms(group, fallback):
            try:
                df_all = _listing.all_symbols()
                # Tìm cột chứa thông tin group/index
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
                print(f"  [BOARDS] all_symbols filter failed: {e}")
            return fallback  # hardcode fallback

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
            return raw

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

        # Fetch VNINDEX (HOSE) — chỉ cổ phiếu, loại CW/ETF
        vnindex_syms = []
        try:
            df_all = _listing.symbols_by_exchange()
            # Lọc: exchange HOSE + type STOCK (loại CW, ETF, ...)
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
        # Split into chunks of 50 initially
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
                # Split into 10
                chunks_10 = [chunk[i:i+10] for i in range(0, len(chunk), 10)]
                for sub in chunks_10:
                    try:
                        raw_sub = _trading.price_board(symbols_list=sub)
                        if not raw_sub.empty:
                            vnindex_dfs.append(raw_sub)
                        time.sleep(0.5)
                        continue
                    except Exception as e2:
                        # Fallback to individual
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
            # Remove duplicates if any
            raw_vnindex = raw_vnindex.loc[raw_vnindex.astype(str).drop_duplicates().index]
            price_boards['VNINDEX'] = _normalize_board(raw_vnindex).sort_values('change_pc', ascending=False)
        else:
            if 'VN100' in price_boards:
                price_boards['VNINDEX'] = price_boards['VN100'].copy()

        print(f"[BOARDS] Done: VN30={len(price_boards.get('VN30',[]))} | VN100={len(price_boards.get('VN100',[]))} | VNINDEX={len(price_boards.get('VNINDEX',[]))}")
        sys.stdout.flush()

    except Exception as e:
        print(f"[BOARDS] Failed: {e}")
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
        raw_stocks = enrich_raw_stocks_with_breadth(raw_stocks)

    # Gắn sector_heatmap vào tất cả index
    for sym in all_data:
        all_data[sym]['sector_heatmap'] = sector_heatmap
        
    all_data['__global__'] = {
        'raw_stocks': raw_stocks
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
