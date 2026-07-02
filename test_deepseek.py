import os
from openai import OpenAI

api_key = os.environ.get("DEEPSEEK_API_KEY")
print(f"API Key found: {'YES (' + api_key[:8] + '...)' if api_key else 'NO - Not set'}")

if api_key:
    client = OpenAI(base_url="https://api.deepseek.com", api_key=api_key)
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "Nói: OK"}],
            max_tokens=10
        )
        print("DeepSeek connection: OK ->", resp.choices[0].message.content)
    except Exception as e:
        print(f"DeepSeek connection: FAILED -> {e}")
else:
    print("\n>>> ACTION REQUIRED <<<")
    print("Bạn cần thêm DEEPSEEK_API_KEY vào GitHub Secrets:")
    print("1. Vào: https://github.com/quagtm/vnstock-analyzer/settings/secrets/actions")
    print("2. Nhấn 'New repository secret'")
    print("3. Name: DEEPSEEK_API_KEY")
    print("4. Value: <API key của bạn từ platform.deepseek.com>")
    print("5. Sau đó vào Actions -> Run workflow để trigger lại")
