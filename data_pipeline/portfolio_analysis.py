"""
portfolio_analysis.py — Phân tích Danh mục cổ phiếu đang nắm giữ.

Đọc danh mục từ `portfolio.json` (gốc repo), lấy lịch sử giá từng mã, rồi sinh
mô tả kỹ thuật theo luật cố định (không dùng AI) gồm 3 phần:
  1. Kỹ thuật tổng quan (MA, RSI, MACD, ADX, khối lượng, đỉnh/đáy 52 tuần)
  2. ATR — biến động, stoploss ban đầu, trailing stop (Chandelier), mục tiêu theo R
  3. SMC — cấu trúc thị trường, Order Block, FVG, thanh khoản (dùng
     compute_bigbeluga_smc của pipeline chính) + liên hệ với điểm mua

Kết quả ghi ra `output/portfolio.json` để frontend hiển thị.
Mọi giá trong output đều tính bằng VND (đồng).
"""

import json
import math
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

ATR_LEN = 14
INIT_STOP_ATR = 2.0      # Stoploss ban đầu = Giá mua − 2×ATR (tại ngày mua)
CHANDELIER_ATR = 3.0     # Trailing stop = Đỉnh cao nhất từ ngày mua − 3×ATR
SMC_STOP_BUFFER_ATR = 0.5


# ─────────────────────────────────────────────────────────────
# Đọc danh mục
# ─────────────────────────────────────────────────────────────

def find_portfolio_file():
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(os.path.dirname(here), 'portfolio.json'),
              os.path.join(here, 'portfolio.json'),
              'portfolio.json'):
        if os.path.exists(p):
            return p
    return None


def _to_vnd(price):
    """Người dùng có thể nhập 20800 (đồng) hoặc 20.8 (nghìn đồng)."""
    if price is None or price == "":
        return None
    p = float(price)
    if p <= 0:
        return None
    return p * 1000 if p < 1000 else p


def load_portfolio(path=None):
    path = path or find_portfolio_file()
    if not path:
        return []
    with open(path, 'r', encoding='utf-8') as f:
        raw = json.load(f)
    items = raw.get('holdings', raw) if isinstance(raw, dict) else raw
    out = []
    for h in items or []:
        sym = str(h.get('symbol', '')).strip().upper()
        buy_price = _to_vnd(h.get('buy_price'))
        buy_date = str(h.get('buy_date', '')).strip()
        if not sym or not buy_price or not buy_date:
            print(f"  [PORTFOLIO] Bỏ qua dòng thiếu symbol/buy_date/buy_price: {h}")
            continue
        try:
            datetime.strptime(buy_date, '%Y-%m-%d')
        except ValueError:
            print(f"  [PORTFOLIO] {sym}: buy_date phải có dạng YYYY-MM-DD, nhận '{buy_date}'")
            continue
        out.append({
            'symbol': sym,
            'buy_date': buy_date,
            'buy_price': buy_price,
            'quantity': h.get('quantity'),
            'thesis': (h.get('thesis') or '').strip(),
            'stop_loss': _to_vnd(h.get('stop_loss')),
            'target': _to_vnd(h.get('target')),
            'note': (h.get('note') or '').strip(),
        })
    return out


# ─────────────────────────────────────────────────────────────
# Chỉ báo (pandas thuần, không phụ thuộc thư viện `ta`)
# ─────────────────────────────────────────────────────────────

def _rma(s, n):
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def prepare_df(df):
    """Chuẩn hoá: sort theo ngày, cột date 'YYYY-MM-DD', giá quy về VND."""
    d = df.copy()
    d['time'] = pd.to_datetime(d['time'])
    d = d.sort_values('time').reset_index(drop=True)
    for c in ('open', 'high', 'low', 'close', 'volume'):
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d = d.dropna(subset=['open', 'high', 'low', 'close']).reset_index(drop=True)
    # VCI / VNDIRECT trả giá cổ phiếu theo nghìn đồng → quy về đồng
    if d['close'].median() < 1000:
        for c in ('open', 'high', 'low', 'close'):
            d[c] = d[c] * 1000
    d['date'] = d['time'].dt.strftime('%Y-%m-%d')
    return d


