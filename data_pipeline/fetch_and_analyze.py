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

def ask_groq(prompt, system_prompt="Bạn là chuyên gia phân tích chứng khoán."):
    if not api_key:
        return "API Key không hợp lệ."
        
    models_to_try = [
        "meta-llama/llama-3.3-70b-instruct:free",
        "mistralai/mistral-7b-instruct:free",
        "google/gemini-2.5-pro"
    ]
    
    for model in models_to_try:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=800
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"Error with model {model}: {e}")
            time.sleep(2)
            continue
            
    return "Hệ thống AI hiện đang quá tải. Vui lòng thử lại sau."

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
        general_markdown = ask_groq(prompt_general, "Bạn là chuyên gia Vĩ mô & Tổng quan thị trường chứng khoán Việt Nam. Bạn luôn dựa vào FACT được cung cấp, không bịaa số liệu hay tự đoán cổ phiếu.")
        time.sleep(2) # rate limit safe
        
        # 2. Prompt Volume
        prompt_volume = f"""
Hãy phân tích DÒNG TIỀN VÀ KHỐI LƯỢNG của {symbol} ngày ({time_val}).
Giá đóng cửa: {close:.2f}, Khối lượng: {current_vol:.0f} CP ({vol_status} so với TB 20 phiên).

Các chỉ báo dòng tiền chuyên sâu:
- Chaikin Money Flow (CMF): {safe_float(latest['cmf']):.4f} (Đo lường áp lực Mua/Bán)
- VWAP: {safe_float(latest['vwap']):.2f} (Giá trung bình gia quyền khối lượng, nếu Giá > VWAP là Tích cực)
- Klinger/OBV: {safe_float(latest['obv']):.0f} (Tích lũy phân phối)

Yêu cầu trả về định dạng Markdown, chia làm 2 phần:
### 1. Thống kê Chỉ báo Khối lượng
Phân tích chi tiết ý nghĩa của 3 chỉ báo trên đối với trạng thái hiện tại.
### 2. Nhận định Dòng tiền chung
Dòng tiền đang vào hay rút ra? Do tổ chức hay cá nhân? Có rủi ro phân phối không?
"""
        volume_markdown = ask_groq(prompt_volume, "Bạn là chuyên gia Phân tích Dòng tiền & Khối lượng chứng khoán.")
        time.sleep(2)
        
        # 3. Prompt Trend
        prompt_trend = f"""
Hãy phân tích XU HƯỚNG VÀ BIẾN ĐỘNG của {symbol} ngày ({time_val}).
Giá đóng cửa: {close:.2f}.
Khoảng cách tới MAs: {ma_str}

Các chỉ báo biến động chuyên sâu:
- ADX: {safe_float(latest['adx']):.2f} (Sức mạnh xu hướng, > 25 là xu hướng rõ ràng)
- ATR: {safe_float(latest['atr']):.2f} (Mức độ biến động trung bình)
- Keltner Channels: Upper {safe_float(latest['keltner_h']):.2f}, Lower {safe_float(latest['keltner_l']):.2f}. (Nếu giá vượt Upper là quá mua, thủng Lower là quá bán).

Yêu cầu trả về định dạng Markdown, chia làm 2 phần:
### 1. Thống kê Xu hướng
Phân tích mức độ biến động (ATR), sức mạnh xu hướng (ADX) và vị trí giá so với kênh Keltner.
### 2. Nhận định Rủi ro & Hành động
Đánh giá xu hướng hiện tại là Tăng/Giảm/Đi ngang? Rủi ro hiện tại cao hay thấp? Khuyến nghị hành động giá tiếp theo.
"""
        trend_markdown = ask_groq(prompt_trend, "Bạn là chuyên gia Phân tích Kỹ thuật & Quản trị rủi ro chứng khoán.")
        time.sleep(2)

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
        
    os.makedirs("public", exist_ok=True)
    with open("public/data.json", "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    print("Successfully generated public/data.json")

if __name__ == "__main__":
    main()
