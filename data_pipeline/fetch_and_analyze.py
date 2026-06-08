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

# Ensure we have API key
api_key = os.environ.get("GROQ_API_KEY")
if not api_key:
    print("Error: GROQ_API_KEY environment variable not set.")
    sys.exit(1)

client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)

def calculate_technical_indicators(df):
    if df.empty:
        return df
    
    # Ensure time is datetime and sorted
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'])
        df = df.sort_values(by='time')
        
    close = df['close']
    high = df['high']
    low = df['low']
    volume = df['volume']
    
    # MAs
    df['ma5'] = ta.trend.sma_indicator(close, window=5)
    df['ma10'] = ta.trend.sma_indicator(close, window=10)
    df['ma20'] = ta.trend.sma_indicator(close, window=20)
    df['ma50'] = ta.trend.sma_indicator(close, window=50)
    df['ma100'] = ta.trend.sma_indicator(close, window=100)
    df['ma200'] = ta.trend.sma_indicator(close, window=200)
    
    # Bollinger Bands
    df['bb_upper'] = ta.volatility.bollinger_hband(close, window=20, window_dev=2)
    df['bb_lower'] = ta.volatility.bollinger_lband(close, window=20, window_dev=2)
    df['bb_middle'] = df['ma20']
    
    # Pivot
    df['pivot'] = (high + low + close) / 3
    df['r1'] = (2 * df['pivot']) - low
    df['s1'] = (2 * df['pivot']) - high
    df['r2'] = df['pivot'] + (high - low)
    df['s2'] = df['pivot'] - (high - low)
    
    # Fibo
    last_year = df.tail(252)
    if not last_year.empty:
        max_high = last_year['high'].max()
        min_low = last_year['low'].min()
        diff = max_high - min_low
        df['fibo_236'] = max_high - 0.236 * diff
        df['fibo_382'] = max_high - 0.382 * diff
        df['fibo_500'] = max_high - 0.5 * diff
        df['fibo_618'] = max_high - 0.618 * diff
    else:
        df['fibo_236'] = df['fibo_382'] = df['fibo_500'] = df['fibo_618'] = None
        
    # NEW: Volume Indicators
    df['cmf'] = ta.volume.ChaikinMoneyFlowIndicator(high=high, low=low, close=close, volume=volume, window=20).chaikin_money_flow()
    df['vwap'] = ta.volume.VolumeWeightedAveragePrice(high=high, low=low, close=close, volume=volume, window=14).volume_weighted_average_price()
    df['mfi'] = ta.volume.MFIIndicator(high=high, low=low, close=close, volume=volume, window=14).money_flow_index()
    
    # NEW: Trend & Volatility Indicators
    df['adx'] = ta.trend.ADXIndicator(high=high, low=low, close=close, window=14).adx()
    df['atr'] = ta.volatility.AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()
    keltner = ta.volatility.KeltnerChannel(high=high, low=low, close=close, window=20, window_atr=10)
    df['keltner_h'] = keltner.keltner_channel_hband()
    df['keltner_l'] = keltner.keltner_channel_lband()
        
    return df.iloc[-1]