def add_indicators(d):
    c, h, l, v = d['close'], d['high'], d['low'], d['volume'].fillna(0)
    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    d['tr'] = tr
    d['atr'] = _rma(tr, ATR_LEN)
    d['atr_pct'] = d['atr'] / c * 100
    for n in (10, 20, 50, 200):
        d[f'ma{n}'] = c.rolling(n).mean()
    delta = c.diff()
    gain = _rma(delta.clip(lower=0), 14)
    loss = _rma((-delta).clip(lower=0), 14)
    rs = gain / loss.replace(0, np.nan)
    d['rsi'] = (100 - 100 / (1 + rs)).fillna(50)
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    d['macd'] = ema12 - ema26
    d['macd_signal'] = d['macd'].ewm(span=9, adjust=False).mean()
    d['macd_hist'] = d['macd'] - d['macd_signal']
    up = h.diff()
    dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr_ = _rma(tr, 14)
    plus_di = 100 * _rma(pd.Series(plus_dm, index=d.index), 14) / atr_
    minus_di = 100 * _rma(pd.Series(minus_dm, index=d.index), 14) / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    d['adx'] = _rma(dx.fillna(0), 14)
    d['plus_di'] = plus_di
    d['minus_di'] = minus_di
    d['vol_ma20'] = v.rolling(20).mean()
    return d


# ─────────────────────────────────────────────────────────────
# Tiện ích
# ─────────────────────────────────────────────────────────────

