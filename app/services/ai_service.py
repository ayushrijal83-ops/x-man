import requests
import os
import json
from dotenv import load_dotenv

load_dotenv()

class AIService:
    """AI Service for Ollama integration."""
    
    def __init__(self):
        self.base_url = os.getenv('OLLAMA_URL', 'http://localhost:11434')
        self.model = os.getenv('AI_MODEL', 'qwen2.5:0.5b')
    
    def generate(self, prompt, system_prompt=None):
        """Generate response from Ollama."""
        try:
            payload = {
                'model': self.model,
                'prompt': prompt,
                'stream': False
            }
            
            if system_prompt:
                payload['system'] = system_prompt
            
            response = requests.post(
                f'{self.base_url}/api/generate',
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json().get('response', '')
            else:
                return None
        except Exception as e:
            print(f'AI Service Error: {e}')
            return None
    
    def classify_post(self, content):
        """Classify a post using AI."""
        prompt = f"""Classify this post about Nepal road/community information.

Post: {content}

Return JSON with these fields:
- category: traffic, road_condition, weather, landslide, emergency, development, news, announcement, general
- severity: low, medium, high, critical
- language: ne (Nepali) or en (English)

Return ONLY JSON."""
        
        response = self.generate(prompt)
        
        if response:
            try:
                # Try to parse JSON from response
                start = response.find('{')
                end = response.rfind('}') + 1
                if start >= 0 and end > start:
                    json_str = response[start:end]
                    return json.loads(json_str)
            except:
                pass
        
        # Fallback classification
        return self._fallback_classify(content)
    
    def detect_language(self, text):
        """Detect if text is Nepali or English."""
        # Simple heuristic: Check for Devanagari characters
        devanagari_range = range(0x0900, 0x097F)
        nepali_chars = sum(1 for char in text if ord(char) in devanagari_range)
        
        if nepali_chars > 0:
            return 'ne'
        return 'en'
    
    def _fallback_classify(self, content):
        """Fallback classification without AI."""
        content_lower = content.lower()
        
        # Simple keyword matching
        if any(word in content_lower for word in ['landslide', 'पहिरो']):
            return {'category': 'landslide', 'severity': 'high', 'language': self.detect_language(content)}
        elif any(word in content_lower for word in ['traffic', 'जाम', 'ट्राफिक']):
            return {'category': 'traffic', 'severity': 'medium', 'language': self.detect_language(content)}
        elif any(word in content_lower for word in ['flood', 'बाढी']):
            return {'category': 'emergency', 'severity': 'critical', 'language': self.detect_language(content)}
        elif any(word in content_lower for word in ['road', 'बाटो', 'सडक']):
            return {'category': 'road_condition', 'severity': 'medium', 'language': self.detect_language(content)}
        elif any(word in content_lower for word in ['weather', 'मौसम', 'पानी']):
            return {'category': 'weather', 'severity': 'low', 'language': self.detect_language(content)}
        else:
            return {'category': 'general', 'severity': 'low', 'language': self.detect_language(content)}
    
    def health_check(self):
        """Check if Ollama is available."""
        try:
            response = requests.get(f'{self.base_url}/api/tags', timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def summarize_district(self, district_name, roads, rivers, projects):
        """Generate district summary."""
        prompt = f"""Summarize the current status of {district_name} district.

Roads: {len(roads)} segments
Rivers: {len(rivers)} rivers
Projects: {len(projects)} active projects

Provide a brief 2-3 sentence summary for residents."""
        
        return self.generate(prompt)
    
    def travel_recommendation(self, from_location, to_location, risk_score, warnings):
        """Generate travel recommendation."""
        prompt = f"""Based on current conditions:
From: {from_location}
To: {to_location}
Risk Score: {risk_score}/100
Warnings: {len(warnings)} active warnings

Provide a brief travel recommendation in simple English."""
        
        return self.generate(prompt)