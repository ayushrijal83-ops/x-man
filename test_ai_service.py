from app.services.ai_service import AIService
import time

ai = AIService()

print('=' * 50)
print('TESTING NEPALSATHI AI SERVICE')
print('=' * 50)

print(f'\nProvider: {ai.provider}')
print(f'Model: {ai.model}')
print(f'Base URL: {ai.base_url}')
print(f'Health: {ai.health_check()}')

# Test generate
print('\n' + '=' * 50)
print('TESTING GENERATE')
print('=' * 50)

questions = [
    'What is the road status?',
    'Any flood warnings?',
]

for q in questions:
    print(f'\nQ: {q}')
    start = time.time()
    response = ai.generate(q)
    elapsed = time.time() - start
    print(f'Time: {elapsed:.2f} seconds')
    print(f'A: {response}')
    print('---')

# Test classify
print('\n' + '=' * 50)
print('TESTING CLASSIFY')
print('=' * 50)

posts = [
    'पहिरोले बाटो बन्द भएको छ',
    'Traffic is heavy',
]

for post in posts:
    print(f'\nPost: {post}')
    start = time.time()
    result = ai.classify_post(post)
    elapsed = time.time() - start
    print(f'Time: {elapsed:.2f} seconds')
    print(f'Result: {result}')
    print('---')