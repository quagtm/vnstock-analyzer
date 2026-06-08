import os
import time
from openai import OpenAI

api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("GROQ_API_KEY")

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key or "sk-or-v1-abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890")

models = [
    "google/gemini-2.0-pro-exp-02-05:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free"
]

for m in models:
    try:
        print(f"Testing {m}...")
        resp = client.chat.completions.create(
            model=m,
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=10
        )
        print("Success!")
    except Exception as e:
        print(f"Error: {e}")
