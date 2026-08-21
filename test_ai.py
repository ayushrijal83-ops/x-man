from app.services.ai_service import AIService

ai = AIService()

# Test posts
posts = [
    'पहिरोले बाटो बन्द भएको छ',
    'Traffic is heavy near Dhulikhel',
    'बाढी आएको छ गाउँमा',
    'Road construction at KM 45',
    'Weather is clear today',
    'सडकमा ठूलो खाल्डो छ',
    'Development project update',
]

print('=' * 50)
print('AI CLASSIFICATION TEST RESULTS')
print('=' * 50)

for post in posts:
    result = ai.classify_post(post)
    category = result.get('category', 'N/A')
    severity = result.get('severity', 'N/A')
    language = result.get('language', 'N/A')
    
    print(f'\nPost: {post}')
    print(f'  Category: {category}')
    print(f'  Severity: {severity}')
    print(f'  Language: {language}')
    print('  ---')

print('\n' + '=' * 50)
print('TEST COMPLETE')
print('=' * 50)

# Test AI Assistant responses
print('\n' + '=' * 50)
print('AI ASSISTANT TEST')
print('=' * 50)

questions = [
    'What is the road status?',
    'Any flood warnings?',
    'What projects are ongoing?',
    'When should I travel?',
    'How to file a complaint?',
]

for question in questions:
    response = ai.generate(question)
    print(f'\nQ: {question}')
    print(f'A: {response}')
    print('  ---')

print('\n' + '=' * 50)
print('ALL TESTS COMPLETE')
print('=' * 50)