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

# Setup OpenRouter with fallback
api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("GROQ_API_KEY")
if not api_key:
    print("WARNING: OPENROUTER_API_KEY not found. Analysis will fail.")

client = OpenAI(
  base_url="https://openrouter.ai/api/v1",
  api_key=api_key or "dummy_key",
)

def ask_ai(prompt, system_prompt="Bạn là chuyên gia phân tích chứng khoán."):
    if not api_key:
        return None  # Signal to use rule-based fallback
        
    models_to_try = [
        "google/gemini-2.0-flash-exp:free",
        "meta-llama/llama-3.3-70b-instruct:free",
        "qwen/qwen-2.5-72b-instruct:free",
        "mistralai/mistral-7b-instruct:free",
        "google/gemma-3-27b-it:free",
    ]
    
    for i, model in enumerate(models_to_try):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=900
            )
            print(f"  ✓ Success with model: {model}")
            return response.choices[0].message.content
        except Exception as e:
            wait = 3 + i * 2  # Tăng dần: 3s, 5s, 7s, 9s...
            print(f"  ✗ Error with model {model}: {e}. Retrying in {wait}s...")
            time.sleep(wait)
            continue
            
    return None  # Signal to use rule-based fallback


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
        sentiment = "Tích cực" if change >= 0 else "Tiêu cực"
        scenario_bull_pct = 55 if cmf > 0 and change >= 0 else (45 if change >= 0 else 35)
        scenario_bear_pct = 100 - scenario_bull_pct
        top_info = top_movers_str if "FACT" in top_movers_str else ""
        
        return f"""### 1. Diễn biến và Đóng góp

{direction_emoji} **{symbol}** đóng cửa tại **{close:.2f}** điểm, **{direction} {abs(change):.2f} điểm ({abs(change_pc):.2f}%)** so với phiên mở cửa {open_price:.2f}.

Khối lượng giao dịch đạt **{current_vol:,.0f} CP** — {vol_status} so với trung bình 20 phiên, cho thấy {"sự tham gia tích cực của dòng tiền" if vol_diff > 5 else ("áp lực giao dịch vừa phải" if vol_diff > -5 else "dòng tiền đang thận trọng, rút lui")}.

**Vùng Hỗ trợ gần nhất:** {support_str}
**Vùng Kháng cự gần nhất:** {resist_str}

{top_info}

### 2. Kịch bản Xác suất

**🟢 Kịch bản Tích cực ({scenario_bull_pct}%):** {"Giá đang giữ được vùng hỗ trợ MA" if support_levels else "Nếu lực cầu hồi phục"}, có thể kiểm tra lại vùng kháng cự {resist_levels[0][1]:.2f} ({resist_levels[0][0]}) nếu dòng tiền duy trì. Khối lượng {"cao hơn TB" if vol_diff > 0 else "cần cải thiện"} là tín hiệu cần theo dõi.

**🔴 Kịch bản Tiêu cực ({scenario_bear_pct}%):** Nếu {"mất vùng hỗ trợ " + support_levels[-1][0] + " (" + f"{support_levels[-1][1]:.2f}" + ")" if support_levels else "áp lực bán tiếp tục"}, chỉ số có thể điều chỉnh sâu hơn xuống vùng {low:.2f}–{(close * 0.97):.2f}. Cần chú ý nếu khối lượng tăng đột biến trong phiên giảm.

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
        
        # Lấy Top 3 cổ phiếu VN30 làm fact
        top_movers_str = ""
        try:
            v_stock = Vnstock().stock(symbol='VNINDEX', source='VCI')
            vn30_symbols = v_stock.listing.symbols_by_group('VN30').tolist()
            board = v_stock.trading.price_board(symbols_list=vn30_symbols)
            board.columns = ['_'.join(col).strip() for col in board.columns.values]
            board['change_pc'] = (board['match_match_price'] - board['listing_ref_price']) / board['listing_ref_price'] * 100
            board = board.sort_values('change_pc', ascending=False)
            top_3 = board.head(3)['listing_symbol'].tolist()
            bot_3 = board.tail(3)['listing_symbol'].tolist()
            top_movers_str = f"SỐ LIỆU THỰC TẾ TRONG VN30 (FACT): Top 3 tăng mạnh nhất là {', '.join(top_3)}. Top 3 giảm mạnh nhất là {', '.join(bot_3)}. (Hãy dùng danh sách này để suy ra Nhóm ngành dẫn dắt/đi lùi, TUYỆT ĐỐI KHÔNG tự suy đoán cổ phiếu khác)."
        except Exception as e:
            top_movers_str = "Dữ liệu Top cổ phiếu hiện không khả dụng."
            print(f"Error fetching VN30 price board: {e}")

        # Shared fallback args
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
            top_movers_str=top_movers_str, time_val=time_val
        )

        # 1. Prompt General
        prompt_general = f"""
Hãy phân tích TỔNG QUAN chỉ số {symbol} cho ngày giao dịch gần nhất ({time_val}).
Dữ liệu hiện tại:
- Đóng cửa: {close:.2f} (Mở: {safe_float(latest['open']):.2f}, Cao: {safe_float(latest['high']):.2f}, Thấp: {safe_float(latest['low']):.2f})
- Khối lượng giao dịch: {current_vol:.0f} CP ({vol_status} so với trung bình 20 phiên).

Khoảng cách tới Hỗ trợ / Kháng cự MAs (từ gần nhất đến xa nhất): {ma_str}

{top_movers_str}

Yêu cầu trả về định dạng Markdown, chia làm 2 phần:
### 1. Diễn biến và Đóng góp
Dựa VÀO SỐ LIỆU FACT Ở TRÊN để chỉ ra Nhóm ngành dẫn dắt và đi lùi (suy luận logic từ danh sách cổ phiếu thực tế).
### 2. Kịch bản Xác suất
Đưa ra 2 kịch bản (Tích cực và Tiêu cực) và gán xác suất (%), kèm luận điểm.
"""
        ai_general = ask_ai(prompt_general, "Bạn là chuyên gia Vĩ mô & Tổng quan thị trường chứng khoán Việt Nam. Bạn luôn dựa vào FACT được cung cấp, không bịa số liệu hay tự đoán cổ phiếu.")
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
