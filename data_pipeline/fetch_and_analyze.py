import os
import sys
import io
import json
import traceback
from datetime import datetime, timedelta
import pandas as pd
import ta
import requests
from vnstock import Vnstock
from openai import OpenAI

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Ensure we have API key
api_key = os.environ.get("OPENROUTER_API_KEY")
if not api_key:
    print("Error: OPENROUTER_API_KEY environment variable not set.")
    sys.exit(1)

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)

def calculate_technical_indicators(df):
    if df.empty:
        return df
    
    # Ensure time is datetime and sorted
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'])
        df = df.sort_values(by='time')
    
    # MAs
    df['ma5'] = ta.trend.sma_indicator(df['close'], window=5)
    df['ma10'] = ta.trend.sma_indicator(df['close'], window=10)
    df['ma20'] = ta.trend.sma_indicator(df['close'], window=20)
    df['ma50'] = ta.trend.sma_indicator(df['close'], window=50)
    df['ma100'] = ta.trend.sma_indicator(df['close'], window=100)
    df['ma200'] = ta.trend.sma_indicator(df['close'], window=200)
    
    # Bollinger Bands
    df['bb_upper'] = ta.volatility.bollinger_hband(df['close'], window=20, window_dev=2)
    df['bb_lower'] = ta.volatility.bollinger_lband(df['close'], window=20, window_dev=2)
    df['bb_middle'] = df['ma20']
    
    # Pivot
    df['pivot'] = (df['high'] + df['low'] + df['close']) / 3
    df['r1'] = (2 * df['pivot']) - df['low']
    df['s1'] = (2 * df['pivot']) - df['high']
    df['r2'] = df['pivot'] + (df['high'] - df['low'])
    df['s2'] = df['pivot'] - (df['high'] - df['low'])
    
    # Fibo (simple max high min low of last 252 days)
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
        
    return df.iloc[-1]

import time

def ask_openrouter(prompt):
    models = [
        "google/gemma-2-9b-it:free",
        "meta-llama/llama-3.1-8b-instruct:free",
        "microsoft/phi-3-mini-128k-instruct:free",
        "qwen/qwen-2-7b-instruct:free"
    ]
    
    last_error = ""
    for model_name in models:
        try:
            print(f"  -> Trying model: {model_name}")
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "Bạn là chuyên gia phân tích chứng khoán Việt Nam xuất sắc. Hãy phân tích dựa trên số liệu được cung cấp với luận điểm nhân quả (nguyên nhân - kết quả) rõ ràng."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=2000
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"  -> Failed with {model_name}: {str(e)}")
            last_error = str(e)
            time.sleep(3) # Tránh bị dính lỗi giới hạn nhịp độ (Rate Limit) của OpenRouter
            continue
            
    return f"Lỗi khi gọi OpenRouter API (Tất cả mô hình đều bận): {last_error}"

def process_symbol(symbol):
    print(f"Processing {symbol}...")
    try:
        # Lấy dữ liệu 2 năm để tính MA200
        start_date = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
        end_date = datetime.now().strftime("%Y-%m-%d")
        
        stock = Vnstock().stock(symbol=symbol, source="VCI")
        df = stock.quote.history(start=start_date, end=end_date, interval="1D")
        
        if df is None or df.empty:
            print(f"No data for {symbol}")
            return None
            
        latest = calculate_technical_indicators(df)
        
        # Lấy thông tin thời gian (cột time hoặc index tùy vào output của vnstock)
        time_val = latest['time'] if 'time' in latest else "N/A"
        
        def safe_float(val):
            return float(val) if pd.notna(val) else 0.0
        
        # Tạo prompt
        prompt = f"""
Hãy phân tích chỉ số {symbol} cho ngày giao dịch gần nhất ({time_val}).
Dữ liệu hiện tại:
- Đóng cửa: {safe_float(latest['close']):.2f}
- Mở cửa: {safe_float(latest['open']):.2f}, Cao nhất: {safe_float(latest['high']):.2f}, Thấp nhất: {safe_float(latest['low']):.2f}
- Khối lượng: {safe_float(latest.get('volume', 0)):.0f}

Chỉ báo kỹ thuật:
- MA5: {safe_float(latest['ma5']):.2f}, MA10: {safe_float(latest['ma10']):.2f}, MA20: {safe_float(latest['ma20']):.2f}
- MA50: {safe_float(latest['ma50']):.2f}, MA100: {safe_float(latest['ma100']):.2f}, MA200: {safe_float(latest['ma200']):.2f}
- Bollinger Bands: Upper {safe_float(latest['bb_upper']):.2f}, Middle {safe_float(latest['bb_middle']):.2f}, Lower {safe_float(latest['bb_lower']):.2f}
- Pivot: {safe_float(latest['pivot']):.2f}, Kháng cự (R1, R2): {safe_float(latest['r1']):.2f}, {safe_float(latest['r2']):.2f}, Hỗ trợ (S1, S2): {safe_float(latest['s1']):.2f}, {safe_float(latest['s2']):.2f}
- Fibonacci Retracement 1 năm: 0.236 ({safe_float(latest['fibo_236']):.2f}), 0.382 ({safe_float(latest['fibo_382']):.2f}), 0.5 ({safe_float(latest['fibo_500']):.2f}), 0.618 ({safe_float(latest['fibo_618']):.2f})

Yêu cầu trả về định dạng Markdown, chia làm 3 phần như sau:
### 1. Diễn biến và Đóng góp
Mô tả thay đổi, tăng giảm (Dựa trên giá đóng/mở và khối lượng). Phân tích các ngưỡng Kháng cự hỗ trợ hiện tại theo BB, Pivot và Fibo.
(Ghi chú quan trọng: Hãy tự suy luận logic từ dữ liệu vĩ mô và tính chất vốn hóa của {symbol} để chỉ ra Nhóm ngành dẫn dắt, nhóm ngành đi lùi, Top 3 cổ phiếu ảnh hưởng tích cực, top 3 cổ phiếu ảnh hưởng tiêu cực trong nhịp thị trường này).

### 2. Phân tích Hành động giá, Khối lượng và Xu hướng
Phân tích chi tiết hành động giá khối lượng và xu hướng thị trường theo 3 khung thời gian: ngắn hạn (MA5, 10, 20), trung hạn (MA50), dài hạn (MA100, 200). Đưa ra luận điểm rõ ràng (Nguyên nhân - Kết quả).

### 3. Kịch bản Xác suất Thị trường
Kết hợp các chỉ báo kỹ thuật trên, đưa ra 2 kịch bản (Tích cực và Tiêu cực) và gán xác suất (%), kèm luận điểm nguyên nhân - kết quả rõ ràng tại sao lại có xác suất đó.
"""
        
        analysis = ask_openrouter(prompt)
        
        return {
            "symbol": symbol,
            "date": str(time_val),
            "close": safe_float(latest['close']),
            "volume": safe_float(latest.get('volume', 0)),
            "technical": {
                "ma20": safe_float(latest['ma20']),
                "pivot": safe_float(latest['pivot']),
            },
            "analysis_markdown": analysis
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
            
    # Lưu vào public folder của frontend
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "public")
    os.makedirs(frontend_dir, exist_ok=True)
    
    out_file = os.path.join(frontend_dir, "data.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print(f"Successfully saved data to {out_file}")

if __name__ == "__main__":
    main()
