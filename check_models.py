"""Check available model names on OpenRouter"""
import requests, json, os
from dotenv import load_dotenv
load_dotenv()


def main():
    key = os.getenv('OPENROUTER_API_KEY')
    resp = requests.get(
        'https://openrouter.ai/api/v1/models',
        headers={'Authorization': f'Bearer {key}'},
        timeout=15
    )
    models = resp.json().get('data', [])
    for m in models:
        mid = m['id']
        if 'gemini-2.5' in mid.lower() or 'gpt-4.5' in mid.lower() or mid == 'openai/gpt-4o':
            print(f'✅ {mid}')


if __name__ == '__main__':
    main()