def ask_groq(prompt, system_prompt="Bạn là chuyên gia phân tích chứng khoán Việt Nam xuất sắc. Hãy phân tích dựa trên số liệu được cung cấp với luận điểm nhân quả rõ ràng."):
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1500
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Lỗi khi gọi Groq API: {str(e)}"

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
            
        # 1. Prompt General
        prompt_general = f"""
Hãy phân tích TỔNG QUAN chỉ số {symbol} cho ngày giao dịch gần nhất ({time_val}).
Dữ liệu hiện tại:
- Đóng cửa: {safe_float(latest['close']):.2f} (Mở: {safe_float(latest['open']):.2f}, Cao: {safe_float(latest['high']):.2f}, Thấp: {safe_float(latest['low']):.2f})
- Khối lượng: {safe_float(latest.get('volume', 0)):.0f}

Chỉ báo hỗ trợ:
- MA20: {safe_float(latest['ma20']):.2f}, MA50: {safe_float(latest['ma50']):.2f}, MA200: {safe_float(latest['ma200']):.2f}
- Bollinger Bands: Upper {safe_float(latest['bb_upper']):.2f}, Middle {safe_float(latest['bb_middle']):.2f}, Lower {safe_float(latest['bb_lower']):.2f}
- Pivot: {safe_float(latest['pivot']):.2f}, Fibo 0.5: {safe_float(latest['fibo_500']):.2f}

Yêu cầu trả về định dạng Markdown, chia làm 2 phần:
### 1. Diễn biến và Đóng góp
Mô tả thay đổi, tăng giảm. Chỉ ra Nhóm ngành dẫn dắt, nhóm ngành đi lùi, Top 3 cổ phiếu ảnh hưởng tích cực/tiêu cực (suy luận logic từ vĩ mô).
### 2. Kịch bản Xác suất
Đưa ra 2 kịch bản (Tích cực và Tiêu cực) và gán xác suất (%), kèm luận điểm.
"""
        general_markdown = ask_groq(prompt_general, "Bạn là chuyên gia Vĩ mô & Tổng quan thị trường chứng khoán Việt Nam.")
        time.sleep(2) # rate limit safe
        
        # 2. Prompt Volume
        prompt_volume = f"""
Hãy phân tích DÒNG TIỀN VÀ KHỐI LƯỢNG của {symbol} ngày ({time_val}).
Giá đóng cửa: {safe_float(latest['close']):.2f}, Khối lượng: {safe_float(latest.get('volume', 0)):.0f}.

Chỉ báo Khối lượng:
- Chaikin Money Flow (CMF): {safe_float(latest['cmf']):.4f} (Dòng tiền ra/vào)
- VWAP: {safe_float(latest['vwap']):.2f} (Giá trung bình theo khối lượng)
- Money Flow Index (MFI): {safe_float(latest['mfi']):.4f}

Yêu cầu trả về định dạng Markdown:
### 1. Thống kê Khối lượng
Phân tích chi tiết ý nghĩa của 3 chỉ số CMF, VWAP, MFI ở thời điểm hiện tại.
### 2. Nhận định Trạng thái Dòng tiền
Tổng hợp lại, dòng tiền đang mua gom (tích lũy) hay phân phối? Phe mua hay phe bán đang kiểm soát?
"""
        volume_markdown = ask_groq(prompt_volume, "Bạn là chuyên gia Phân tích Khối lượng & Dòng tiền (VSA) chứng khoán.")
        time.sleep(2)
        
        # 3. Prompt Trend
        prompt_trend = f"""
Hãy phân tích XU HƯỚNG VÀ BIẾN ĐỘNG của {symbol} ngày ({time_val}).
Giá đóng cửa: {safe_float(latest['close']):.2f}.

Chỉ báo Xu hướng & Biến động:
- ADX: {safe_float(latest['adx']):.2f} (Sức mạnh xu hướng, >25 là mạnh)
- ATR: {safe_float(latest['atr']):.2f} (Mức độ biến động)
- Keltner Channels: Upper {safe_float(latest['keltner_h']):.2f}, Lower {safe_float(latest['keltner_l']):.2f}

Yêu cầu trả về định dạng Markdown:
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
            "close": safe_float(latest['close']),
            "volume": safe_float(latest.get('volume', 0)),
            "technical": {
                "ma20": safe_float(latest['ma20']),
                "pivot": safe_float(latest['pivot']),
                "cmf": safe_float(latest['cmf']),
                "adx": safe_float(latest['adx'])
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
    data = {}
    for sym in symbols:
        res = process_symbol(sym)
        if res:
            data[sym] = res
            
    if not data:
        print("No data collected!")
        sys.exit(1)
            
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "public")
    os.makedirs(frontend_dir, exist_ok=True)
    out_file = os.path.join(frontend_dir, "data.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print(f"Successfully saved data to {out_file}")

if __name__ == "__main__":
    main()
