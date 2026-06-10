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
        try:
            print(f"  → Calling DeepSeek [{model}]...")
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
            wait = 5 + i * 5
            print(f"  ✗ DeepSeek [{model}] error: {e}. Wait {wait}s...")
            time.sleep(wait)
            continue

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
    
    # Xu hướng
    df['ma10'] = close.rolling(window=10).mean()
    df['ma20'] = close.rolling(window=20).mean()
    df['ma50'] = close.rolling(window=50).mean()
    df['ma200'] = close.rolling(window=200).mean()
    
    # Bollinger Bands
    indicator_bb = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
    df['bb_upper'] = indicator_bb.bollinger_hband()
    df['bb_middle'] = indicator_bb.bollinger_mavg()
    df['bb_lower'] = indicator_bb.bollinger_lband()
    
    # Pivot Points (Sử dụng High, Low, Close của cây nến liền trước)
    df['prev_high'] = high.shift(1)
    df['prev_low'] = low.shift(1)
    df['prev_close'] = close.shift(1)
    df['pivot'] = (df['prev_high'] + df['prev_low'] + df['prev_close']) / 3
    
    # Khối lượng
    df['cmf'] = ta.volume.ChaikinMoneyFlowIndicator(high=high, low=low, close=close, volume=volume).chaikin_money_flow()
    df['vwap'] = ta.volume.VolumeWeightedAveragePrice(high=high, low=low, close=close, volume=volume).volume_weighted_average_price()
    
    # Klinger Oscillator requires a workaround if the standard one doesn't exist.
    try:
        # Tạm thay thế Klinger bằng OBV vì Klinger đôi khi thiếu trong các phiên bản ta cũ
        df['obv'] = ta.volume.OnBalanceVolumeIndicator(close=close, volume=volume).on_balance_volume()
    except:
        df['obv'] = 0
        
    # Xu hướng / Biến động
    df['adx'] = ta.trend.ADXIndicator(high=high, low=low, close=close).adx()
    df['atr'] = ta.volatility.AverageTrueRange(high=high, low=low, close=close).average_true_range()
    
    indicator_keltner = ta.volatility.KeltnerChannel(high=high, low=low, close=close)
    df['keltner_h'] = indicator_keltner.keltner_channel_hband()
    df['keltner_l'] = indicator_keltner.keltner_channel_lband()
    
    return df.iloc[-1]

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
            ("MA10", safe_float(latest.get('ma10', 0))),
            ("MA20", safe_float(latest.get('ma20', 0))),
            ("MA50", safe_float(latest.get('ma50', 0))),
            ("MA200", safe_float(latest.get('ma200', 0)))
        ]
        mas_sorted = sorted([m for m in mas if m[1] > 0], key=lambda x: abs(close - x[1]))
        ma_str = ", ".join([f"{name} ({eval_ma(close, val)} tại {val:.2f})" for name, val in mas_sorted])
        
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

        # Gộp tất cả fact data vào top_movers_str cho rule-based fallback
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

        # 1. Prompt General — thuần thống kê, không kịch bản/xác suất
        prompt_general = f"""Tổng hợp dữ liệu phiên giao dịch {symbol} ngày {time_val}.

SỐ LIỆU THỰC TẾ:
- Đóng cửa: {close:.2f} | Mở: {safe_float(latest['open']):.2f} | Cao: {safe_float(latest['high']):.2f} | Thấp: {safe_float(latest['low']):.2f}
- Khối lượng: {current_vol:,.0f} CP — {vol_status} so với TB 20 phiên
- Các mức MA (từ gần đến xa): {ma_str}

{top_movers_str}

{market_breadth_str}

{sector_flow_str}

Yêu cầu: Viết bài tổng hợp Markdown gồm 3 phần dưới đây. CHỈ dùng số liệu được cung cấp ở trên, KHÔNG thêm phân tích nguyên nhân tăng/giảm của từng mã, KHÔNG đưa ra kịch bản hay xác suất.

### 1. Diễn biến phiên giao dịch
Tóm tắt ngắn gọn: giá đóng cửa, biến động so với tham chiếu, khối lượng so với TB 20 phiên, vị trí so với các ngưỡng MA.

### 2. Thống kê Cổ phiếu & Nhóm ngành
- Liệt kê Top 5 tăng/giảm mạnh nhất kèm đúng % thay đổi (chỉ liệt kê, không bình luận nguyên nhân)
- Liệt kê nhóm ngành thu hút / bị rút dòng tiền kèm % trung bình

### 3. Market Breadth
- Số mã tăng/giảm/đứng giá trong VN30 và tỷ lệ A/D, đánh giá 1 câu
"""
        ai_general = ask_ai(prompt_general, "Bạn là hệ thống tổng hợp dữ liệu thị trường chứng khoán. Trình bày đúng số liệu được cung cấp. Không thêm phân tích định tính, không suy đoán nguyên nhân, không đưa ra kịch bản hay xác suất.")
        general_markdown = ai_general if ai_general else generate_rule_based_analysis(**rb_args, tab_type="general")
        time.sleep(3)
        
        # 2. Prompt Volume
        prompt_volume = f"""
Hãy phân tích DÒNG TIỀN VÀ KHỐI LƯỢNG của {symbol} ngày ({time_val}).
Giá đóng cửa: {close:.2f}, Khối lượng: {current_vol:.0f} CP ({vol_status} so với TB 20 phiên).

Các chỉ báo dòng tiền chuyên sâu:
- Chaikin Money Flow (CMF): {safe_float(latest['cmf']):.4f} (Đo lường áp lực Mua/Bán)
- VWAP: {safe_float(latest['vwap']):.2f} (Giá trung bình gia quyền khối lượng, nếu Giá > VWAP là Tích cực)
- OBV: {safe_float(latest['obv']):.0f} (Tích lũy phân phối)

Yêu cầu trả về định dạng Markdown, chia làm 2 phần:
### 1. Thống kê Chỉ báo Khối lượng
Phân tích chi tiết ý nghĩa của 3 chỉ báo trên đối với trạng thái hiện tại.
### 2. Nhận định Dòng tiền chung
Dòng tiền đang vào hay rút ra? Do tổ chức hay cá nhân? Có rủi ro phân phối không?
"""
        ai_volume = ask_ai(prompt_volume, "Bạn là chuyên gia Phân tích Dòng tiền & Khối lượng chứng khoán.")
        volume_markdown = ai_volume if ai_volume else generate_rule_based_analysis(**rb_args, tab_type="volume")
        time.sleep(3)
        
        # 3. Prompt Trend
        prompt_trend = f"""
Hãy phân tích XU HƯỚNG VÀ BIẾN ĐỘNG của {symbol} ngày ({time_val}).
Giá đóng cửa: {close:.2f}.
Khoảng cách tới MAs: {ma_str}

Các chỉ báo biến động chuyên sâu:
- ADX: {safe_float(latest['adx']):.2f} (Sức mạnh xu hướng, > 25 là xu hướng rõ ràng)
- ATR: {safe_float(latest['atr']):.2f} (Mức độ biến động trung bình)
- Keltner Channels: Upper {safe_float(latest['keltner_h']):.2f}, Lower {safe_float(latest['keltner_l']):.2f}.

Yêu cầu trả về định dạng Markdown, chia làm 2 phần:
### 1. Thống kê Xu hướng
### 2. Nhận định Rủi ro & Hành động
"""
        ai_trend = ask_ai(prompt_trend, "Bạn là chuyên gia Phân tích Kỹ thuật & Quản trị rủi ro chứng khoán.")
        trend_markdown = ai_trend if ai_trend else generate_rule_based_analysis(**rb_args, tab_type="trend")
        time.sleep(3)

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
