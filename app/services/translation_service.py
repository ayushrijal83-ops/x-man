import requests
import re
import os
from dotenv import load_dotenv

load_dotenv()

class TranslationService:
    """Translation service for NepalSathi multi-language support."""
    
    def __init__(self):
        self.base_url = os.getenv('OLLAMA_URL', 'http://localhost:11434')
        self.model = os.getenv('AI_MODEL', 'qwen2.5:0.5b')
        
        # UI Translations dictionary
        self.translations = {
            'en': {
                'app_name': 'NepalSathi',
                'tagline': 'Know your district. Know your roads. Know your Nepal.',
                'dashboard': 'Dashboard',
                'districts': 'Districts',
                'road_status': 'Road Status',
                'river_status': 'River Status',
                'projects': 'Projects',
                'authorities': 'Authorities',
                'file_complaint': 'File Complaint',
                'travel_planner': 'Travel Planner',
                'ai_assistant': 'AI Assistant',
                'community_feed': 'Community Feed',
                'create_post': 'Create Post',
                'my_profile': 'My Profile',
                'logout': 'Logout',
                'login': 'Login',
                'register': 'Register',
                'welcome': 'Welcome',
                'your_district': 'Your District',
                'recent_posts': 'Recent Posts',
                'active_incidents': 'Active Incidents',
                'road_segments': 'Road Segments',
                'rivers': 'Rivers',
                'view_all': 'View All',
                'search': 'Search',
                'filter': 'Filter',
                'submit': 'Submit',
                'cancel': 'Cancel',
                'save': 'Save',
                'edit': 'Edit',
                'delete': 'Delete',
                'back': 'Back',
                'next': 'Next',
                'loading': 'Loading...',
                'no_data': 'No data available',
                'post_created': 'Post created successfully!',
                'complaint_filed': 'Complaint filed successfully!',
                'profile_updated': 'Profile updated successfully!',
                'password_changed': 'Password changed successfully!',
                'emergency_numbers': 'Emergency Numbers',
                'police': 'Police',
                'fire': 'Fire',
                'ambulance': 'Ambulance',
            },
            'ne': {
                'app_name': 'नेपालसाथी',
                'tagline': 'आफ्नो जिल्ला जान्नुहोस्। आफ्नो बाटो जान्नुहोस्। आफ्नो नेपाल जान्नुहोस्।',
                'dashboard': 'ड्यासबोर्ड',
                'districts': 'जिल्लाहरू',
                'road_status': 'सडक अवस्था',
                'river_status': 'नदी अवस्था',
                'projects': 'आयोजनाहरू',
                'authorities': 'निकायहरू',
                'file_complaint': 'उजुरी दर्ता',
                'travel_planner': 'यात्रा योजना',
                'ai_assistant': 'एआई सहायक',
                'community_feed': 'सामुदायिक फिड',
                'create_post': 'पोस्ट सिर्जना',
                'my_profile': 'मेरो प्रोफाइल',
                'logout': 'लगआउट',
                'login': 'लगइन',
                'register': 'दर्ता',
                'welcome': 'स्वागत छ',
                'your_district': 'तपाईंको जिल्ला',
                'recent_posts': 'हालका पोस्टहरू',
                'active_incidents': 'सक्रिय घटनाहरू',
                'road_segments': 'सडक खण्डहरू',
                'rivers': 'नदीहरू',
                'view_all': 'सबै हेर्नुहोस्',
                'search': 'खोज्नुहोस्',
                'filter': 'फिल्टर',
                'submit': 'पेश गर्नुहोस्',
                'cancel': 'रद्द',
                'save': 'सुरक्षित',
                'edit': 'सम्पादन',
                'delete': 'मेटाउनुहोस्',
                'back': 'पछाडि',
                'next': 'अगाडि',
                'loading': 'लोड हुँदै...',
                'no_data': 'डाटा उपलब्ध छैन',
                'post_created': 'पोस्ट सफलतापूर्वक सिर्जना भयो!',
                'complaint_filed': 'उजुरी सफलतापूर्वक दर्ता भयो!',
                'profile_updated': 'प्रोफाइल सफलतापूर्वक अपडेट भयो!',
                'password_changed': 'पासवर्ड सफलतापूर्वक परिवर्तन भयो!',
                'emergency_numbers': 'आपतकालीन नम्बरहरू',
                'police': 'प्रहरी',
                'fire': 'दमकल',
                'ambulance': 'एम्बुलेन्स',
            },
            'newari': {
                'app_name': 'नेपाःसाथी',
                'tagline': 'थःगु जिल्ला सियु। थःगु लं सियु। थःगु नेपाः सियु।',
                'dashboard': 'ड्यासबोर्ड',
                'districts': 'जिल्लात',
                'road_status': 'लं अवस्था',
                'river_status': 'खुसि अवस्था',
                'projects': 'ज्याझ्वःत',
                'authorities': 'निकायत',
                'file_complaint': 'उजुरी दर्ता',
                'travel_planner': 'यात्रा योजना',
                'ai_assistant': 'एआई ग्वाहालि',
                'community_feed': 'समुदाय फिड',
                'create_post': 'पोस्ट दयेकी',
                'my_profile': 'थःगु प्रोफाइल',
                'logout': 'लगआउट',
                'login': 'लगइन',
                'register': 'दर्ता',
                'welcome': 'ज्वजलपा',
                'your_district': 'थःगु जिल्ला',
                'recent_posts': 'हालया पोस्टत',
                'active_incidents': 'सक्रिय घटनात',
                'road_segments': 'लं खण्डत',
                'rivers': 'खुसित',
                'view_all': 'फुक्क स्वयादिसँ',
                'search': 'माले',
                'filter': 'फिल्टर',
                'submit': 'पेश यानादिसँ',
                'cancel': 'रद्द',
                'save': 'सुरक्षित',
                'edit': 'सम्पादन',
                'delete': 'लित',
                'back': 'लिउ',
                'next': 'न्हापा',
                'loading': 'लोड जुइ धयाच्वंगु...',
                'no_data': 'डाटा मदु',
                'post_created': 'पोस्ट सफल जुल!',
                'complaint_filed': 'उजुरी सफल दर्ता जुल!',
                'profile_updated': 'प्रोफाइल अपडेट जुल!',
                'password_changed': 'पासवर्ड परिवर्तन जुल!',
                'emergency_numbers': 'आपतकालीन ल्याःखात',
                'police': 'प्रहरी',
                'fire': 'दमकल',
                'ambulance': 'एम्बुलेन्स',
            },
            'maithili': {
                'app_name': 'नेपालसाथी',
                'tagline': 'अपन जिला जानू। अपन सड़क जानू। अपन नेपाल जानू।',
                'dashboard': 'डैशबोर्ड',
                'districts': 'जिला सभ',
                'road_status': 'सड़क अवस्था',
                'river_status': 'नदी अवस्था',
                'projects': 'परियोजना सभ',
                'authorities': 'निकाय सभ',
                'file_complaint': 'शिकायत दर्ज',
                'travel_planner': 'यात्रा योजना',
                'ai_assistant': 'एआई सहायक',
                'community_feed': 'समुदाय फीड',
                'create_post': 'पोस्ट बनाउ',
                'my_profile': 'हमर प्रोफाइल',
                'logout': 'लॉगआउट',
                'login': 'लॉगइन',
                'register': 'पंजीकरण',
                'welcome': 'स्वागत',
                'your_district': 'अहाँक जिला',
                'recent_posts': 'हालक पोस्ट सभ',
                'active_incidents': 'सक्रिय घटना सभ',
                'road_segments': 'सड़क खंड सभ',
                'rivers': 'नदी सभ',
                'view_all': 'सभ देखू',
                'search': 'खोजू',
                'filter': 'फ़िल्टर',
                'submit': 'जमा करू',
                'cancel': 'रद्द',
                'save': 'सुरक्षित',
                'edit': 'संपादन',
                'delete': 'मेटाउ',
                'back': 'पाछू',
                'next': 'आगू',
                'loading': 'लोड होइत...',
                'no_data': 'डाटा उपलब्ध नहि',
                'post_created': 'पोस्ट सफल भेल!',
                'complaint_filed': 'शिकायत सफल दर्ज भेल!',
                'profile_updated': 'प्रोफाइल अपडेट भेल!',
                'password_changed': 'पासवर्ड बदलल!',
                'emergency_numbers': 'आपातकालीन नंबर',
                'police': 'पुलिस',
                'fire': 'दमकल',
                'ambulance': 'एम्बुलेंस',
            },
        }
    
    def get_translation(self, lang, key):
        """Get translation for a key."""
        if lang in self.translations:
            return self.translations[lang].get(key, self.translations['en'].get(key, key))
        return self.translations['en'].get(key, key)
    
    LANG_NAMES = {
        'en': 'English',
        'ne': 'Nepali (Devanagari script)',
        'newari': 'Newari / Nepal Bhasa (Devanagari script)',
        'maithili': 'Maithili (Devanagari script)',
    }

    def translate_text(self, text, target_lang):
        """Translate free text via Ollama. Returns the original text on failure.

        ponytail: qwen2.5:0.5b translates Nepali poorly and Newari/Maithili barely
        at all. UI strings come from the dictionary above, so this only affects the
        /language/translate endpoint. Set AI_MODEL to a larger model if it matters.
        """
        if target_lang == 'en' or not text:
            return text

        name = self.LANG_NAMES.get(target_lang)
        if not name:
            return text

        prompt = (
            "Translate the following English sentence into %s.\n"
            "Output ONLY the translation, nothing else.\n\n"
            "English: %s\n%s:" % (name, text, name.split(' ')[0])
        )

        try:
            response = requests.post(
                f'{self.base_url}/api/generate',
                json={
                    'model': self.model,
                    'prompt': prompt,
                    'stream': False,
                    'options': {'max_tokens': 100, 'temperature': 0.1}
                },
                timeout=20
            )

            if response.status_code == 200:
                out = response.json().get('response', '').strip()
                # the small model likes to echo "English: ... <Lang>:" back
                out = out.split(name.split(' ')[0] + ':')[-1]
                out = re.sub(r'^\s*English:.*$', '', out, flags=re.M).strip()
                out = out.strip('"').strip()
                if out:
                    return out
        except Exception:
            pass

        return text

    def get_supported_languages(self):
        """Get list of supported languages."""
        return [
            {'code': 'en', 'name': 'English', 'flag': '🇬🇧'},
            {'code': 'ne', 'name': 'नेपाली', 'flag': '🇳🇵'},
            {'code': 'newari', 'name': 'नेवारी (Newari)', 'flag': '🏔️'},
            {'code': 'maithili', 'name': 'मैथिली (Maithili)', 'flag': '🌾'},
        ]