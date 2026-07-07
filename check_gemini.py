"""Check all Gemini models available"""
import requests, os
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
        if 'gemini' in mid.lower():
            pricing = m.get('pricing', {})
            prompt_cost = float(pricing.get('prompt', 0))
            completion_cost = float(pricing.get('completion', 0))
            print(f"{mid}  | prompt: ${prompt_cost:.6f}/tok | complete: ${completion_cost:.6f}/tok")


if __name__ == '__main__':
    main()