def _f(x, nd=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return round(x, nd)


def _p(x):
    """Định dạng giá VND: 20,800"""
    return f"{x:,.0f}" if x is not None else "—"


def _pct(a, b):
    return (a - b) / b * 100 if b else 0.0


def _swing_points(d, length=5, lookback=150):
    """Đỉnh/đáy swing (pivot `length` nến hai bên) trong `lookback` phiên gần nhất."""
    start = max(0, len(d) - lookback)
    highs, lows = [], []
    H, L = d['high'].values, d['low'].values
    for i in range(start + length, len(d) - length):
        win_h = H[i - length:i + length + 1]
        win_l = L[i - length:i + length + 1]
        if H[i] == win_h.max():
            highs.append((i, float(H[i])))
        if L[i] == win_l.min():
            lows.append((i, float(L[i])))
    return highs, lows


def _liquidity_pools(d, atr):
    """Buy-side (trên đỉnh cũ chưa bị phá) & Sell-side (dưới đáy cũ chưa bị phá)."""
    highs, lows = _swing_points(d)
    H, L, dates = d['high'].values, d['low'].values, d['date'].values
    n = len(d)
    close = float(d['close'].iloc[-1])
    bsl, ssl = [], []
    for i, p in highs:
        if p > close and (i + 1 >= n or H[i + 1:].max() <= p):
            bsl.append({'price': p, 'date': dates[i]})
    for i, p in lows:
        if p < close and (i + 1 >= n or L[i + 1:].min() >= p):
            ssl.append({'price': p, 'date': dates[i]})
    bsl.sort(key=lambda x: x['price'])
    ssl.sort(key=lambda x: -x['price'])

    def _mark_equal(pools):
        tol = 0.3 * atr
        for a in pools:
            a['equal'] = any(b is not a and abs(b['price'] - a['price']) <= tol for b in pools)
        return pools
    return _mark_equal(bsl[:4]), _mark_equal(ssl[:4])


# ─────────────────────────────────────────────────────────────
# Phân tích một mã
# ─────────────────────────────────────────────────────────────

def analyze_holding(h, df_raw, smc_fn=None):
    d = add_indicators(prepare_df(df_raw))
    if len(d) < 30:
        return None
    last = d.iloc[-1]
    close = float(last['close'])
    atr = float(last['atr'])
    atr_pct = float(last['atr_pct'])
    sym = h['symbol']
    buy = h['buy_price']
    buy_date = h['buy_date']

    # Phiên mua = phiên giao dịch gần nhất <= ngày mua
    after = d.index[d['date'] <= buy_date]
    buy_idx = int(after[-1]) if len(after) else 0
    buy_in_range = len(after) > 0
    since = d.iloc[buy_idx:]
    days_held = (datetime.now() - datetime.strptime(buy_date, '%Y-%m-%d')).days
    sessions_held = len(d) - 1 - buy_idx

    # ── Kỹ thuật tổng quan ─────────────────────────────
    ma = {n: _f(last.get(f'ma{n}'), 0) for n in (10, 20, 50, 200)}
    rsi = float(last['rsi'])
    adx = float(last['adx'])
    macd_hist = float(last['macd_hist'])
    macd_hist_prev = float(d['macd_hist'].iloc[-2])
    vol_ratio = float(last['volume'] / last['vol_ma20']) if last['vol_ma20'] else None
    w52 = d.iloc[-250:]
    hi52, lo52 = float(w52['high'].max()), float(w52['low'].min())
    ret5 = _pct(close, float(d['close'].iloc[-6])) if len(d) > 6 else 0
    ret20 = _pct(close, float(d['close'].iloc[-21])) if len(d) > 21 else 0
    pnl_pct = _pct(close, buy)

    above = [n for n in (20, 50, 200) if ma[n] and close > ma[n]]
    if ma[20] and ma[50] and ma[200] and close > ma[20] > ma[50] > ma[200]:
        ma_state = 'Xếp chồng TĂNG hoàn hảo (Giá > MA20 > MA50 > MA200)'
        ma_score = 2
    elif ma[20] and ma[50] and ma[200] and close < ma[20] < ma[50] < ma[200]:
        ma_state = 'Xếp chồng GIẢM (Giá < MA20 < MA50 < MA200)'
        ma_score = -2
    elif len(above) >= 2:
        ma_state = f"Giá nằm trên {len(above)}/3 đường MA chính ({', '.join('MA' + str(n) for n in above)})"
        ma_score = 1
    else:
        ma_state = f"Giá nằm dưới {3 - len(above)}/3 đường MA chính"
        ma_score = -1

    tech = []
    tech.append(f"- **Xu hướng MA:** {ma_state}. MA20 `{_p(ma[20])}` · MA50 `{_p(ma[50])}` · MA200 `{_p(ma[200])}`.")
    rsi_txt = ('quá mua — dễ rung lắc/chốt lời' if rsi >= 70 else
               'quá bán — có thể hồi kỹ thuật' if rsi <= 30 else
               'vùng mạnh, động lượng tăng' if rsi >= 55 else
               'vùng yếu, động lượng giảm' if rsi <= 45 else 'trung tính')
    tech.append(f"- **RSI(14):** `{rsi:.1f}` — {rsi_txt}.")
    macd_txt = ('Histogram dương và mở rộng → động lượng tăng đang mạnh lên' if macd_hist > 0 and macd_hist >= macd_hist_prev else
                'Histogram dương nhưng thu hẹp → động lượng tăng suy yếu' if macd_hist > 0 else
                'Histogram âm và mở rộng → áp lực giảm gia tăng' if macd_hist < macd_hist_prev else
                'Histogram âm nhưng thu hẹp → lực bán đang yếu dần')
    tech.append(f"- **MACD(12,26,9):** {macd_txt}.")
    adx_txt = ('xu hướng rất mạnh' if adx >= 40 else 'có xu hướng rõ' if adx >= 25 else
               'xu hướng yếu / đi ngang' if adx >= 18 else 'không có xu hướng (sideway)')
    di_txt = 'phe Mua (+DI > −DI) chiếm ưu thế' if last['plus_di'] > last['minus_di'] else 'phe Bán (−DI > +DI) chiếm ưu thế'
    tech.append(f"- **ADX(14):** `{adx:.1f}` — {adx_txt}, {di_txt}.")
    if vol_ratio is not None:
        v_txt = ('bùng nổ' if vol_ratio >= 2 else 'cao hơn trung bình' if vol_ratio >= 1.2 else
                 'thấp — thiếu xác nhận' if vol_ratio < 0.7 else 'bình thường')
        tech.append(f"- **Khối lượng:** phiên gần nhất bằng `{vol_ratio:.2f}x` trung bình 20 phiên — {v_txt}.")
    tech.append(f"- **Biên độ 52 tuần:** đáy `{_p(lo52)}` – đỉnh `{_p(hi52)}`; giá hiện cách đỉnh `{_pct(close, hi52):+.1f}%`, cách đáy `{_pct(close, lo52):+.1f}%`.")
    tech.append(f"- **Hiệu suất:** 5 phiên `{ret5:+.2f}%` · 20 phiên `{ret20:+.2f}%` · từ ngày mua `{pnl_pct:+.2f}%` ({sessions_held} phiên).")

    # ── ATR ────────────────────────────────────────────
    atr_hist = d['atr_pct'].iloc[-250:].dropna()
    atr_rank = float((atr_hist < atr_pct).mean() * 100) if len(atr_hist) else 50.0
    atr_20ago = float(d['atr'].iloc[-21]) if len(d) > 21 else atr
    atr_change = _pct(atr, atr_20ago)
    entry_atr = float(d['atr'].iloc[buy_idx]) if buy_in_range else atr
    if math.isnan(entry_atr) or entry_atr <= 0:
        entry_atr = atr

    user_stop = h.get('stop_loss')
    init_stop = user_stop if user_stop else buy - INIT_STOP_ATR * entry_atr
    risk_r = buy - init_stop if buy > init_stop else entry_atr * INIT_STOP_ATR
    highest_since = float(since['high'].max())
    lowest_since = float(since['low'].min())
    chandelier = highest_since - CHANDELIER_ATR * atr
    trailing = max(init_stop, chandelier)
    targets = [{'label': f'{k}R', 'price': buy + k * risk_r, 'hit': highest_since >= buy + k * risk_r}
               for k in (1, 2, 3)]
    user_target = h.get('target')
    r_mult = (close - buy) / risk_r if risk_r else 0
    mfe_r = (highest_since - buy) / risk_r if risk_r else 0
    mae_r = (lowest_since - buy) / risk_r if risk_r else 0
    dist_trail_atr = (close - trailing) / atr if atr else 0

    vol_regime = ('THẤP' if atr_pct < 2 else 'TRUNG BÌNH' if atr_pct < 3.5 else 'CAO')
    atr_lines = []
    atr_lines.append(
        f"- **ATR(14) hiện tại:** `{_p(atr)}` đ/phiên = **{atr_pct:.2f}%** giá → biến động **{vol_regime}**. "
        f"ATR% hiện cao hơn {atr_rank:.0f}% số phiên trong 1 năm qua — "
        + ('biến động đang ở vùng **thấp so với lịch sử**.' if atr_rank < 25 else
           'biến động đang ở vùng **cao so với lịch sử**.' if atr_rank > 75 else 'mức biến động quen thuộc của mã.'))
    atr_lines.append(
        f"- **Xu hướng biến động:** ATR {'tăng' if atr_change > 0 else 'giảm'} `{atr_change:+.1f}%` so với 20 phiên trước — "
        + ('biến động đang **mở rộng**, thường đi kèm phá vỡ hoặc bán tháo; nới stop / giảm khối lượng.' if atr_change > 15 else
           'biến động đang **co hẹp**, giá tích luỹ — chuẩn bị cho một nhịp bùng nổ.' if atr_change < -15 else
           'biến động ổn định.'))
    atr_lines.append(
        f"- **Biên độ dự kiến phiên tới (±1 ATR):** `{_p(close - atr)}` – `{_p(close + atr)}`. "
        f"Giá đã đi `{(close - buy) / atr:+.1f} ATR` kể từ điểm mua.")
    stop_src = 'do bạn đặt' if user_stop else f'= Giá mua − {INIT_STOP_ATR:g}×ATR lúc mua ({_p(entry_atr)})'
    atr_lines.append(
        f"- **Stoploss ban đầu:** `{_p(init_stop)}` ({stop_src}) → rủi ro **1R = {_p(risk_r)} đ/cp** ({risk_r / buy * 100:.1f}%).")
    atr_lines.append(
        f"- **Trailing stop (Chandelier {CHANDELIER_ATR:g}×ATR):** `{_p(trailing)}` = đỉnh từ ngày mua `{_p(highest_since)}` − {CHANDELIER_ATR:g}×ATR"
        + (" (đang dùng stop ban đầu vì cao hơn)." if trailing == init_stop and chandelier < init_stop else ".")
        + f" Giá hiện cách stop **{dist_trail_atr:.1f} ATR** ({_pct(close, trailing):+.1f}%).")
    tg_txt = ' · '.join(f"{t['label']} `{_p(t['price'])}`{' ✅' if t['hit'] else ''}" for t in targets)
    atr_lines.append(f"- **Mục tiêu theo R:** {tg_txt}" + (f" · Mục tiêu của bạn `{_p(user_target)}`" if user_target else '') + '.')
    atr_lines.append(
        f"- **Vị thế hiện tại:** `{r_mult:+.2f}R`. Tốt nhất từng đạt `{mfe_r:+.2f}R` (đỉnh `{_p(highest_since)}`), "
        f"xấu nhất `{mae_r:+.2f}R` (đáy `{_p(lowest_since)}`).")
    if dist_trail_atr < 0:
        atr_lines.append("- 🔴 **Giá đã đóng cửa dưới trailing stop ATR** — kỷ luật là thoát vị thế hoặc giảm mạnh tỷ trọng.")
    elif dist_trail_atr < 1:
        atr_lines.append("- ⚠️ **Giá chỉ còn cách trailing stop dưới 1 ATR** — một phiên biến động bình thường cũng có thể kích hoạt stop.")
    if mfe_r >= 1 and trailing < buy:
        atr_lines.append(f"- 💡 Vị thế từng đạt +1R: cân nhắc dời stop lên **hoà vốn** `{_p(buy)}` để khoá rủi ro.")

    # ── SMC ────────────────────────────────────────────
    smc = None
    if smc_fn is not None:
        try:
            smc = smc_fn(d[['time', 'open', 'high', 'low', 'close', 'volume']].copy(), sym)
        except Exception as e:  # SMC lỗi không được làm hỏng cả danh mục
            print(f"  [PORTFOLIO] SMC lỗi {sym}: {e}")
            smc = None

    bsl, ssl = _liquidity_pools(d, atr)
    smc_lines = []
    smc_stop = None
    smc_targets = []
    trend = smc['trend'] if smc else 0
    choch_after_buy = None
    if smc:
        trend_txt = 'TĂNG (Bullish)' if trend == 1 else 'GIẢM (Bearish)' if trend == -1 else 'TRUNG TÍNH'
        smc_lines.append(f"- **Cấu trúc hiện tại:** **{trend_txt}**"
                         + (f" · CHoCH `{_p(smc['choch_level'])}`" if smc.get('choch_level') else '')
                         + (f" · BOS `{_p(smc['bos_level'])}`" if smc.get('bos_level') else '') + '.')
        evs = [e for e in (smc.get('events') or []) if e.get('x2_date', '') >= buy_date and e.get('style') == 'solid']
        evs.sort(key=lambda e: e['x2_date'])
        if evs:
            ev_txt = ', '.join(f"{e['txt']} {'↑' if e['dir'] == 'bull' else '↓'} {_p(e['y'])} ({e['x2_date']})" for e in evs[-5:])
            smc_lines.append(f"- **Diễn biến cấu trúc từ ngày mua:** {ev_txt}.")
            chochs = [e for e in evs if e['txt'] == 'CHoCH']
            if chochs:
                choch_after_buy = chochs[-1]
        else:
            smc_lines.append("- **Diễn biến cấu trúc từ ngày mua:** chưa có BOS/CHoCH mới được xác nhận.")

        bull_obs = smc.get('bull_obs') or []
        bear_obs = smc.get('bear_obs') or []
        in_ob = next((ob for ob in bull_obs if ob['btm'] <= buy <= ob['top']), None)
        if in_ob:
            smc_lines.append(f"- ✅ **Điểm mua nằm trong Bullish OB** `{_p(in_ob['btm'])}–{_p(in_ob['top'])}` — mua đúng vùng cầu tổ chức.")
        else:
            below_ob = [ob for ob in bull_obs if ob['top'] < buy]
            if below_ob:
                ob = max(below_ob, key=lambda o: o['top'])
                smc_lines.append(f"- **Điểm mua so với vùng cầu:** nằm trên Bullish OB gần nhất `{_p(ob['btm'])}–{_p(ob['top'])}` "
                                 f"{_pct(buy, ob['top']):+.1f}% — mua ở vùng giá cao hơn vùng cầu.")
        sup_obs = [ob for ob in bull_obs if ob['btm'] < close]
        if sup_obs:
            ob = max(sup_obs, key=lambda o: o['top'])
            smc_lines.append(f"- 🟢 **Vùng cầu bảo vệ (Bullish OB):** `{_p(ob['btm'])}–{_p(ob['top'])}` (mid `{_p(ob['avg'])}`, {ob['vol_pct']}% KL) "
                             f"— cách giá {_pct(ob['top'], close):+.1f}%.")
        res_obs = [ob for ob in bear_obs if ob['top'] > close]
        if res_obs:
            ob = min(res_obs, key=lambda o: o['btm'])
            smc_lines.append(f"- 🔴 **Vùng cung phía trên (Bearish OB):** `{_p(ob['btm'])}–{_p(ob['top'])}` — cách giá {_pct(ob['btm'], close):+.1f}%; "
                             f"vùng chốt lời / kháng cự đầu tiên.")
            smc_targets.append({'label': 'Bear OB', 'price': ob['btm']})
        bfvg = [f for f in (smc.get('bull_fvgs') or []) if f['top'] < close]
        sfvg = [f for f in (smc.get('bear_fvgs') or []) if f['btm'] > close]
        if bfvg:
            f = max(bfvg, key=lambda x: x['top'])
            smc_lines.append(f"- **Bullish FVG chưa lấp phía dưới:** `{_p(f['btm'])}–{_p(f['top'])}` — giá có xu hướng quay về lấp trước khi đi tiếp.")
        if sfvg:
            f = min(sfvg, key=lambda x: x['btm'])
            smc_lines.append(f"- **Bearish FVG chưa lấp phía trên:** `{_p(f['btm'])}–{_p(f['top'])}` — nam châm hút giá khi hồi.")
            smc_targets.append({'label': 'Bear FVG', 'price': f['btm']})

        # Mức vô hiệu hoá theo SMC (dưới OB hỗ trợ hoặc CHoCH khi xu hướng tăng)
        cands = []
        if sup_obs:
            cands.append(max(sup_obs, key=lambda o: o['top'])['btm'])
        if trend == 1 and smc.get('choch_level') and smc['choch_level'] < close:
            cands.append(smc['choch_level'])
        if cands:
            smc_stop = max(cands) - SMC_STOP_BUFFER_ATR * atr

    if bsl:
        tags = ' · '.join(f"`{_p(x['price'])}`{' (Equal Highs)' if x['equal'] else ''}" for x in bsl[:3])
        smc_lines.append(f"- 💧 **Buy-side liquidity (đỉnh cũ chưa bị phá):** {tags} — nơi tập trung lệnh stop của phe bán, là mục tiêu tự nhiên của giá.")
        smc_targets.append({'label': 'BSL', 'price': bsl[0]['price']})
    if ssl:
        tags = ' · '.join(f"`{_p(x['price'])}`{' (Equal Lows)' if x['equal'] else ''}" for x in ssl[:3])
        smc_lines.append(f"- 💧 **Sell-side liquidity (đáy cũ chưa bị phá):** {tags} — vùng dễ bị quét stop; tránh đặt stop đúng tại các đáy này.")
    if smc_stop is not None:
        smc_lines.append(f"- 🛡️ **Mức vô hiệu hoá theo SMC:** `{_p(smc_stop)}` (dưới vùng cầu/CHoCH {SMC_STOP_BUFFER_ATR:g} ATR). "
                         f"So với trailing ATR `{_p(trailing)}`: "
                         + ('hai mức gần nhau → vùng stop **hợp lưu**, độ tin cậy cao.' if abs(smc_stop - trailing) <= 0.5 * atr else
                            'stop SMC chặt hơn, phù hợp quản trị rủi ro ngắn hạn.' if smc_stop > trailing else
                            'stop ATR chặt hơn; stop SMC là lớp phòng thủ cuối.'))
    smc_targets.sort(key=lambda t: t['price'])

    # ── Kết luận hành động (luật cố định) ──────────────
    reasons = []
    if dist_trail_atr < 0:
        verdict, tone = 'THOÁT / CẮT LỖ', 'bear'
        reasons.append('giá đóng cửa dưới trailing stop ATR')
    elif choch_after_buy and choch_after_buy['dir'] == 'bear' and trend == -1:
        verdict, tone = 'GIẢM TỶ TRỌNG', 'bear'
        reasons.append(f"xuất hiện CHoCH giảm ({choch_after_buy['x2_date']}) sau ngày mua")
    elif trend == -1 and ma_score < 0:
        verdict, tone = 'GIẢM TỶ TRỌNG', 'bear'
        reasons.append('cấu trúc SMC giảm và giá dưới các MA chính')
    elif (r_mult >= 2) or rsi >= 75 or (smc_targets and smc_targets[0]['price'] - close <= 0.5 * atr):
        verdict, tone = 'CHỐT LỜI TỪNG PHẦN', 'warn'
        if r_mult >= 2:
            reasons.append(f'lợi nhuận đã đạt {r_mult:.1f}R')
        if rsi >= 75:
            reasons.append('RSI quá mua')
        if smc_targets and smc_targets[0]['price'] - close <= 0.5 * atr:
            reasons.append(f"giá sát vùng cản {smc_targets[0]['label']} {_p(smc_targets[0]['price'])}")
    elif trend == 1 and ma_score > 0:
        verdict, tone = 'NẮM GIỮ', 'bull'
        reasons.append('cấu trúc SMC tăng và giá trên các MA chính')
        if dist_trail_atr < 1:
            reasons.append('nhưng sát trailing stop')
    else:
        verdict, tone = 'THEO DÕI', 'neutral'
        reasons.append('tín hiệu kỹ thuật và cấu trúc chưa đồng thuận')

    active_stop = trailing
    if smc_stop is not None and trailing < smc_stop < close:
        active_stop = smc_stop
    near_tg = (f"`{_p(smc_targets[0]['price'])}` ({smc_targets[0]['label']})" if smc_targets
               else f"{targets[1]['label']} `{_p(targets[1]['price'])}`")
    if verdict == 'THOÁT / CẮT LỖ':
        tail = (f"Giá `{_p(close)}` đã thủng stop `{_p(trailing)}`; chỉ mua lại khi giá lấy lại mức này "
                f"kèm tín hiệu CHoCH tăng.")
    elif tone == 'bear':
        tail = (f"Hạ tỷ trọng, phần còn lại giữ stop chặt `{_p(active_stop)}`; "
                f"luận điểm kỹ thuật chỉ phục hồi khi giá vượt lại CHoCH"
                + (f" `{_p(smc['choch_level'])}`." if smc and smc.get('choch_level') else '.'))
    elif tone == 'warn':
        tail = f"Chốt 1/3–1/2 vị thế quanh {near_tg}, dời stop phần còn lại lên `{_p(max(active_stop, buy) if mfe_r >= 1 else active_stop)}`."
    else:
        tail = f"Giữ kỷ luật với stop `{_p(active_stop)}`, mục tiêu gần nhất {near_tg}."
    summary = f"**{verdict}** — {', '.join(reasons)}. {tail}"

    md = []
    md.append("### 1. Kỹ thuật tổng quan")
    md += tech
    md.append("\n### 2. Phân tích ATR — Biến động & Quản trị rủi ro")
    md += atr_lines
    md.append("\n### 3. Phân tích SMC — Smart Money Concepts")
    md += (smc_lines or ["- Chưa đủ dữ liệu để tính SMC."])
    md.append("\n### 4. Kết luận")
    md.append(f"➡️ {summary}")

    qty = h.get('quantity')
    try:
        qty = float(qty) if qty not in (None, '') else None
    except (TypeError, ValueError):
        qty = None

    smc_out = None
    if smc:
        smc_out = {k: smc.get(k) for k in ('trend', 'trend_label', 'bos_level', 'choch_level', 'last_event',
                                           'chart_events', 'bull_obs', 'bear_obs', 'bull_fvgs', 'bear_fvgs',
                                           'chart_series', 'interpretation_markdown')}

    return {
        'symbol': sym,
        'buy_date': buy_date,
        'buy_price': _f(buy, 0),
        'quantity': qty,
        'thesis': h.get('thesis', ''),
        'note': h.get('note', ''),
        'last_date': str(last['date']),
        'close': _f(close, 0),
        'pnl_pct': _f(pnl_pct),
        'pnl_value': _f((close - buy) * qty, 0) if qty else None,
        'days_held': days_held,
        'sessions_held': sessions_held,
        'verdict': verdict,
        'verdict_tone': tone,
        'summary': summary,
        'technical': {
            'ma10': ma[10], 'ma20': ma[20], 'ma50': ma[50], 'ma200': ma[200],
            'ma_state': ma_state, 'rsi': _f(rsi, 1), 'adx': _f(adx, 1),
            'macd_hist': _f(macd_hist, 2), 'vol_ratio': _f(vol_ratio),
            'high_52w': _f(hi52, 0), 'low_52w': _f(lo52, 0),
            'ret_5d': _f(ret5), 'ret_20d': _f(ret20),
        },
        'atr': {
            'atr': _f(atr, 0), 'atr_pct': _f(atr_pct), 'atr_rank_1y': _f(atr_rank, 0),
            'atr_change_20d': _f(atr_change, 1), 'regime': vol_regime,
            'entry_atr': _f(entry_atr, 0), 'initial_stop': _f(init_stop, 0),
            'active_stop': _f(active_stop, 0),
            'risk_r': _f(risk_r, 0), 'chandelier': _f(chandelier, 0), 'trailing_stop': _f(trailing, 0),
            'highest_since_buy': _f(highest_since, 0), 'lowest_since_buy': _f(lowest_since, 0),
            'r_multiple': _f(r_mult), 'mfe_r': _f(mfe_r), 'mae_r': _f(mae_r),
            'dist_trailing_atr': _f(dist_trail_atr),
            'targets': [{'label': t['label'], 'price': _f(t['price'], 0), 'hit': t['hit']} for t in targets],
            'user_target': _f(user_target, 0) if user_target else None,
            'range_low': _f(close - atr, 0), 'range_high': _f(close + atr, 0),
        },
        'smc_levels': {
            'smc_stop': _f(smc_stop, 0) if smc_stop is not None else None,
            'targets': [{'label': t['label'], 'price': _f(t['price'], 0)} for t in smc_targets],
            'buy_side_liquidity': [{'price': _f(x['price'], 0), 'date': x['date'], 'equal': x['equal']} for x in bsl],
            'sell_side_liquidity': [{'price': _f(x['price'], 0), 'date': x['date'], 'equal': x['equal']} for x in ssl],
        },
        'smc': smc_out,
        'description_markdown': "\n".join(md),
    }


# ─────────────────────────────────────────────────────────────
# Entry point dùng trong pipeline
# ─────────────────────────────────────────────────────────────

def run_portfolio(fetch_fn, smc_fn=None, out_dir='output', portfolio_path=None):
    holdings = load_portfolio(portfolio_path)
    run_time_ict = datetime.utcnow() + timedelta(hours=7)
    result = {'generated_at': run_time_ict.strftime('%Y-%m-%d %H:%M') + ' (ICT)', 'holdings': [], 'errors': []}
    if not holdings:
        print("[PORTFOLIO] Không có mã nào trong portfolio.json")
    for h in holdings:
        print(f"[PORTFOLIO] {h['symbol']} (mua {h['buy_date']} @ {h['buy_price']:,.0f})")
        try:
            df = fetch_fn(h['symbol'], days=730)
            if df is None or len(df) == 0:
                result['errors'].append({'symbol': h['symbol'], 'error': 'Không lấy được dữ liệu giá'})
                continue
            a = analyze_holding(h, df, smc_fn)
            if a:
                result['holdings'].append(a)
            else:
                result['errors'].append({'symbol': h['symbol'], 'error': 'Không đủ dữ liệu lịch sử'})
        except Exception as e:
            print(f"  [PORTFOLIO] Lỗi {h['symbol']}: {e}")
            result['errors'].append({'symbol': h['symbol'], 'error': str(e)})

    # Tổng hợp danh mục
    tot_cost = sum(x['buy_price'] * x['quantity'] for x in result['holdings'] if x.get('quantity'))
    tot_val = sum(x['close'] * x['quantity'] for x in result['holdings'] if x.get('quantity'))
    result['totals'] = {
        'count': len(result['holdings']),
        'cost': round(tot_cost) if tot_cost else None,
        'value': round(tot_val) if tot_val else None,
        'pnl_pct': round((tot_val - tot_cost) / tot_cost * 100, 2) if tot_cost else None,
    }

    def _clean(o):
        if isinstance(o, dict):
            return {k: _clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [_clean(v) for v in o]
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating, float)):
            v = float(o)
            return None if math.isnan(v) or math.isinf(v) else v
        if isinstance(o, np.bool_):
            return bool(o)
        return o

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, 'portfolio.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(_clean(result), f, ensure_ascii=False, separators=(',', ':'))
    print(f"[PORTFOLIO] Đã ghi {path} ({len(result['holdings'])} mã)")
    return result
