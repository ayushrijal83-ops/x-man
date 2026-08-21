import requests
import time

print('Testing Ollama direct connection...')
print('=' * 50)

start = time.time()

try:
    response = requests.post(
        'http://localhost:11434/api/generate',
        json={
            'model': 'qwen2.5:0.5b',
            'prompt': 'Say hello in 2 words',
            'stream': False,
            'options': {'max_tokens': 20}
        },
        timeout=30
    )
    elapsed = time.time() - start
    
    print(f'Status: {response.status_code}')
    print(f'Time: {elapsed:.2f} seconds')
    
    if response.status_code == 200:
        data = response.json()
        print(f'Response: {data.get("response", "No response")}')
    else:
        print(f'Error Response: {response.text[:200]}')
        
except requests.exceptions.Timeout:
    elapsed = time.time() - start
    print(f'TIMEOUT after {elapsed:.2f} seconds')
except requests.exceptions.ConnectionError as e:
    elapsed = time.time() - start
    print(f'CONNECTION ERROR after {elapsed:.2f} seconds')
    print(f'Error: {e}')
except Exception as e:
    elapsed = time.time() - start
    print(f'ERROR after {elapsed:.2f} seconds')
    print(f'Error: {e}')

print('=' * 50)

# Test health check
print('\nTesting Ollama health...')
try:
    response = requests.get('http://localhost:11434/api/tags', timeout=5)
    print(f'Health Status: {response.status_code}')
    if response.status_code == 200:
        models = response.json().get('models', [])
        print(f'Available models:')
        for model in models:
            print(f'  - {model.get("name")}')
except Exception as e:
    print(f'Health Error: {e}')