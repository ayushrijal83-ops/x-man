import requests
import os
import json
from dotenv import load_dotenv

load_dotenv()

class AIService:
    """AI Service for NepalSathi with Ollama and fallback."""
    
    def __init__(self):
        self.base_url = os.getenv('OLLAMA_URL', 'http://localhost:11434')
        self.model = os.getenv('AI_MODEL', 'qwen2.5:0.5b')
        self.provider = os.getenv('AI_PROVIDER', 'ollama')
    
    def generate(self, prompt, system_prompt=None):
        """Generate response from AI with Nepal context."""
        nepal_context = """You are NepalSathi AI Assistant for Nepal. Answer briefly about:
- Roads: BP Highway partially open near Dhulikhel
- Rivers: Kamala River rising (3.2m), Sunkoshi normal, Bagmati normal
- Projects: Kamala Bridge 65% complete, BP Highway Expansion 80%
- Travel: Early morning best for most routes
- Emergency: Police 100, Fire 101, Ambulance 102

Keep answer SHORT (1-2 sentences)."""
        
        full_prompt = f"{nepal_context}\n\nQuestion: {prompt}\n\nAnswer:"
        
        if self.provider == 'ollama':
            response = self._generate_ollama(full_prompt, system_prompt)
            if response:
                return response.strip()
        
        return self._generate_fallback(prompt)
    
    def _generate_ollama(self, prompt, system_prompt=None):
        """Generate using Ollama with optimized settings."""
        try:
            payload = {
                'model': self.model,
                'prompt': prompt,
                'stream': False,
                'options': {
                    'temperature': 0.3,
                    'max_tokens': 80,
                    'top_p': 0.9,
                }
            }
            
            if system_prompt:
                payload['system'] = system_prompt
            
            response = requests.post(
                f'{self.base_url}/api/generate',
                json=payload,
                timeout=20
            )
            
            if response.status_code == 200:
                return response.json().get('response', '')
        except Exception as e:
            print(f'Ollama Error: {e}')
        
        return None
    
    def _generate_fallback(self, prompt):
        """Fallback rule-based responses."""
        prompt_lower = prompt.lower()
        
        if any(word in prompt_lower for word in ['road', 'highway', 'बाटो', 'सडक']):
            return "BP Highway has some sections under construction near Dhulikhel. Check Road Status page for live updates."
        
        elif any(word in prompt_lower for word in ['river', 'flood', 'बाढी', 'नदी']):
            return "Kamala River is rising (3.2m). Sunkoshi River is normal. Check River Status page for details."
        
        elif any(word in prompt_lower for word in ['project', 'development', 'आयोजना']):
            return "Active projects: Kamala Bridge (65% complete) and BP Highway Expansion (80% complete)."
        
        elif any(word in prompt_lower for word in ['travel', 'journey', 'यात्रा']):
            return "Use Travel Planner to analyze your route. Early morning is recommended."
        
        elif any(word in prompt_lower for word in ['complaint', 'report', 'उजुरी']):
            return "File a complaint through Complaint page. Select authority and describe the issue."
        
        elif any(word in prompt_lower for word in ['emergency', 'sos', 'आपतकाल']):
            return "Emergency: Police 100, Fire 101, Ambulance 102, Disaster 1149."
        
        elif any(word in prompt_lower for word in ['hello', 'hi', 'hey', 'नमस्ते']):
            return "Namaste! I'm NepalSathi AI. Ask me about roads, rivers, projects, or travel in Nepal."
        
        else:
            return "I can help with: road conditions, river status, projects, travel planning, complaints, and emergency numbers."
    
    def classify_post(self, content):
        """Classify a post using AI with better prompts."""
        prompt = f"""Classify this Nepal post into ONE category.

Post: {content}

Categories:
- landslide: पहिरो, landslide, land slide
- traffic: जाम, traffic, congestion, ट्राफिक
- flood: बाढी, flood, flooding
- road_condition: बाटो, सडक, road, pothole, construction, खाल्डो
- weather: मौसम, weather, rain, पानी
- emergency: accident, दुर्घटना, emergency
- development: विकास, development, project
- general: anything else

Severity:
- critical: life-threatening
- high: major disruption
- medium: moderate issue
- low: minor

Language: ne (if Devanagari script) or en

Return ONLY JSON:
{{"category": "traffic", "severity": "medium", "language": "en"}}"""
        
        if self.provider == 'ollama':
            response = self._generate_ollama(prompt)
            if response:
                try:
                    start = response.find('{')
                    end = response.rfind('}') + 1
                    if start >= 0 and end > start:
                        result = json.loads(response[start:end])
                        # Validate category
                        valid_categories = ['landslide', 'traffic', 'flood', 'road_condition', 
                                           'weather', 'emergency', 'development', 'general']
                        if result.get('category') in valid_categories:
                            return result
                except:
                    pass
        
        return self._fallback_classify(content)
    
    def detect_language(self, text):
        """Detect Nepali or English."""
        devanagari_range = range(0x0900, 0x097F)
        nepali_chars = sum(1 for char in text if ord(char) in devanagari_range)
        
        if nepali_chars > 0:
            return 'ne'
        return 'en'
    
    def _fallback_classify(self, content):
        """Fallback keyword-based classification."""
        language = self.detect_language(content)
        content_lower = content.lower()
        
        # Traffic keywords (check first to avoid confusion)
        if any(word in content for word in ['जाम', 'ट्राफिक']) or any(word in content_lower for word in ['traffic', 'congestion']):
            return {'category': 'traffic', 'severity': 'medium', 'language': language}
        
        # Landslide
        elif any(word in content for word in ['पहिरो']) or any(word in content_lower for word in ['landslide']):
            return {'category': 'landslide', 'severity': 'high', 'language': language}
        
        # Flood
        elif any(word in content for word in ['बाढी']) or any(word in content_lower for word in ['flood', 'flooding']):
            return {'category': 'flood', 'severity': 'critical', 'language': language}
        
        # Road condition
        elif any(word in content for word in ['बाटो', 'सडक', 'खाल्डो']) or any(word in content_lower for word in ['road', 'pothole', 'construction']):
            return {'category': 'road_condition', 'severity': 'medium', 'language': language}
        
        # Weather
        elif any(word in content for word in ['मौसम', 'पानी']) or any(word in content_lower for word in ['weather', 'rain']):
            return {'category': 'weather', 'severity': 'low', 'language': language}
        
        # Development
        elif any(word in content for word in ['विकास', 'आयोजना']) or any(word in content_lower for word in ['development', 'project']):
            return {'category': 'development', 'severity': 'low', 'language': language}
        
        # Emergency
        elif any(word in content for word in ['दुर्घटना']) or any(word in content_lower for word in ['accident', 'emergency']):
            return {'category': 'emergency', 'severity': 'critical', 'language': language}
        
        # Default
        else:
            return {'category': 'general', 'severity': 'low', 'language': language}
    
    def health_check(self):
        """Check AI service health."""
        if self.provider == 'ollama':
            try:
                response = requests.get(f'{self.base_url}/api/tags', timeout=5)
                return response.status_code == 200
            except:
                pass
        return False
    
    def summarize_district(self, district_name, roads, rivers, projects, incidents):
        """Generate district summary."""
        road_status = ', '.join([r.name + ' (' + r.status + ')' for r in roads[:3]]) if roads else 'No roads'
        river_status = ', '.join([r.name + ' (' + r.status + ')' for r in rivers[:3]]) if rivers else 'No rivers'
        project_status = ', '.join([p.name + ' (' + str(p.progress_percent) + '%)' for p in projects[:3]]) if projects else 'No projects'
        
        prompt = f"""Summarize the current status of {district_name} district in Nepal.

Roads: {road_status}
Rivers: {river_status}
Projects: {project_status}
Active Incidents: {len(incidents) if incidents else 0}

Provide a brief 2-3 sentence summary for residents."""
        
        return self.generate(prompt)
    
    def travel_recommendation(self, from_location, to_location, risk_score, warnings_count):
        """Generate travel recommendation."""
        prompt = f"""Based on current conditions:
Route: {from_location} to {to_location}
Risk Score: {risk_score}/100
Active Warnings: {warnings_count}

Provide a brief travel recommendation for Nepal."""
        
        return self.generate(prompt)