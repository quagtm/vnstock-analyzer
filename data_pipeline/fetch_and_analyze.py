import os
import sys
import io
import json
import traceback
import time
from datetime import datetime, timedelta
import pandas as pd
import ta
import requests
from vnstock import Vnstock
from openai import OpenAI

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
        df = df.sort_values(by='time')
        
    close = df['close']
    high = df['high']
    low = df['low']
    volume = df['volume']
    
    # Moving Averages
    df['ma10']  = close.rolling(window=10).mean()
    df['ma20']  = close.rolling(window=20).mean()
    df['ma50']  = close.rolling(window=50).mean()
    df['ma100'] = close.rolling(window=100).mean()
    df['ma200'] = close.rolling(window=200).mean()

    # ROC — Rate of Change (động lượng thị trường)
    df['roc10']  = ta.momentum.ROCIndicator(close=close, window=10).roc()   # ngắn hạn
    df['roc20']  = ta.momentum.ROCIndicator(close=close, window=20).roc()   # trung hạn

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


# get_vn30_breadth đã được loại bỏ — dùng price_board (1 call) thay vì 30 calls lịch sử


def process_symbol(symbol):
    print(f"Processing {symbol}...")
    try:
        start_date = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
        end_date = datetime.now().strftime("%Y-%m-%d")
        
        stock = Vnstock().stock(symbol=symbol, source="VCI")
        df = stock.quote.history(start=start_date, end=end_date, interval="1D")
        
        if df is None or df.empty:
            print(f"No data for {symbol}")
            return None
            
        latest = calculate_technical_indicators(df)
        time_val = latest['time'] if 'time' in latest else "N/A"
        
        def safe_float(val):
            return float(val) if pd.notna(val) else 0.0
            
        # Tính MA20 của Volume
        vol_20 = df['volume'].rolling(20).mean().iloc[-1]
        current_vol = safe_float(latest.get('volume', 0))
        vol_diff = ((current_vol - vol_20) / vol_20) * 100 if vol_20 > 0 else 0
        vol_status = f"cao hơn {vol_diff:.2f}%" if vol_diff > 0 else f"thấp hơn {abs(vol_diff):.2f}%"
        
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
        
        # ── Sector mapping VN30 ──────────────────────────────────────
        SECTOR_MAP = {
            "ACB":"Ngân hàng","BID":"Ngân hàng","CTG":"Ngân hàng",
            "HDB":"Ngân hàng","LPB":"Ngân hàng","MBB":"Ngân hàng",
            "SHB":"Ngân hàng","SSB":"Ngân hàng","STB":"Ngân hàng",
            "TCB":"Ngân hàng","TPB":"Ngân hàng","VCB":"Ngân hàng",
            "VIB":"Ngân hàng","VPB":"Ngân hàng",
            "VHM":"Bất động sản","VIC":"Bất động sản",
            "VRE":"Bất động sản","VPL":"Bất động sản",
            "SSI":"Chứng khoán",
            "MWG":"Bán lẻ",
            "MSN":"Hàng tiêu dùng","SAB":"Hàng tiêu dùng","VNM":"Hàng tiêu dùng",
            "GAS":"Dầu khí","PLX":"Dầu khí",
            "HPG":"Thép","GVR":"Cao su",
            "FPT":"Công nghệ","VJC":"Hàng không","BSR":"Lọc hóa dầu",
        }

        # ── Fetch VN30 price board + market breadth + sector flow ─────
        top_movers_str = ""
        market_breadth_str = ""
        sector_flow_str = ""
        try:
            v_stock = Vnstock().stock(symbol='VNINDEX', source='VCI')
            vn30_symbols = v_stock.listing.symbols_by_group('VN30').tolist()
            board = v_stock.trading.price_board(symbols_list=vn30_symbols)
            board.columns = ['_'.join(col).strip() for col in board.columns.values]
            board['change_pc'] = (board['match_match_price'] - board['listing_ref_price']) / board['listing_ref_price'] * 100
            board = board.sort_values('change_pc', ascending=False)

            # Top movers — chỉ liệt kê thống kê, không phân tích lý do
            top5 = board.head(5)[['listing_symbol','change_pc']]
            bot5 = board.tail(5)[['listing_symbol','change_pc']]
            top_lines = ", ".join([f"{r['listing_symbol']} (+{r['change_pc']:.2f}%)" for _, r in top5.iterrows()])
            bot_lines  = ", ".join([f"{r['listing_symbol']} ({r['change_pc']:.2f}%)"  for _, r in bot5.iterrows()])
            top_movers_str = (
                f"**Top 5 tăng mạnh nhất (VN30):** {top_lines}\n"
                f"**Top 5 giảm mạnh nhất (VN30):** {bot_lines}"
            )

            # Market Breadth (VN30)
            n_up   = int((board['change_pc'] > 0).sum())
            n_down = int((board['change_pc'] < 0).sum())
            n_flat = int((board['change_pc'] == 0).sum())
            vn30_total = len(board)
            breadth_ratio = n_up / max(n_down, 1)
            if n_up > n_down:
                breadth_signal = "Thị trường TÍCH CỰC — Bên mua chiếm ưu thế"
            elif n_down > n_up:
                breadth_signal = "Thị trường TIÊU CỰC — Bên bán chiếm ưu thế"
            else:
                breadth_signal = "Thị trường CÂN BẰNG"
            market_breadth_str = (
                f"**Market Breadth VN30:** 🟢 Tăng: **{n_up}/{vn30_total}** | "
                f"🔴 Giảm: **{n_down}/{vn30_total}** | ➖ Đứng giá: **{n_flat}/{vn30_total}**\n"
                f"Tỷ lệ A/D: **{breadth_ratio:.2f}** — {breadth_signal}"
            )

            # Sector money flow
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
            print(f"  Market breadth: +{n_up}/-{n_down}/={n_flat}")
        except Exception as e:
            top_movers_str = "Dữ liệu VN30 hiện không khả dụng."
            print(f"Error fetching VN30 price board: {e}")

        combined_market_str = "\n\n".join(filter(None, [top_movers_str, market_breadth_str, sector_flow_str]))

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

        # ── 1 PROMPT DUY NHẤT cho cả 3 tabs — giảm từ 9 API calls xuống 3 ──
        keltner_pos = ('Vượt trên Upper → quá mua' if close > safe_float(latest.get('keltner_h', 0))
                       else ('Thủng dưới Lower → quá bán' if close < safe_float(latest.get('keltner_l', 0))
                             else 'Trong kênh Keltner'))
        vwap_pos = 'trên' if close > safe_float(latest.get('vwap', 0)) else 'dưới'

        prompt_all = f"""Bạn là hệ thống tổng hợp dữ liệu thị trường chứng khoán Việt Nam.
Chỉ trình bày số liệu được cung cấp. KHÔNG suy đoán nguyên nhân tăng/giảm của từng mã, KHÔNG đưa ra kịch bản/xác suất.

=== DỮ LIỆU {symbol} — {time_val} ===

[GIÁ & KHỐI LƯỢNG]
- Đóng cửa: {close:.2f} | Mở: {safe_float(latest['open']):.2f} | Cao: {safe_float(latest['high']):.2f} | Thấp: {safe_float(latest['low']):.2f}
- Khối lượng khớp lệnh: {current_vol/1_000_000:.3f} triệu CP — {vol_status} so với TB 20 phiên

[XU HƯỚNG MA & ĐỘNG LƯỢNG]
{trend_assessment}
- ROC: {roc_str} → {roc_signal}
- ADX: {safe_float(latest['adx']):.2f} (>25: mạnh | 15-25: TB | <15: đi ngang)
- ATR: {safe_float(latest['atr']):.2f} điểm/phiên
- Keltner: Upper {safe_float(latest['keltner_h']):.2f} / Lower {safe_float(latest['keltner_l']):.2f} → {keltner_pos}

[DÒNG TIỀN]
- CMF: {safe_float(latest['cmf']):.4f} (>0: dòng tiền vào | <0: dòng tiền ra)
- VWAP: {safe_float(latest['vwap']):.2f} — Giá đang {vwap_pos} VWAP
- OBV: {safe_float(latest['obv']):.0f}

[VN30 & THỊ TRƯỜNG]
{combined_market_str}

=== YÊU CẦU OUTPUT ===
Viết 6 section Markdown theo đúng tiêu đề sau (KHÔNG thêm tiêu đề khác):

## [TAB:GENERAL]
### 1. Diễn biến phiên giao dịch
Giá đóng cửa, biến động so tham chiếu, khối lượng (triệu CP) vs TB 20 phiên.
### 2. Xu hướng & Động lượng
Tóm tắt nhận định 5 MAs và ROC theo số liệu đã cho.
### 3. Thống kê Cổ phiếu & Nhóm ngành
Top 5 tăng/giảm kèm % | Ngành thu hút/rút tiền kèm % TB | % CP trên MA20/50/200.
### 4. Market Breadth
Số mã tăng/giảm/đứng giá VN30, tỷ lệ A/D.

## [TAB:VOLUME]
### 1. Thống kê Chỉ báo Khối lượng
Bảng CMF/VWAP/OBV với giá trị thực và nhận định ngắn.
### 2. Nhận định Dòng tiền
Dòng tiền ròng vào/ra? Áp lực mua/bán vs VWAP? Dấu hiệu phân phối?

## [TAB:TREND]
### 1. Thống kê Xu hướng & Động lượng
Bảng: MA positions, ROC, ADX, ATR, Keltner.
### 2. Nhận định Rủi ro
Sức mạnh xu hướng, biến động, vùng giá quan trọng tiếp theo.
"""

        ai_response = ask_ai(prompt_all,
            "Bạn là hệ thống tổng hợp dữ liệu thị trường chứng khoán. "
            "Trình bày đúng số liệu, không thêm định tính, không suy đoán nguyên nhân, "
            "không kịch bản/xác suất. Output phải có đúng 3 block ## [TAB:GENERAL], ## [TAB:VOLUME], ## [TAB:TREND].")

        def parse_tab(response, tag):
            """Tách nội dung theo tag ## [TAB:XXX]"""
            if not response:
                return None
            import re
            pattern = rf'## \[TAB:{tag}\](.*?)(?=## \[TAB:|$)'
            match = re.search(pattern, response, re.DOTALL)
            return match.group(1).strip() if match else None

        if ai_response:
            general_markdown = parse_tab(ai_response, "GENERAL") or generate_rule_based_analysis(**rb_args, tab_type="general")
            volume_markdown  = parse_tab(ai_response, "VOLUME")  or generate_rule_based_analysis(**rb_args, tab_type="volume")
            trend_markdown   = parse_tab(ai_response, "TREND")   or generate_rule_based_analysis(**rb_args, tab_type="trend")
        else:
            general_markdown = generate_rule_based_analysis(**rb_args, tab_type="general")
            volume_markdown  = generate_rule_based_analysis(**rb_args, tab_type="volume")
            trend_markdown   = generate_rule_based_analysis(**rb_args, tab_type="trend")

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
            "volume_markdown": volume_markdown,
            "trend_markdown": trend_markdown
        }

        
    except Exception as e:
        print(f"Error processing {symbol}: {e}")
        traceback.print_exc()
        return None

def main():
    symbols = ["VNINDEX", "VN30", "VN100"]
    all_data = {}

    for sym in symbols:
        data = process_symbol(sym)
        if data:
            all_data[sym] = data
            
    if not all_data:
        print("No data collected!")
        sys.exit(1)
        
    out_dir = "output"
    os.makedirs(out_dir, exist_ok=True)
    with open(f"{out_dir}/data.json", "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    print(f"Successfully generated {out_dir}/data.json")

if __name__ == "__main__":
    main()
