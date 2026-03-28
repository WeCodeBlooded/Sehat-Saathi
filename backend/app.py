from flask import Flask, request, jsonify
from flask_cors import CORS, cross_origin
import json
import random
import firebase_admin
from firebase_admin import credentials, firestore, auth
import logging, re, os, textwrap, time
from datetime import datetime, timedelta
from flask import Response
from werkzeug.utils import secure_filename
import base64
import overpass
import requests  # Added for Hugging Face zero-shot classification

# MedlinePlus Integration for Medical Knowledge
try:
    from medlineplus_integration import medical_enhancer, enhance_chatbot_response, get_medical_info
    MEDLINEPLUS_AVAILABLE = True
except ImportError as e:
    logging.warning(f'MedlinePlus integration not available: {e}')
    MEDLINEPLUS_AVAILABLE = False
    # Create dummy functions
    def enhance_chatbot_response(user_query, detected_conditions):
        return {'confidence_boost': False, 'authoritative_summary': '', 'medical_sources': []}
    def get_medical_info(query, max_results=3):
        return []

# External Healthcare APIs Integration
try:
    from integrations.lybrate_integration import LybrateAPI, EnhancedDoctorDirectory
    from integrations.practo_integration import PractoAPI, HealthcareServicesIntegrator
    
    # Initialize external healthcare services
    LYBRATE_KEY = os.getenv('LYBRATE_API_KEY')
    PRACTO_KEY = os.getenv('PRACTO_API_KEY')
    
    # Initialize integrations if keys are available
    healthcare_integrator = None
    if LYBRATE_KEY or PRACTO_KEY:
        healthcare_integrator = HealthcareServicesIntegrator(
            lybrate_key=LYBRATE_KEY,
            practo_key=PRACTO_KEY
        )
        logging.info("External healthcare APIs initialized successfully")
    else:
        logging.info("External healthcare API keys not found - using local data only")
    
    EXTERNAL_APIS_AVAILABLE = True
except ImportError as e:
    logging.warning(f'External healthcare APIs not available: {e}')
    healthcare_integrator = None
    EXTERNAL_APIS_AVAILABLE = False

# Optional Gemini / Generative AI
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# External service API keys (loaded after dotenv)
GEOAPIFY_API_KEY = os.getenv('GEOAPIFY_API_KEY')

GENAI_AVAILABLE = False
GEMINI_STATUS = 'disabled'
# Default preferred models in order (will auto-detect availability)
_GENAI_PREFERRED_MODELS = [
    'gemini-1.5-pro-latest',
    'gemini-1.5-pro',
    'gemini-1.5-flash-latest',
    'gemini-1.5-flash',
    'gemini-pro'  # legacy fallback
]
GENAI_MODEL_NAME = None  # Will be resolved dynamically
_LAST_MODEL_REFRESH = 0
_MODEL_REFRESH_INTERVAL_SEC = 1800  # refresh model list every 30 minutes
_CONSECUTIVE_404S = 0
_MAX_404S_BEFORE_DISABLE = 5
try:
    import google.generativeai as genai
    _gemini_key = os.getenv('GEMINI_API_KEY')
    if _gemini_key:
        genai.configure(api_key=_gemini_key)
        # Allow override via env
        env_model = os.getenv('GEMINI_MODEL')
        available_models = []
        try:
            # list_models returns objects with name attribute like 'models/gemini-1.5-pro-latest'
            for m in genai.list_models():
                if hasattr(m, 'name') and isinstance(m.name, str):
                    # Normalize to short form after last '/'
                    short = m.name.split('/')[-1]
                    available_models.append(short)
        except Exception as lm_err:
            logging.warning(f'Could not list Gemini models: {lm_err}')
        # Runtime selection deferred to resolve_genai_model() for accuracy
        GENAI_AVAILABLE = True
        if env_model:
            GENAI_MODEL_NAME = env_model  # tentative; will be validated at first use
            GEMINI_STATUS = f'enabled:tentative:{env_model}'
        else:
            GEMINI_STATUS = 'enabled:auto_fallback'
    else:
        GEMINI_STATUS = 'disabled:no_key'
        logging.warning('GEMINI_API_KEY not set; AI recommendation disabled.')
except ImportError:
    logging.warning('google-generativeai not installed; AI recommendation disabled.')
except Exception as e:
    logging.warning(f'Gemini initialization failed: {e}')

# -------- Helper: Resolve a usable Gemini model dynamically --------
def resolve_genai_model():
    global GENAI_MODEL_NAME, GEMINI_STATUS, _LAST_MODEL_REFRESH, GENAI_AVAILABLE
    if not GENAI_AVAILABLE:
        return None
    now = time.time()
    # If we have a model and it's recent, reuse
    if GENAI_MODEL_NAME and (now - _LAST_MODEL_REFRESH) < _MODEL_REFRESH_INTERVAL_SEC:
        return GENAI_MODEL_NAME
    try:
        models = []
        try:
            for m in genai.list_models():
                # Keep only those supporting generateContent
                methods = getattr(m, 'supported_generation_methods', []) or []
                if 'generateContent' in methods:
                    models.append(m)
        except Exception as lm_err:
            logging.warning(f'Model list refresh failed: {lm_err}')
            # If listing fails, fall back to preferred list ordering without validation
            GENAI_MODEL_NAME = _GENAI_PREFERRED_MODELS[0]
            GEMINI_STATUS = f'enabled:fallback_no_list:{GENAI_MODEL_NAME}'
            _LAST_MODEL_REFRESH = now
            return GENAI_MODEL_NAME
        short_names = [m.name.split('/')[-1] for m in models if hasattr(m, 'name')]
        # If user forced a model via env and it's in list, use it
        if GENAI_MODEL_NAME and GENAI_MODEL_NAME in short_names:
            GEMINI_STATUS = f'enabled:{GENAI_MODEL_NAME}'
            _LAST_MODEL_REFRESH = now
            return GENAI_MODEL_NAME
        # Choose first preferred present
        for cand in _GENAI_PREFERRED_MODELS:
            if (not short_names) or (cand in short_names):
                GENAI_MODEL_NAME = cand
                GEMINI_STATUS = f'enabled:{cand}'
                _LAST_MODEL_REFRESH = now
                return GENAI_MODEL_NAME
        # None matched
        GENAI_MODEL_NAME = None
        GEMINI_STATUS = 'enabled:no_supported_models'
        _LAST_MODEL_REFRESH = now
        return None
    except Exception as e:
        logging.warning(f'Model resolution error: {e}')
        GEMINI_STATUS = 'enabled:model_resolution_error'
        return None

app = Flask(__name__)
# Expanded CORS to ensure preflight (OPTIONS) succeeds for custom POST endpoints
CORS(app, resources={r"/*": {"origins": "*"}}, allow_headers=["Content-Type","Authorization","X-Requested-With"], methods=["GET","POST","OPTIONS"], max_age=86400)

# Simple in-memory (or disk) storage for consult attachments (prototype)
ATTACHMENTS_DIR = os.path.join(os.path.dirname(__file__), 'consult_attachments')
os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
ALLOWED_ATTACHMENT_EXT = {'.pdf', '.png', '.jpg', '.jpeg', '.txt'}
MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024  # 2MB prototype limit

def _consult_attachment_path(consult_id, filename):
    safe = secure_filename(filename)
    return os.path.join(ATTACHMENTS_DIR, f"{consult_id}__{safe}")

def _list_consult_attachments(consult_id):
    prefix = f"{consult_id}__"
    out = []
    try:
        for fn in os.listdir(ATTACHMENTS_DIR):
            if fn.startswith(prefix):
                path = os.path.join(ATTACHMENTS_DIR, fn)
                size = os.path.getsize(path)
                out.append({'filename': fn.split('__',1)[1], 'size': size})
    except Exception:
        pass
    return out

# Initialize the Firebase Admin SDK
# Use a service account key file (you'll download this from Firebase)
try:
    # For development, you can use the default credentials or specify a service account key
    # Make sure to add your Firebase service account key file to the project
    cred = credentials.Certificate('./serviceAccountKey.json')
    firebase_admin.initialize_app(cred)
    
    # Point to your Firestore database
    db = firestore.client()
    print("Firebase initialized successfully")
except Exception as e:
    print(f"Firebase initialization failed: {e}")
    # For development, you might want to continue without Firebase
    db = None

# Try to import and initialize translator, fallback if not available
try:
    from deep_translator import GoogleTranslator
    from langdetect import detect
    TRANSLATION_AVAILABLE = True
    print("Translation service initialized successfully")
except ImportError as e:
    print(f"Translation library not available: {e}")
    TRANSLATION_AVAILABLE = False
except Exception as e:
    print(f"Translation service initialization failed: {e}")
    TRANSLATION_AVAILABLE = False

with open('data/responses.json', 'r') as file:
    responses = json.load(file)

with open('data/hospitals.json', 'r') as file:
    hospitals_data = json.load(file)

# Enhanced Greeting and Conversation Detection
def detect_greeting_or_conversation(message_lower, uid=None):
    """
    Detect greetings, farewells, and general conversational patterns.
    Returns appropriate response or None if this is likely a medical query.
    """
    
    # Expanded greeting patterns (English, Hindi, Hinglish, casual)
    greeting_patterns = [
        r'\b(hello|hi|hey|namaste|namaskar|yo|hola|sup|wassup|greetings|shalom|bonjour)\b',
        r'\b(good morning|good afternoon|good evening|good night|morning|evening|night)\b',
        r'\b(how are you|kaise ho|kya hal hai|kaisi ho|howdy|how r u|howz it going)\b',
        r'\b(what\'s up|whats up|wassup|kya chal raha hai|kya haal hai|kya scene hai)\b',
        r'\b(yo|sup|hey there|hi there|hello there)\b'
    ]
    # Expanded farewells
    farewell_patterns = [
        r'\b(bye|goodbye|see you|alvida|milte hain|see ya|later|ciao|peace out)\b',
        r'\b(thank you|thanks|dhanyawad|shukriya|tysm|thx|thank u)\b',
        r'\b(take care|good night|shubh ratri|rest well|sweet dreams)\b'
    ]
    # Expanded general conversation patterns
    conversation_patterns = [
        r'\b(who are you|what are you|aap kaun hain|who r u|who is this|who am i talking to)\b',
        r'\b(what can you do|help me|kya kar sakte hain|how can you help|what help)\b',
        r'\b(tell me about yourself|introduce yourself|about you|about sehat saathi)\b',
        r'\b(how does this work|kaise kaam karta hai|how does it work|explain this)\b',
        r'\b(are you real|are you a doctor|are you human|are you ai|are you chatbot)\b'
    ]
    
    # Check for greetings
    for pattern in greeting_patterns:
        if re.search(pattern, message_lower):
            greetings = [
                "Hello! I'm your health assistant. How can I help you today?",
                "Hi there! I'm here to help with your health questions. What's on your mind?",
                "Namaste! I can help you with health information and advice. How are you feeling?",
                "Hello! I'm Sehat Saathi, your health companion. Please tell me how you're feeling or what health concerns you have."
            ]
            return random.choice(greetings)
    
    # Check for farewells
    for pattern in farewell_patterns:
        if re.search(pattern, message_lower):
            farewells = [
                "Take care! Remember to stay healthy and don't hesitate to reach out if you need medical advice.",
                "Goodbye! Wishing you good health. Feel free to ask me anything health-related anytime.",
                "Thank you for using Sehat Saathi! Stay safe and healthy. Come back anytime you need health guidance.",
                "Take care of yourself! Remember - if you have serious symptoms, always consult a doctor."
            ]
            return random.choice(farewells)
    
    # Check for general conversation
    for pattern in conversation_patterns:
        if re.search(pattern, message_lower):
            info_responses = [
                "I'm Sehat Saathi, your AI health assistant. I can help you understand symptoms, provide basic medical guidance, and suggest when to see a doctor. I can also help you find nearby hospitals and doctors. What health concern would you like to discuss?",
                "I'm here to help with your health questions! I can provide information about symptoms, basic first aid, when to seek medical care, and help you locate healthcare services. What would you like to know about your health?",
                "I'm an AI health companion designed to help with medical questions and health guidance. I can assist with symptom assessment, basic health advice, emergency care guidance, and finding healthcare providers. How can I help you today?"
            ]
            return random.choice(info_responses)
    
    # Check if message is too short, generic, or just emojis (likely not a medical query)
    if len(message_lower.split()) <= 2 or all(not c.isalnum() for c in message_lower):
        short_responses = [
            "👋 Hi! Could you tell me a bit more about your health or how you're feeling?",
            "I'm here to help with health questions. Please describe your symptoms or ask any health-related question!",
            "Could you share more details about your health concern or what you're experiencing?"
        ]
        return random.choice(short_responses)
    
    # Check for medical contexts involving family members (should NOT be redirected)
    family_medical_patterns = [
        r'\b(my|our)\s+(child|baby|kid|son|daughter|infant|toddler|teenager|parent|mother|father|mom|dad|wife|husband|family|friend)\s+(has|is|feels|experiencing|complaining)',
        r'\b(child|baby|kid|son|daughter|infant|toddler|teenager|parent|mother|father|mom|dad|wife|husband)\s+(has|is|feels).+(fever|pain|sick|ill|hurt|cough|cold|vomit)',
        r'\b(baby|infant|child|kid).+(fever|temperature|sick|crying|not eating|rash|cough)'
    ]
    for pattern in family_medical_patterns:
        if re.search(pattern, message_lower):
            return None  # Allow it to be treated as a medical query
    
    # Expanded non-health topics and friendly redirection
    non_health_patterns = [
        r'\b(weather|movie|song|game|food|restaurant|travel|trip|holiday|vacation|party|shopping|shopping mall|mall|sale|discount)\b',
        r'\b(politics|election|news|sports|cricket|football|basketball|tennis|olympics|score|match|team)\b',
        r'\b(joke|funny|entertainment|music|dance|meme|tiktok|reel|youtube|netflix|prime|series|show)\b',
        r'\b(work|job|office|study|school|college|exam|assignment|project|boss|teacher|student)\b',
        r'\b(relationship|love|dating|crush|marriage|wedding|breakup)\b'
    ]
    for pattern in non_health_patterns:
        if re.search(pattern, message_lower):
            redirect_responses = [
                "I'm here to help with health and medical questions! If you have any health concerns, symptoms, or want to know about healthy living, just ask.",
                "I focus on health topics. If you have a question about your health, symptoms, or medical care, I'm here for you!",
                "I'm your health assistant, so I specialize in medical and wellness guidance. Let me know if you have any health-related questions!"
            ]
            return random.choice(redirect_responses)

    # Catch-all for totally off-topic, nonsense, or unsupported input
    if not re.search(r'[a-zA-Z0-9]', message_lower):
        return "I'm here to help with health and wellness questions. Please type your health concern or symptom."

    # If the message is unclear or doesn't match anything, gently prompt for clarification
    unclear_patterns = [
        r'\b(idk|dont know|don\'t know|no idea|random|anything|whatever|something|nothing)\b',
        r'\?\?\?|\.\.\.',
        r'[\?\!\.][\?\!\.][\?\!\.]+'
    ]
    for pattern in unclear_patterns:
        if re.search(pattern, message_lower):
            return "Could you please clarify your health question or describe your symptoms in a bit more detail?"
    
    # Return None if this seems like a potential medical query
    return None

# Calculate match confidence for keyword matching
def calculate_match_confidence(keyword, normalized_message, original_message):
    """
    Calculate confidence score for keyword matches based on various factors.
    """
    # Base confidence
    confidence = 0.5
    
    # Boost for longer, more specific keywords
    if len(keyword) > 10:
        confidence += 0.2
    elif len(keyword) > 5:
        confidence += 0.1
    
    # Boost for exact matches (non-normalized)
    if keyword.lower() in original_message.lower():
        confidence += 0.2
    
    # Boost for medical-specific terms
    medical_terms = ['pain', 'ache', 'fever', 'infection', 'disease', 'syndrome', 'disorder']
    if any(term in keyword.lower() for term in medical_terms):
        confidence += 0.15
    
    # Boost for multiple word keywords (more specific)
    if ' ' in keyword:
        confidence += 0.1
    
    # Penalize very common words
    common_words = ['the', 'and', 'or', 'with', 'have', 'is', 'are']
    if any(word in keyword.lower() for word in common_words):
        confidence -= 0.1
    
    # Ensure confidence is within bounds
    return max(0.1, min(0.95, confidence))

# Enhanced Medical Response Accuracy
def get_enhanced_medical_response(user_message, matched_entries, confidence_scores):
    """
    Provide more accurate and comprehensive medical responses with better context.
    """
    if not matched_entries:
        return None
    
    # Sort by confidence if available
    if confidence_scores:
        sorted_entries = sorted(zip(matched_entries, confidence_scores), 
                              key=lambda x: x[1], reverse=True)
        best_entry, best_confidence = sorted_entries[0]
    else:
        best_entry = matched_entries[0]
        best_confidence = 0.5
    
    # Get the advice
    if isinstance(best_entry, tuple):
        entry, matched_keywords = best_entry
        advice = entry.get('advice', '')
        keywords = entry.get('keywords', [])
    else:
        advice = best_entry.get('advice', '')
        keywords = best_entry.get('keywords', [])
        matched_keywords = set()
    
    # Enhanced advice with additional context
    enhanced_advice = advice
    
    # Add confidence indicator for low confidence matches
    if best_confidence < 0.3:
        enhanced_advice = f"⚠️ Based on your description, this might be related to: {advice}\n\nHowever, I recommend consulting a healthcare professional for accurate diagnosis and treatment."
    
    # Add emergency warnings for critical symptoms
    critical_keywords = ['chest pain', 'heart attack', 'stroke', 'seizure', 'poisoning', 'severe allergic reaction']
    if any(kw in str(keywords).lower() for kw in critical_keywords):
        enhanced_advice = "🚨 EMERGENCY: " + enhanced_advice + "\n\n⚡ If this is a medical emergency, call emergency services immediately!"
    
    # Add follow-up recommendations
    if best_confidence > 0.7:
        enhanced_advice += "\n\n💡 Additional advice: Monitor your symptoms, maintain good hygiene, rest adequately, and don't hesitate to seek professional medical care if symptoms worsen or persist."
    
    return enhanced_advice

# Simple in-memory doctor directory mapping specialties to available doctors.
# In production this would come from a database or external service.
DOCTOR_DIRECTORY = {
    'cardiology': ['Dr. Arjun Mehta', 'Dr. Kavita Rao'],
    'dermatology': ['Dr. Neha Kapoor', 'Dr. Rohan Iyer'],
    'neurology': ['Dr. S. Menon', 'Dr. Priya Kaul'],
    'orthopedics': ['Dr. Nikhil Shah', 'Dr. Aditi Verma'],
    'pediatrics': ['Dr. Ritu Malhotra', 'Dr. Aman Batra'],
    'general': ['Dr. Anil Singh', 'Dr. Farah Khan', 'Dr. Vivek Patel'],
    'ent': ['Dr. Varun Sharma', 'Dr. K. Nanda'],
    'ophthalmology': ['Dr. Ishita Bose', 'Dr. Deepak Gill']
}

# ---------------- Indic / Hinglish Detection Helpers -----------------
# We only want to translate for supported Indian languages; everything else defaults to English.
SUPPORTED_INDIC_LANGS = {
    'hi',  # Hindi
    'bn',  # Bengali
    'ta',  # Tamil
    'te',  # Telugu
    'ml',  # Malayalam
    'mr',  # Marathi
    'gu',  # Gujarati
    'kn',  # Kannada
    'pa',  # Punjabi
}

# ---------------- Symptom / Keyword Synonym Map (English, post-translation) -----------------
# Simple lowercase replacements; multi-word phrases processed longest-first.
SYNONYM_MAP = {
    'belly pain': 'stomach pain',
    'belly': 'stomach',
    'tummy ache': 'stomach pain',
    'tummy': 'stomach',
    'abdomen pain': 'stomach pain',
    'abdominal pain': 'stomach pain',  # already present but ensure normalization
    'gastric pain': 'stomach pain',
    'gastric': 'stomach',
    'shortness of breath': 'breathing problem',
    'breathlessness': 'breathing problem',
    'loose motions': 'diarrhea',
    'loose motion': 'diarrhea',
    'throat pain': 'sore throat',
    'coughing': 'cough',
    'nauseous': 'nausea',
    # Women's health synonyms
    'period bleeding': 'menstrual bleeding',
    'period pain': 'menstrual pain', 
    'period problems': 'menstrual problem',
    'menstrual cycle': 'menstrual problem',
    'periods': 'menstrual bleeding',
    'menses': 'menstrual bleeding',
    'monthly cycle': 'menstrual problem',
    'vaginal spotting': 'vaginal bleeding',
    'spotting': 'vaginal bleeding',
    'heavy flow': 'heavy periods',
    'irregular cycle': 'irregular periods',
    'gynec problem': 'gynecological issue',
    'women problem': 'gynecological issue',
    'female issue': 'gynecological issue',
    'reproductive issue': 'reproductive health',
    'pelvic discomfort': 'pelvic pain',
    'lower belly pain': 'pelvic pain',
    # Cardiovascular synonyms
    'heart attack': 'cardiac emergency',
    'heart trouble': 'heart problem',
    'chest tightness': 'chest pain',
    'chest pressure': 'chest pain',
    'high bp': 'high blood pressure',
    'hypertension': 'high blood pressure',
    # Respiratory synonyms
    'breathlessness': 'shortness of breath',
    'wheezing': 'breathing difficulty',
    'chest infection': 'pneumonia',
    'lung problem': 'respiratory infection',
    # Neurological synonyms
    'brain stroke': 'stroke symptoms',
    'paralysis': 'stroke symptoms',
    'fits': 'seizure',
    'convulsions': 'seizure',
    'memory loss': 'memory problem',
    'confusion': 'memory problem',
    # Musculoskeletal synonyms
    'bone pain': 'joint pain',
    'muscle pain': 'muscle problem',
    'sprain': 'injury',
    'strain': 'muscle problem',
    'broken bone': 'fracture',
    # Mental health synonyms
    'stress': 'anxiety',
    'worry': 'anxiety',
    'panic': 'anxiety',
    'sadness': 'depression',
    'sleep disorder': 'sleep problem',
    'insomnia': 'sleep problem',
    # Endocrine synonyms
    'sugar problem': 'diabetes',
    'blood sugar': 'diabetes',
    'thyroid': 'thyroid problem',
    # Emergency synonyms
    'unconscious': 'emergency condition',
    'collapse': 'emergency condition',
    'severe pain': 'emergency condition',
    'drug overdose': 'poisoning',
    'toxic exposure': 'poisoning'
}

def normalize_synonyms(text: str) -> str:
    if not text:
        return text
    lower = text.lower()
    # Sort synonyms by length (desc) so multi-word phrases replace first
    for phrase in sorted(SYNONYM_MAP.keys(), key=len, reverse=True):
        repl = SYNONYM_MAP[phrase]
        lower = re.sub(r'\b' + re.escape(phrase) + r'\b', repl, lower)
    return lower

# ---------------- Simple In-Memory Session Cache -----------------
# Stores last matched keyword signature per session_id to skip recomputation for identical message patterns.
SESSION_MATCH_CACHE = {}

# ---------------- Optional HuggingFace Zero-Shot Classification ---------------
HF_API_TOKEN = os.getenv('HUGGINGFACE_API_TOKEN')
HF_MODEL = os.getenv('HUGGINGFACE_ZS_MODEL', 'facebook/bart-large-mnli')
HF_TIMEOUT = float(os.getenv('HUGGINGFACE_TIMEOUT_SEC', '3.5'))
HF_ENABLED = bool(HF_API_TOKEN)

# Comprehensive condition categories covering all major medical specialties
# 'unknown' is placed first to increase likelihood of selection for ambiguous cases
HF_CONDITION_LABELS = [
    'unknown', 'general health concern',
    # Common symptoms
    'fever', 'headache', 'pain', 'fatigue',
    # Respiratory
    'respiratory infection', 'cough', 'cold', 'flu', 'asthma', 'breathing difficulty', 'pneumonia',
    # Cardiovascular  
    'chest pain', 'heart problem', 'blood pressure issue', 'cardiac emergency',
    # Gastrointestinal
    'stomach pain', 'diarrhea', 'vomiting', 'nausea', 'constipation', 'acid reflux',
    # Neurological
    'neurological issue', 'stroke symptoms', 'seizure', 'dizziness', 'memory problem',
    # Musculoskeletal
    'joint pain', 'back pain', 'muscle problem', 'fracture', 'injury',
    # Dermatological
    'skin issue', 'rash', 'allergic reaction', 'eczema', 'acne',
    # Women's health
    'pregnancy related', 'gynecological issue', 'menstrual problem', 'reproductive health',
    # Mental health
    'mental health concern', 'depression', 'anxiety', 'sleep problem',
    # Endocrine
    'diabetes', 'thyroid problem', 'hormonal issue',
    # Infectious diseases
    'infection', 'viral illness', 'bacterial infection',
    # Emergency conditions
    'emergency condition', 'poisoning', 'severe allergic reaction',
    # Pediatric
    'pediatric concern', 'child fever', 'infant problem',
    # Other specialties
    'eye issue', 'dental issue', 'urinary problem', 'burn', 'cut', 'snake bite', 'dog bite'
]

HF_LABEL_ADVICE = {
    'unknown': 'Monitor symptoms carefully; consult a healthcare professional if they persist, worsen, or you have concerns.',
    'general health concern': 'Monitor your symptoms, rest, stay hydrated. Consult a healthcare professional if symptoms persist, worsen, or you have specific concerns.',
    'respiratory infection': 'Rest, stay hydrated, monitor fever and breathing. Seek care if breathing worsens or high fever persists.',
    'breathing difficulty': 'Sit upright, loosen tight clothing. If severe or with chest pain, seek emergency medical help immediately.',
    'stomach pain': 'Use light meals and fluids. Severe, persistent, or localized pain (esp. with vomiting / blood) requires medical evaluation.',
    'diarrhea': 'Oral rehydration (ORS), avoid street food. If blood appears or lasts >2 days, consult a doctor.',
    'vomiting': 'Small sips of water/ORS. If persistent, bloody, or with severe pain, seek urgent care.',
    'nausea': 'Light bland food, hydration. Persistent or worsening symptoms merit medical advice.',
    'dehydration': 'Increase fluids (ORS, coconut water). If confusion, fainting, or no urination, seek urgent care.',
    'pain': 'Monitor pain severity and location. Rest, apply heat/ice as appropriate. Severe, sudden, or persistent pain needs medical evaluation.',
    'fatigue': 'Ensure adequate rest, hydration, and nutrition. Persistent fatigue lasting weeks may indicate underlying conditions requiring medical assessment.',
    # Cardiovascular
    'chest pain': 'URGENT: Severe chest pain, especially with arm/jaw pain, sweating, or breathing difficulty requires immediate emergency care. Call ambulance.',
    'heart problem': 'Heart symptoms (palpitations, chest discomfort, shortness of breath) need prompt medical evaluation. Avoid strenuous activity until assessed.',
    'blood pressure issue': 'Monitor BP regularly, reduce salt, maintain healthy weight. Very high BP (>180/110) with symptoms needs immediate medical care.',
    'cardiac emergency': 'EMERGENCY: Call ambulance immediately for severe chest pain, difficulty breathing, or collapse. Do not drive yourself to hospital.',
    # Respiratory
    'pneumonia': 'Rest, stay hydrated, seek prompt medical care for fever, productive cough, chest pain. Elderly/immunocompromised need immediate attention.',
    # Neurological
    'stroke symptoms': 'EMERGENCY: Face drooping, arm weakness, speech problems = call ambulance IMMEDIATELY. Time is critical for stroke treatment.',
    'seizure': 'Keep person safe, don\'t restrain, turn to side after seizure. Call emergency if lasts >5 minutes or breathing difficulty.',
    'dizziness': 'Sit down, stay hydrated, avoid sudden movements. Severe or persistent dizziness with other symptoms needs medical evaluation.',
    'memory problem': 'Sudden confusion needs immediate evaluation. Gradual memory changes should be discussed with healthcare provider.',
    # Gastrointestinal  
    'constipation': 'Increase fiber, fluids, exercise. If severe pain, vomiting, or no bowel movement >3 days, see doctor.',
    'acid reflux': 'Eat smaller meals, avoid triggers, elevate head while sleeping. Persistent symptoms or difficulty swallowing need evaluation.',
    # Musculoskeletal
    'joint pain': 'Rest joint, apply ice/heat, gentle movement. Red, hot, swollen joints or severe limitation needs medical attention.',
    'back pain': 'Rest, apply heat/ice, gentle stretching. Pain radiating to legs, numbness, or after injury needs prompt evaluation.',
    'muscle problem': 'Rest, gentle stretching, stay hydrated. Persistent weakness or severe cramping needs medical assessment.',
    'fracture': 'Don\'t move injured area, apply ice, seek immediate medical care. Call emergency for severe injuries.',
    # Dermatological
    'rash': 'Keep clean and dry, avoid scratching. Rapidly spreading rash with fever or breathing problems = emergency.',
    'eczema': 'Moisturize regularly, avoid triggers, use mild products. Severe flare-ups or signs of infection need medical care.',
    'acne': 'Gentle cleansing, don\'t pick. Severe or scarring acne should be evaluated by dermatologist.',
    # Women's health
    'gynecological issue': 'For vaginal bleeding, pelvic pain, or unusual discharge, please consult a gynecologist promptly. Heavy bleeding or severe pain requires immediate medical attention.',
    'menstrual problem': 'For irregular periods, excessive bleeding, or severe cramps, track symptoms and consult a healthcare provider. Heavy bleeding soaking pads hourly needs urgent care.',
    'reproductive health': 'For reproductive health concerns, consult a gynecologist or healthcare provider. Do not ignore unusual symptoms, bleeding, or pain.',
    # Mental health
    'depression': 'Reach out to mental health professionals, trusted people, or crisis helplines. Suicidal thoughts require immediate emergency help.',
    'anxiety': 'Practice deep breathing, grounding techniques. If significantly impacting life or panic attacks, seek professional support.',
    'sleep problem': 'Maintain regular sleep schedule, avoid screens before bed. Chronic insomnia may indicate underlying conditions.',
    # Endocrine
    'diabetes': 'Monitor blood sugar, maintain healthy diet, regular exercise. Extremely high/low blood sugar needs immediate medical attention.',
    'thyroid problem': 'Symptoms like weight changes, fatigue, heart rate changes need medical evaluation and blood tests.',
    'hormonal issue': 'Hormonal imbalances affecting mood, weight, or cycles should be evaluated by healthcare provider.',
    # Infectious diseases
    'infection': 'Monitor for fever, spreading redness, or worsening symptoms. Severe infections need prompt antibiotic treatment.',
    'viral illness': 'Rest, fluids, symptom management. Seek care if symptoms worsen, breathing problems, or dehydration.',
    'bacterial infection': 'May require antibiotics - consult healthcare provider. Don\'t ignore signs of spreading infection.',
    # Emergency
    'emergency condition': 'EMERGENCY: Call ambulance immediately. Do not delay for life-threatening symptoms.',
    'poisoning': 'Call poison control immediately. Do not induce vomiting unless instructed. Bring substance container if safe.',
    'severe allergic reaction': 'EMERGENCY: Call ambulance for face/throat swelling, breathing difficulty, or rapid pulse after exposure.',
    # Pediatric
    'pediatric concern': 'Children need prompt medical attention for concerning symptoms. When in doubt, consult pediatrician.',
    'child fever': 'Infants <3 months with fever need immediate care. Monitor hydration and breathing in older children.',
    'infant problem': 'Babies <3 months need immediate medical evaluation for any concerning symptoms.',
    # Other conditions
    'allergic reaction': 'Remove trigger, monitor breathing. Swelling of face/throat or breathing issues = emergency.',
    'skin issue': 'Keep area clean and dry. Spreading redness, pus, or fever needs doctor review.',
    'urinary problem': 'Increase fluids for mild symptoms. Severe pain, blood, or inability to urinate needs immediate care.',
    'injury': 'Apply clean pressure for bleeding, immobilize if fracture suspected. Seek care for deep wounds or severe pain.',
    'burn': 'Cool running water 10 mins. Do not apply toothpaste/oil. Large or deep burns need emergency care.',
    'cut': 'Clean with water, apply antiseptic, cover. If deep or bleeding won’t stop, seek care.',
    'snake bite': 'Keep still, limb immobilized. Get emergency medical help immediately.',
    'dog bite': 'Wash with soap & water 15 mins. Seek rabies prophylaxis promptly.',
    'eye issue': 'Rinse with clean water. Pain, vision change, or discharge → doctor.',
    'dental issue': 'Rinse warm salt water, avoid extremes of temperature. Persistent pain or swelling → dentist.',
    'neurological issue': 'Severe headache, sudden weakness, speech or vision changes require urgent evaluation.',
    'headache': 'Hydration, rest in low-light room. Severe or recurrent headaches with neuro signs → doctor.',
    'migraine': 'Rest, dark quiet room, hydration. If new or changing pattern, seek medical advice.',
    'pregnancy related': 'Any heavy bleeding, severe pain, or dizziness during pregnancy needs urgent obstetric evaluation.',
    'mental health concern': 'Speak with a trusted person or professional. Suicidal thoughts require immediate helpline/emergency contact.',
    'fever': 'Hydration, rest, monitor temperature. Fever >102°F or >2 days needs medical review.',
    'cough': 'Warm fluids, steam inhalation. Persistent, bloody, or breath-limiting cough → doctor.',
    'cold': 'Rest, fluids, symptomatic relief. High fever or breathing issues → medical exam.',
    'flu': 'Rest, fluids, monitor high fever and breathing. High-risk groups should consult early.',
    'asthma': 'Use prescribed inhaler, monitor breathing. If not improving or severe, seek urgent care.'
}

_HF_CACHE = {}

def hf_zero_shot_categories(text: str, top_k: int = 3):
    """Return top_k condition labels using HuggingFace zero-shot classification if enabled.
    Falls back gracefully if disabled or errors occur."""
    if not HF_ENABLED or not text:
        return []
    key = (hash(text), top_k)
    if key in _HF_CACHE:
        return _HF_CACHE[key]
    payload = {
        'inputs': text[:2000],  # limit size
        'parameters': {
            'candidate_labels': HF_CONDITION_LABELS,
            'multi_label': True
        }
    }
    url = f"https://api-inference.huggingface.co/models/{HF_MODEL}"
    headers = {'Authorization': f'Bearer {HF_API_TOKEN}'}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=HF_TIMEOUT)
        if resp.status_code == 503:
            # Warm-up state – skip silently
            return []
        data = resp.json()
        labels = data.get('labels') or []
        scores = data.get('scores') or []
        paired = sorted(zip(labels, scores), key=lambda x: x[1], reverse=True)
        # Filter by confidence threshold - be more selective
        filtered = [(l, s) for l, s in paired if s >= 0.25][:top_k]
        
        # If no high-confidence matches and top score is for injury/cut, prefer unknown/general
        if filtered and len(filtered) >= 1:
            top_label, top_score = filtered[0]
            # If the top match is injury/cut with low-medium confidence, prefer generic labels
            if top_label in ['injury', 'cut', 'burn'] and top_score < 0.4:
                # Check if unknown or general health concern have reasonable scores
                for label, score in paired:
                    if label in ['unknown', 'general health concern'] and score >= 0.15:
                        filtered = [(label, score)] + [item for item in filtered if item[0] != label]
                        break
        
        _HF_CACHE[key] = filtered
        return filtered
    except Exception:
        return []

# Common transliterated Hindi (Hinglish) / general symptom tokens (lowercase, ascii) for heuristic mapping
HINGLISH_HINT_TOKENS = {
    'hai','nahi','nahi','bukhar','bukhaar','dard','pet','sir','khansi','khaansi','khansi','khasi','ulti','ulTI','ulati','saans','phool','phoolna','sardi','jala','jalna','jaldi','dawai','dava','davayi','medicine','tez','kamzori','kamjori','thakan','thakawat','thak','gabrahat','gas','pet dard'
}

DEVANAGARI_RANGE = (0x0900, 0x097F)

def looks_devanagari(text: str) -> bool:
    for ch in text:
        cp = ord(ch)
        if DEVANAGARI_RANGE[0] <= cp <= DEVANAGARI_RANGE[1]:
            return True
    return False

def heuristic_detect_indic(text: str) -> str:
    """Return a language code from SUPPORTED_INDIC_LANGS or 'en'.
    Strategy:
      1. If any Devanagari chars -> assume Hindi (hi).
      2. Tokenize ascii words; if sufficient Hinglish tokens -> hi.
      3. Use langdetect (if available) and keep only if in our whitelist.
    """
    if not text or not isinstance(text, str):
        return 'en'
    lower = text.lower()
    # Step 1: Script check
    if looks_devanagari(lower):
        return 'hi'
    # Step 2: Hinglish token heuristic
    tokens = re.findall(r"[a-zA-Z']+", lower)
    if tokens:
        hits = sum(1 for t in tokens if t in HINGLISH_HINT_TOKENS)
        if hits >= 2 or (hits >= 1 and len(tokens) <= 6):
            return 'hi'
    # Step 3: Fallback to langdetect result but constrain
    # Disabled langdetect due to issues with special characters
    # if TRANSLATION_AVAILABLE:
    #     try:
    #         # Clean the text first to avoid langdetect issues
    #         cleaned_text = re.sub(r'[^\w\s]', ' ', lower)
    #         cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
    #         
    #         if len(cleaned_text) > 3:  # Only detect if we have sufficient text
    #             detected = detect(cleaned_text)
    #             if detected in SUPPORTED_INDIC_LANGS:
    #                 return detected
    #     except Exception as e:
    #         # If langdetect fails, just return English
    #         logging.debug(f'Language detection failed: {e}')
    #         pass
    return 'en'

def assign_doctor_for_specialty(spec: str):
    if not spec:
        spec = 'general'
    key = spec.lower().strip()
    # Fuzzy fallback: choose key with prefix match
    if key not in DOCTOR_DIRECTORY:
        for existing in DOCTOR_DIRECTORY.keys():
            if existing.startswith(key):
                key = existing
                break
    doctor_list = DOCTOR_DIRECTORY.get(key) or DOCTOR_DIRECTORY.get('general', [])
    if not doctor_list:
        return 'Dr. On Call', key
    return random.choice(doctor_list), key

# Initialize Overpass API instance with optional env-based endpoint/timeout
try:
    overpass_endpoint = os.getenv('OVERPASS_ENDPOINT')  # e.g. https://overpass-api.de/api/interpreter
    overpass_timeout = int(os.getenv('OVERPASS_TIMEOUT_SEC', '25'))
    api = overpass.API(endpoint=overpass_endpoint, timeout=overpass_timeout) if overpass_endpoint else overpass.API(timeout=overpass_timeout)
except Exception as e:
    logging.warning(f"Failed to initialize Overpass API: {e}")
    api = None

# Create a new API endpoint called '/register' that accepts POST requests
@app.route('/register', methods=['POST'])
def register():
    """Register a new user in Firebase Auth and create a Firestore profile document.
    Expects JSON: { "email": "user@example.com", "password": "secret" }
    """
    data = request.get_json() or {}
    email = data.get('email', '').strip()
    password = data.get('password', '')
    role = (data.get('role') or 'patient').strip().lower()
    display_name = (data.get('name') or data.get('display_name') or '').strip()
    mobile = (data.get('mobile') or data.get('phone') or '').strip()
    if role not in ('patient','doctor'):
        return jsonify({'error': 'Invalid role; must be patient or doctor'}), 400

    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400

    email_regex = r'^[^@\s]+@[^@\s]+\.[^@\s]+$'
    if not re.match(email_regex, email):
        return jsonify({'error': 'Invalid email format'}), 400

    # Basic password rules (Firebase only enforces length >=6, we can add light suggestions)
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    if password.lower() == password or password.upper() == password:
        # Not rejecting, just warning potential weakness
        pass

    try:
        user = auth.create_user(email=email, password=password, display_name=display_name or None)

        profile_created = False
        role_status = 'active'
        patient_id = None
        if role == 'doctor':
            # Newly registered doctors require verification
            role_status = 'pending'
        else:
            # Sequential patient ID like SS001, SS002 ... stored in a counter doc
            if db is not None:
                try:
                    counter_ref = db.collection('meta').document('counters')
                    def txn_counter(transaction):
                        snap = counter_ref.get(transaction=transaction)
                        data_ct = snap.to_dict() if snap.exists else {}
                        current = int(data_ct.get('patient_seq', 0)) + 1
                        transaction.set(counter_ref, {'patient_seq': current}, merge=True)
                        return current
                    # Firestore transaction
                    seq = db.transaction()(txn_counter)  # returns new integer
                    patient_id = f"SS{seq:03d}"
                except Exception:
                    # Fallback random pattern if transaction fails
                    patient_id = f"SS{random.randint(100,999)}"
        if db is not None:
            try:
                user_doc = {
                    'email': user.email,
                    'created_at': firestore.SERVER_TIMESTAMP,
                    'uid': user.uid,
                    'role': role,
                    'role_status': role_status
                }
                if patient_id:
                    user_doc['patient_id'] = patient_id
                if display_name:
                    user_doc['display_name'] = display_name
                if mobile:
                    user_doc['mobile'] = mobile
                db.collection('users').document(user.uid).set(user_doc, merge=True)
                if role == 'doctor':
                    # Add a doctors collection entry for admin review
                    db.collection('doctors').document(user.uid).set({
                        'uid': user.uid,
                        'email': user.email,
                        'status': 'pending',
                        'submitted_at': firestore.SERVER_TIMESTAMP,
                        'specialties': []
                    }, merge=True)
                profile_created = True
            except Exception as fe:
                logging.warning(f"Firestore profile creation failed for {user.uid}: {fe}")

        return jsonify({
            'success': True,
            'message': 'User created successfully',
            'uid': user.uid,
            'email': user.email,
            'profileCreated': profile_created,
            'role': role,
            'roleStatus': role_status,
            'patientId': patient_id,
            'displayName': display_name,
            'mobile': mobile
        }), 201

    except auth.EmailAlreadyExistsError:
        return jsonify({'error': 'Email already exists'}), 409
    except Exception as e:
        err_txt = str(e)
        if 'CONFIGURATION_NOT_FOUND' in err_txt:
            return jsonify({
                'error': 'Authentication provider not configured',
                'details': {
                    'hint': 'Enable Email/Password sign-in in Firebase Console > Authentication > Sign-in method.',
                    'check_service_account': 'Ensure serviceAccountKey.json project_id matches the Firebase project where you enabled the provider.',
                    'project_id_detected': getattr(firebase_admin.get_app().project_id, 'value', firebase_admin.get_app().project_id) if firebase_admin._apps else 'unknown'
                }
            }), 500
        logging.exception('Unexpected error during registration')
        return jsonify({'error': f'Registration failed: {err_txt}'}), 500

# ---------------- Helper: Retroactively assign sequential patient IDs -----------------
def _assign_patient_id_if_missing(uid: str):
    """If user is a patient without patient_id, assign next sequential ID.
    Returns the patient_id (existing or newly assigned) or None on failure."""
    if db is None or not uid:
        return None
    try:
        ref = db.collection('users').document(uid)
        snap = ref.get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        if data.get('role') != 'patient':
            return None
        existing = data.get('patient_id')
        if existing:
            return existing
        # Need to allocate new id
        counter_ref = db.collection('meta').document('counters')
        def txn_counter(transaction):
            csnap = counter_ref.get(transaction=transaction)
            cdata = csnap.to_dict() if csnap.exists else {}
            current = int(cdata.get('patient_seq', 0)) + 1
            transaction.set(counter_ref, {'patient_seq': current}, merge=True)
            return current
        try:
            seq = db.transaction()(txn_counter)
            new_pid = f"SS{seq:03d}"
        except Exception:
            new_pid = f"SS{random.randint(100,999)}"
        ref.set({'patient_id': new_pid}, merge=True)
        return new_pid
    except Exception as e:
        logging.warning(f"Failed assigning patient id for {uid}: {e}")
        return None

@app.route('/get_profile', methods=['POST'])
def get_profile():
    """Return a user's profile details (self-view). Expects JSON { uid }"""
    if db is None:
        return jsonify({'error':'Firestore not initialized'}), 500
    data = request.get_json() or {}
    uid = (data.get('uid') or '').strip()
    if not uid:
        return jsonify({'error':'uid required'}), 400
    try:
        snap = db.collection('users').document(uid).get()
        if not snap.exists:
            return jsonify({'error':'not found'}), 404
        rec = snap.to_dict() or {}
        # Retroactive patient id assignment
        if rec.get('role') == 'patient' and not rec.get('patient_id'):
            pid_new = _assign_patient_id_if_missing(uid)
            if pid_new:
                rec['patient_id'] = pid_new
        return jsonify({
            'success': True,
            'uid': uid,
            'email': rec.get('email'),
            'display_name': rec.get('display_name'),
            'patient_id': rec.get('patient_id'),
            'mobile': rec.get('mobile'),
            'role': rec.get('role'),
            'role_status': rec.get('role_status')
        }), 200
    except Exception as e:
        return jsonify({'error':'Failed to fetch profile','details': str(e)}), 500

@app.route('/update_profile', methods=['POST'])
def update_profile():
    """Allow a user (patient or doctor) to update limited profile fields: display_name, mobile.
    JSON: { uid: '', display_name?: '', mobile?: '' }
    Returns updated profile snapshot.
    """
    if db is None:
        return jsonify({'error':'Firestore not initialized'}), 500
    data = request.get_json() or {}
    uid = (data.get('uid') or '').strip()
    if not uid:
        return jsonify({'error':'uid required'}), 400
    display_name = (data.get('display_name') or data.get('name') or '').strip()
    mobile = (data.get('mobile') or '').strip()
    updates = {}
    if display_name:
        if len(display_name) < 2 or len(display_name) > 80:
            return jsonify({'error':'display_name must be 2-80 chars'}), 400
        updates['display_name'] = display_name
    if mobile:
        if len(mobile) < 7 or len(mobile) > 32:
            return jsonify({'error':'mobile length invalid'}), 400
        # Basic character whitelist
        if not re.match(r'^[0-9+()\-\s]+$', mobile):
            return jsonify({'error':'mobile contains invalid characters'}), 400
        updates['mobile'] = mobile
    if not updates:
        return jsonify({'error':'Nothing to update'}), 400
    try:
        user_ref = db.collection('users').document(uid)
        snap = user_ref.get()
        if not snap.exists:
            return jsonify({'error':'profile not found'}), 404
        user_ref.set(updates, merge=True)
        new_doc = user_ref.get().to_dict() or {}
        return jsonify({
            'success': True,
            'uid': uid,
            'email': new_doc.get('email'),
            'display_name': new_doc.get('display_name'),
            'mobile': new_doc.get('mobile'),
            'role': new_doc.get('role'),
            'patient_id': new_doc.get('patient_id')
        }), 200
    except Exception as e:
        return jsonify({'error':'Failed to update profile','details': str(e)}), 500

# Create another endpoint called '/login' that accepts POST requests
@app.route('/login', methods=['POST'])
def login():
    try:
        # For hackathon purposes, this is a simplified login
        # In production, you'd verify the password and generate custom tokens
        data = request.get_json()
        email = data.get('email')
        
        if not email:
            return jsonify({'error': 'Email is required'}), 400
        
        # Get user by email to return UID for client-side authentication
        user = auth.get_user_by_email(email)
        user_role = 'patient'
        role_status = 'active'
        patient_id = None
        if db is not None:
            try:
                doc = db.collection('users').document(user.uid).get()
                if doc.exists:
                    data_doc = doc.to_dict() or {}
                    r = (data_doc.get('role') or '').lower()
                    if r in ('patient','doctor'):
                        user_role = r
                    rs = (data_doc.get('role_status') or '').lower()
                    if rs in ('pending','active','rejected'):
                        role_status = rs
                    pid = data_doc.get('patient_id')
                    if isinstance(pid, str):
                        patient_id = pid
                    # Assign patient id retroactively if needed
                    if user_role == 'patient' and not patient_id:
                        patient_id = _assign_patient_id_if_missing(user.uid)
            except Exception:
                pass
        
        return jsonify({
            'success': True,
            'message': 'User found',
            'uid': user.uid,
            'email': user.email,
            'role': user_role,
            'roleStatus': role_status,
            'patientId': patient_id,
            'note': 'For hackathon: Use this UID in headers for authenticated requests'
        }), 200
        
    except auth.UserNotFoundError:
        return jsonify({'error': 'User not found'}), 404
    except Exception as e:
        return jsonify({'error': f'Login failed: {str(e)}'}), 500
    
@app.route('/chat', methods=['POST'])
def chat():
    """Enhanced personalized chat endpoint with greeting detection and improved medical responses.
    Expects JSON body: { "uid": "<user uid>", "message": "<user message>" }
    Features:
      1. Greeting and conversation detection
      2. Enhanced medical condition matching
      3. Improved response accuracy with confidence scoring
      4. Personalized responses based on health history
      5. Multi-language support
    """
    body = request.get_json() or {}
    uid = body.get('uid')
    user_message = (body.get('message') or '').strip()
    session_id = body.get('session_id')  # optional existing session id

    # Validate inputs
    if not uid:
        return jsonify({'error': 'Field "uid" is required in JSON body'}), 400
    if not user_message:
        return jsonify({'error': 'Field "message" is required in JSON body'}), 400

    try:
        # --- Optional Translation (Inbound) ---
        original_language = 'en'
        translated_inbound = False
        if TRANSLATION_AVAILABLE:
            try:
                original_language = heuristic_detect_indic(user_message)
                if original_language != 'en':
                    # Translate only if in supported Indic list
                    if original_language in SUPPORTED_INDIC_LANGS:
                        user_message = GoogleTranslator(source=original_language, target='en').translate(user_message)
                        translated_inbound = True
                    else:
                        original_language = 'en'
            except Exception as e:
                logging.warning(f'Translation failed: {e}')
                original_language = 'en'
                translated_inbound = False

        # --- Enhanced Greeting & Conversation Detection ---
        user_message_lower = user_message.lower().strip()
        
        # Check for greetings and common conversational patterns
        greeting_response = detect_greeting_or_conversation(user_message_lower, uid)
        if greeting_response:
            # Store greeting interaction in session
            if db is not None and uid:
                try:
                    sessions_ref = db.collection('users').document(uid).collection('chat_sessions')
                    if not session_id:
                        new_ref = sessions_ref.document()
                        new_ref.set({
                            'created_at': firestore.SERVER_TIMESTAMP,
                            'last_updated': firestore.SERVER_TIMESTAMP,
                            'major_issue': 'greeting/conversation',
                            'message_count': 0,
                            'title': 'General Conversation',
                            'title_auto': True
                        })
                        session_id = new_ref.id
                    
                    if session_id:
                        sess_doc_ref = sessions_ref.document(session_id)
                        msg_coll = sess_doc_ref.collection('messages')
                        now_server = firestore.SERVER_TIMESTAMP
                        msg_coll.add({'role': 'user', 'text': user_message, 'ts': now_server})
                        msg_coll.add({'role': 'bot', 'text': greeting_response, 'ts': now_server})
                        sess_doc_ref.set({'last_updated': firestore.SERVER_TIMESTAMP, 'message_count': firestore.Increment(2)}, merge=True)
                except Exception:
                    pass
            
            # Translate response back if needed
            final_response = greeting_response
            if TRANSLATION_AVAILABLE and original_language in SUPPORTED_INDIC_LANGS:
                try:
                    final_response = GoogleTranslator(source='en', target=original_language).translate(greeting_response)
                except Exception:
                    pass
            
            return jsonify({
                'message': final_response,
                'language': original_language,
                'translatedInbound': translated_inbound,
                'session_id': session_id,
                'matched_issues': ['conversation'],
                'conversation_type': 'greeting',
                'medical_sources': []
            }), 200

        # --- Step 1: Fetch User's Health History (symptoms only) ---
        past_symptoms = []
        if db is not None:
            try:
                docs = db.collection('users').document(uid).collection('health_history').stream()
                for d in docs:
                    rec = d.to_dict() or {}
                    symptom = rec.get('symptom')
                    if isinstance(symptom, str) and symptom.strip():
                        past_symptoms.append(symptom.strip().lower())
            except Exception:
                past_symptoms = []

        # --- Step 2: Normalize & Check for Recurring Symptoms ---
        user_message_lower = normalize_synonyms(user_message.lower())
        is_recurring = False
        for s in past_symptoms:
            if s and s in user_message_lower:
                is_recurring = True
                break

        # --- Step 3: Enhanced Multi-issue Keyword Logic with improved matching ---
        advice = None
        matched_entries = []  # list of (entry, matched_keywords_set)
        matched_issues_confidence = []
        confidence_scores = []
        
        cache_key = None
        if session_id:
            cache_key = f"sess:{session_id}:{hash(user_message_lower)}"
        else:
            cache_key = f"uid:{uid}:{hash(user_message_lower)}"
        
        if cache_key in SESSION_MATCH_CACHE:
            cached_data = SESSION_MATCH_CACHE[cache_key]
            matched_entries = cached_data['matched_entries']
            confidence_scores = cached_data.get('confidence_scores', [])
        else:
            try:
                # Enhanced keyword matching with scoring
                if isinstance(responses, dict):
                    for keyword, text in responses.items():
                        if keyword:
                            normalized_keyword = normalize_synonyms(keyword.lower())
                            if normalized_keyword in user_message_lower:
                                # Calculate match confidence based on keyword length and context
                                confidence = calculate_match_confidence(keyword, user_message_lower, user_message)
                                matched_entries.append(({ 'advice': text, 'keywords': [keyword] }, { keyword.lower() }))
                                confidence_scores.append(confidence)
                elif isinstance(responses, list):
                    for entry in responses:
                        if not isinstance(entry, dict):
                            continue
                        kws = entry.get('keywords') or []
                        hit = set()
                        match_confidence = 0.0
                        
                        for kw in kws:
                            if not isinstance(kw, str):
                                continue
                            kwl = normalize_synonyms(kw.lower().strip())
                            if kwl and kwl in user_message_lower:
                                hit.add(kwl)
                                # Calculate confidence based on keyword specificity and match quality
                                kw_confidence = calculate_match_confidence(kw, user_message_lower, user_message)
                                match_confidence = max(match_confidence, kw_confidence)
                        
                        if hit:
                            matched_entries.append((entry, hit))
                            confidence_scores.append(match_confidence)
                            
            except Exception as kw_err:
                logging.warning(f'Keyword matching failed: {kw_err}')
            
            SESSION_MATCH_CACHE[cache_key] = { 
                'matched_entries': matched_entries,
                'confidence_scores': confidence_scores
            }

        # Enhanced detection for critical medical terms
        if not matched_entries:
            critical_terms = {
                # Emergency conditions
                'chest pain': 'cardiac emergency',
                'heart attack': 'cardiac emergency', 
                'stroke': 'stroke symptoms',
                'seizure': 'seizure',
                'unconscious': 'emergency condition',
                'severe allergic reaction': 'severe allergic reaction',
                'anaphylaxis': 'severe allergic reaction',
                'poisoning': 'poisoning',
                'overdose': 'poisoning',
                'choking': 'emergency condition',
                # Women's health
                'vaginal bleeding': 'gynecological issue',
                'vaginal discharge': 'gynecological issue', 
                'bleeding': 'vaginal bleeding' if any(term in user_message_lower for term in ['vaginal', 'period', 'menstrual']) else None,
                'pelvic pain': 'gynecological issue',
                'period': 'menstrual problem',
                'menstrual': 'menstrual problem',
                'irregular period': 'menstrual problem',
                'heavy period': 'menstrual problem',
                'missed period': 'reproductive health',
                # Mental health
                'suicidal': 'depression',
                'suicide': 'depression',
                'depression': 'depression',
                'anxiety': 'anxiety',
                'panic attack': 'anxiety',
                # Other critical terms
                'diabetes': 'diabetes',
                'blood sugar': 'diabetes',
                'fracture': 'fracture',
                'broken bone': 'fracture',
                'memory loss': 'memory problem',
                'confusion': 'memory problem'
            }
            
            for term, category in critical_terms.items():
                if category and term in user_message_lower:
                    # Create a synthetic entry for this critical term
                    advice_text = HF_LABEL_ADVICE.get(category, HF_LABEL_ADVICE['unknown'])
                    entry = {
                        'advice': advice_text,
                        'keywords': [term],
                        'source': 'critical_detection'
                    }
                    matched_entries.append((entry, {term}))
                    break
        
        combined = []
        matched_issues = []
        zero_shot_used = False
        # If no direct keyword matches, attempt zero-shot classification
        if not matched_entries:
            zs_results = hf_zero_shot_categories(user_message_lower)
            if zs_results:
                # Only use zero-shot results if we have reasonably confident matches
                # or if the top match is a generic/safe category
                top_label, top_score = zs_results[0]
                use_zs = (top_score >= 0.25 or 
                         top_label in ['unknown', 'general health concern', 'fever', 'headache', 'cough', 'cold', 'gynecological issue', 'menstrual problem', 'reproductive health'] or
                         any(score >= 0.3 for _, score in zs_results))
                
                if use_zs:
                    zero_shot_used = True
                    for label, score in zs_results[:3]:
                        label_norm = label.lower()
                        advice_text = HF_LABEL_ADVICE.get(label_norm, HF_LABEL_ADVICE['unknown'])
                        entry = {
                            'advice': advice_text,
                            'keywords': [label_norm],
                            'source': 'zero_shot',
                            '_zs_confidence': float(score)
                        }
                        matched_entries.append((entry, {label_norm}))
        if matched_entries:
            # Enhanced ranking with confidence scores
            if confidence_scores and len(confidence_scores) == len(matched_entries):
                # Sort by confidence score primarily, then by keyword match quality
                combined_ranking = list(zip(matched_entries, confidence_scores))
                combined_ranking.sort(key=lambda x: (-x[1], -len(x[0][1]) if isinstance(x[0], tuple) else 0))
                matched_entries = [item[0] for item in combined_ranking]
                confidence_scores = [item[1] for item in combined_ranking]
            else:
                # Fallback to original ranking method
                def rank_item(tup):
                    entry, hitset = tup
                    longest = max((len(h) for h in hitset), default=0)
                    return (-len(hitset), -longest)
                matched_entries.sort(key=rank_item)
            
            # Process top matches with enhanced response generation
            for i, (entry, hitset) in enumerate(matched_entries[:3]):
                raw_advice = (entry.get('advice') or '').strip()
                if not raw_advice:
                    continue
                
                source_kws = [normalize_synonyms(k.lower().strip()) for k in (entry.get('keywords') or []) if isinstance(k,str)]
                if hitset:
                    label = max(hitset, key=len)
                elif source_kws:
                    label = source_kws[0]
                else:
                    label = 'health concern'
                
                # Use calculated confidence if available
                if i < len(confidence_scores):
                    confidence = confidence_scores[i]
                else:
                    # Fallback confidence calculation
                    denom = max(len(source_kws), len(hitset), 1)
                    avg_len = sum(len(h) for h in hitset)/max(1,len(hitset))
                    confidence = min(0.99, (len(hitset)/denom) * (0.6 + 0.4 * min(1.0, avg_len/12)))
                
                # Override/blend with zero-shot confidence if present
                if '_zs_confidence' in entry:
                    confidence = max(confidence, float(entry.get('_zs_confidence') or 0.0))
                
                matched_issues.append(label)
                matched_issues_confidence.append((label, confidence))
                
                # Enhanced advice with confidence indicators
                enhanced_raw_advice = raw_advice
                
                # Add confidence indicators
                if confidence < 0.3:
                    confidence_indicator = " <em style='color:#ff9800;font-size:0.8em'>(Low confidence - please verify with a healthcare professional)</em>"
                elif confidence < 0.6:
                    confidence_indicator = " <em style='color:#2196F3;font-size:0.8em'>(Moderate confidence)</em>"
                else:
                    confidence_indicator = " <em style='color:#4CAF50;font-size:0.8em'>(High confidence)</em>"
                
                # Add emergency warnings for critical symptoms
                critical_keywords = ['chest pain', 'heart attack', 'stroke', 'seizure', 'poisoning', 'severe allergic reaction', 'breathing difficulty']
                is_emergency = any(kw in label.lower() or kw in raw_advice.lower() for kw in critical_keywords)
                
                if is_emergency:
                    enhanced_raw_advice = f"🚨 <strong>EMERGENCY ALERT:</strong> {raw_advice}<br><br>⚡ <strong>If this is a medical emergency, call emergency services immediately!</strong>"
                
                if entry.get('source') == 'zero_shot':
                    combined.append(f"<li><strong>{label.title()}</strong> <em style='font-size:0.75em;color:#666'>(AI inferred)</em>{confidence_indicator}<br>{enhanced_raw_advice}</li>")
                else:
                    combined.append(f"<li><strong>{label.title()}</strong>{confidence_indicator}<br>{enhanced_raw_advice}</li>")
            
            if combined:
                if len(combined) > 1:
                    advice = "<div><p><strong>Multiple health concerns identified:</strong></p><ul>" + "".join(combined) + "</ul></div>"
                else:
                    # Single issue - cleaner presentation
                    advice = combined[0].replace('<li><strong>', '').replace('</strong>', '').replace('</li>', '').replace('<br>', '\n\n')
                    advice = f"<div>{advice}</div>"

        # --- Step 3b: Enhanced Intelligent Fallback if no predefined advice matched ---
        fallback_summary = None
        if not advice:
            # Enhanced symptom and body part detection
            body_terms = {
                'head','headache','skull','brain','scalp',
                'stomach','abdominal','belly','abdomen','gut','tummy',
                'chest','lungs','heart','breast','ribs',
                'throat','neck','voice','larynx','pharynx',
                'eye','eyes','vision','sight','eyelid',
                'ear','ears','hearing','eardrum',
                'skin','rash','itch','dermatitis','eczema',
                'back','spine','spinal','lumbar','vertebrae',
                'leg','legs','knee','knees','ankle','foot','feet','toe','toes',
                'arm','arms','shoulder','elbow','wrist','hand','hands','finger','fingers',
                'mouth','lips','tongue','teeth','gums','jaw',
                'nose','nostril','sinus','nasal',
                'breath','breathing','lungs','airways'
            }
            
            symptom_terms = {
                'pain','ache','aching','hurt','hurting','sore','tender',
                'fever','temperature','hot','burning','chills',
                'cough','coughing','wheezing','sneezing',
                'nausea','vomiting','vomit','throwing up','sick',
                'diarrhea','constipation','bowel','stool',
                'dizziness','dizzy','lightheaded','faint','fainting',
                'tired','fatigue','exhausted','weak','weakness',
                'swelling','swollen','inflammation','bloated',
                'bleeding','blood','bruise','bruising',
                'infection','infected','pus','discharge'
            }
            
            tokens = re.findall(r'[a-zA-Z]{3,}', user_message_lower)
            body_parts = []
            symptoms = []
            
            for i, tok in enumerate(tokens):
                if tok in body_terms:
                    prev = tokens[i-1] if i > 0 else ''
                    next_tok = tokens[i+1] if i < len(tokens)-1 else ''
                    context = f"{prev} {tok} {next_tok}".strip()
                    body_parts.append(context if len(context.split()) <= 3 else tok)
                
                if tok in symptom_terms:
                    prev = tokens[i-1] if i > 0 else ''
                    next_tok = tokens[i+1] if i < len(tokens)-1 else ''
                    context = f"{prev} {tok} {next_tok}".strip()
                    symptoms.append(context if len(context.split()) <= 3 else tok)
            
            # Remove duplicates while preserving order
            body_parts = list(dict.fromkeys(body_parts))[:3]
            symptoms = list(dict.fromkeys(symptoms))[:3]
            
            # Enhanced fallback advice based on detected elements
            base_fallback = "I understand you're experiencing health concerns. "
            
            if body_parts and symptoms:
                base_fallback += f"Based on your description mentioning {', '.join(body_parts)} and symptoms like {', '.join(symptoms)}, here's some general guidance:\n\n"
            elif body_parts:
                base_fallback += f"I notice you mentioned issues with {', '.join(body_parts)}. "
            elif symptoms:
                base_fallback += f"I see you're experiencing {', '.join(symptoms)}. "
            
            # Provide specific advice based on detected symptoms
            emergency_symptoms = ['chest pain', 'breathing', 'seizure', 'unconscious', 'severe pain', 'blood', 'poisoning']
            has_emergency = any(term in user_message_lower for term in emergency_symptoms)
            
            if has_emergency:
                base_fallback += "\n🚨 **IMPORTANT**: Based on your symptoms, this could require immediate medical attention. If you're experiencing severe symptoms, difficulty breathing, chest pain, or any life-threatening conditions, please call emergency services immediately or go to the nearest emergency room.\n\n"
            
            # General health advice
            base_fallback += "**General recommendations:**\n"
            base_fallback += "• Monitor your symptoms closely and note any changes\n"
            base_fallback += "• Rest and stay well-hydrated\n"
            base_fallback += "• Avoid self-medication without proper guidance\n"
            base_fallback += "• Maintain good hygiene and nutrition\n\n"
            
            base_fallback += "**Seek immediate medical care if you experience:**\n"
            base_fallback += "• Severe or worsening pain\n"
            base_fallback += "• High fever (over 102°F/39°C)\n"
            base_fallback += "• Difficulty breathing or chest pain\n"
            base_fallback += "• Persistent vomiting or signs of dehydration\n"
            base_fallback += "• Any bleeding or injury\n"
            base_fallback += "• Symptoms that persist more than 2-3 days\n\n"
            
            base_fallback += "💡 **Remember**: I can provide general health information, but I cannot replace professional medical diagnosis and treatment. When in doubt, always consult with a qualified healthcare provider."
            
            advice = base_fallback

        # --- Step 3c: Enhance with MedlinePlus Medical Knowledge ---
        medlineplus_enhancement = None
        medical_sources = []
        try:
            if MEDLINEPLUS_AVAILABLE and matched_issues:
                # Use detected conditions for enhancement
                enhancement = enhance_chatbot_response(user_message, matched_issues)
                if enhancement.get('confidence_boost') and enhancement.get('authoritative_summary'):
                    medlineplus_enhancement = enhancement['authoritative_summary']
                    medical_sources = enhancement.get('medical_sources', [])
                    
                    # Append authoritative information to advice
                    if medlineplus_enhancement:
                        advice += f"\n\n<div style='border-left: 3px solid #2196F3; padding-left: 10px; margin: 10px 0;'>"
                        advice += f"<strong>📚 Medical Information (MedlinePlus):</strong><br>"
                        advice += f"{medlineplus_enhancement}"
                        if medical_sources and medical_sources[0].get('url'):
                            advice += f"<br><br><a href='{medical_sources[0]['url']}' target='_blank' style='color: #2196F3;'>→ Read more on MedlinePlus</a>"
                        advice += "</div>"
        except Exception as e:
            logging.warning(f'MedlinePlus enhancement failed: {e}')

        # --- Step 4: Personalize the Response ---
        if advice and is_recurring:
            personalized_prefix = (
                "<p><em>I see from your history that you've experienced this before. Please monitor your symptoms and seek professional help if they persist or worsen.</em></p>"
            )
            advice = personalized_prefix + advice

        # --- Step 5: Return the Final Response ---
        if not advice:
            # Friendly fallback for unclear or unsupported queries
            if detect_greeting_or_conversation(user_message_lower, uid):
                advice = detect_greeting_or_conversation(user_message_lower, uid)
            else:
                advice = (
                    "I'm here to help with health and wellness questions! "
                    "If you have a health concern, symptom, or want to know about healthy living, just ask. "
                    "For non-health topics, I may not be able to help, but I'm always here for your health queries."
                )
        # --- Optional Translation (Outbound) ---
        if TRANSLATION_AVAILABLE and original_language in SUPPORTED_INDIC_LANGS:
            try:
                advice_translated = GoogleTranslator(source='en', target=original_language).translate(advice)
                advice = advice_translated
            except Exception:
                pass

        # ---- Persist chat session & messages (prototype) ----
        stored_session_id = session_id
        if db is not None and uid:
            try:
                sessions_ref = db.collection('users').document(uid).collection('chat_sessions')
                # Create session document if not provided
                if not stored_session_id:
                    new_ref = sessions_ref.document()
                    title_candidate = user_message.strip().split('\n')[0][:80] if user_message else None
                    new_ref.set({
                        'created_at': firestore.SERVER_TIMESTAMP,
                        'last_updated': firestore.SERVER_TIMESTAMP,
                        'major_issue': None,
                        'message_count': 0,
                        'title': title_candidate,
                        'title_auto': True
                    })
                    stored_session_id = new_ref.id
                # Append user + bot messages
                if stored_session_id:
                    sess_doc_ref = sessions_ref.document(stored_session_id)
                    msg_coll = sess_doc_ref.collection('messages')
                    now_server = firestore.SERVER_TIMESTAMP
                    msg_coll.add({'role': 'user', 'text': user_message, 'ts': now_server})
                    msg_coll.add({'role': 'bot', 'text': advice, 'ts': now_server})
                    sess_doc_ref.set({'last_updated': firestore.SERVER_TIMESTAMP, 'message_count': firestore.Increment(2)}, merge=True)
            except Exception:
                pass

        return jsonify({
            'message': advice,
            'language': original_language,
            'translatedInbound': translated_inbound,
            'session_id': stored_session_id,
            'matched_issues': matched_issues,
            'issue_confidence': [ {'issue': i, 'confidence': round(c,4)} for i,c in matched_issues_confidence ],
            'fallback_used': (not bool(matched_issues)) and (not zero_shot_used),
            'zero_shot_used': zero_shot_used,
            'medlineplus_enhanced': bool(medlineplus_enhancement),
            'medical_sources': medical_sources[:2] if medical_sources else []  # Limit to 2 sources for response size
        }), 200

    except Exception as e:
        import traceback
        logging.exception('Chat processing failure')
        error_details = f"{type(e).__name__}: {str(e)}"
        logging.error(f"Full traceback: {traceback.format_exc()}")
        return jsonify({'error': 'Failed to process chat', 'details': error_details}), 500

@app.route('/analyze_chat_session', methods=['POST'])
@cross_origin(origins='*', methods=['POST','OPTIONS'], allow_headers=['Content-Type','Authorization','X-Requested-With'])
def analyze_chat_session():
    """Analyze a chat session (list of messages) to detect a major health issue.
    Expects JSON: {
       "uid": "...", 
       "messages": [ {"role": "user|bot|doctor", "text": "..."}, ... ],
       "save": true|false
    }
    Heuristic: use user (and doctor) messages, frequency of medical keywords, map to known response keys.
    Stores a health_history record if 'save' true or default (true).
    """
    data = request.get_json() or {}
    uid = data.get('uid')
    messages = data.get('messages')
    save = data.get('save', True)
    supplied_major_issue = (data.get('major_issue') or '').strip()
    session_id = data.get('session_id')  # optional: update chat session doc when saving
    if not uid:
        return jsonify({'error': 'Field "uid" is required'}), 400

    # Save-only shortcut (e.g. confirm on client) if major_issue provided without messages
    if (not messages or not isinstance(messages, list) or len(messages)==0) and supplied_major_issue and save:
        if db is None:
            return jsonify({'error': 'Firestore not initialized'}), 500
        try:
            user_doc_ref = db.collection('users').document(uid)
            health_history_ref = user_doc_ref.collection('health_history')
            doc_ref = health_history_ref.document()
            doc_ref.set({
                'symptom': supplied_major_issue.title(),
                'source': 'chat_session_manual_confirm',
                'created_at': firestore.SERVER_TIMESTAMP
            })
            # Update chat session doc if provided
            if session_id:
                try:
                    sess_ref = db.collection('users').document(uid).collection('chat_sessions').document(session_id)
                    sess_ref.set({'major_issue': supplied_major_issue.title(), 'summary_excerpt': supplied_major_issue.title(), 'analyzed_at': firestore.SERVER_TIMESTAMP}, merge=True)
                except Exception:
                    pass
            return jsonify({'success': True, 'major_issue': supplied_major_issue, 'saved': True, 'record_id': doc_ref.id, 'confidence': None, 'mode': 'manual_confirm'}), 200
        except Exception as e:
            return jsonify({'error': 'Failed to save record', 'details': str(e)}), 500

    if not isinstance(messages, list) or not messages:
        return jsonify({'error': 'Field "messages" (non-empty list) required unless using save-only with major_issue'}), 400

    raw_texts = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = (m.get('role') or '').lower()
        if role in ('user','doctor','physician'):
            txt = (m.get('text') or '').strip()
            if txt:
                raw_texts.append(txt)
    full_text = '\n'.join(raw_texts)
    if not full_text:
        return jsonify({'error': 'No analyzable user/doctor content'}), 400

    # Token frequency
    tokens = re.findall(r'[a-zA-Z]{3,}', full_text.lower())
    STOP = {
        'this','that','with','have','having','about','which','from','will','would','could','there','their','been','were','your','into','what','when','where','them','they','some','more','just','said','also','like','feel','feeling','felt','pain','pains','ache','aches','very','really','still','since','because','after','before','been','getting','going','over','under','around','mine','ours','yours','hers','his','its','okay','please','help','issue','problem','problems','doctor','need','want'
    }
    freq = {}
    for t in tokens:
        if t in STOP:
            continue
        freq[t] = freq.get(t, 0) + 1

    # Match against known response keywords (list-based structure supported)
    candidate_scores = {}
    if isinstance(responses, dict):
        iterable_items = [(k, {'keywords':[k]}) for k in responses.keys()]
    else:
        iterable_items = []
        if isinstance(responses, list):
            for entry in responses:
                if isinstance(entry, dict):
                    kws = entry.get('keywords') or []
                    # Flatten each keyword as candidate label
                    for kw in kws:
                        if isinstance(kw, str):
                            iterable_items.append((kw, entry))
    for key, entry in iterable_items:
        k_low = key.lower().strip()
        if not k_low:
            continue
        score = 0
        if k_low in freq:
            score += freq[k_low] * 3
        parts = re.findall(r'[a-zA-Z]+', k_low)
        overlap = sum(freq.get(p,0) for p in parts)
        score += overlap
        if score > 0:
            # Use the canonical advice label: prefer first keyword of entry
            label = k_low
            if isinstance(entry, dict):
                ekws = entry.get('keywords') or []
                if ekws and isinstance(ekws[0], str):
                    label = ekws[0].lower()
            candidate_scores[label] = max(candidate_scores.get(label,0), score)

    major_issue = None
    top_scores_sorted = []
    if candidate_scores:
        top_scores_sorted = sorted(candidate_scores.items(), key=lambda x: x[1], reverse=True)
        major_issue = top_scores_sorted[0][0]
    else:
        if freq:
            major_issue = max(freq.items(), key=lambda x: x[1])[0]

    if not major_issue:
        return jsonify({'error': 'Unable to extract major issue'}), 200

    # Confidence calculation
    confidence = None
    major_score = candidate_scores.get(major_issue, None) if candidate_scores else None
    if top_scores_sorted and len(top_scores_sorted) == 1:
        confidence = 1.0
    elif top_scores_sorted and len(top_scores_sorted) > 1:
        s1 = float(top_scores_sorted[0][1])
        s2 = float(top_scores_sorted[1][1])
        confidence = round(s1 / (s1 + s2 + 1e-6), 4)  # conservative

    # Evidence tokens: tokens contributing to major_issue + top frequency tokens
    evidence_tokens = []
    if candidate_scores and major_issue:
        parts = re.findall(r'[a-zA-Z]+', major_issue.lower())
        for p in parts:
            if p in freq and p not in evidence_tokens:
                evidence_tokens.append(p)
    # add top freq tokens (up to 10) excluding already included
    for t,_cnt in sorted(freq.items(), key=lambda x: x[1], reverse=True)[:10]:
        if t not in evidence_tokens:
            evidence_tokens.append(t)

    saved = False
    record_id = None
    if save and db is not None:
        try:
            user_doc_ref = db.collection('users').document(uid)
            health_history_ref = user_doc_ref.collection('health_history')
            snippet = full_text[:240] + ('...' if len(full_text) > 240 else '')
            doc_ref = health_history_ref.document()
            doc_ref.set({
                'symptom': major_issue.title(),
                'source': 'chat_session_analysis',
                'analysis_score': major_score,
                'confidence': confidence,
                'raw_token_count': len(tokens),
                'summary_excerpt': snippet,
                'evidence_tokens': evidence_tokens,
                'created_at': firestore.SERVER_TIMESTAMP
            })
            saved = True
            record_id = doc_ref.id
            # Update chat session doc
            if session_id:
                try:
                    sess_ref = user_doc_ref.collection('chat_sessions').document(session_id)
                    sess_ref.set({
                        'major_issue': major_issue.title(),
                        'confidence': confidence,
                        'analysis_score': major_score,
                        'summary_excerpt': snippet,
                        'evidence_tokens': evidence_tokens,
                        'analyzed_at': firestore.SERVER_TIMESTAMP
                    }, merge=True)
                except Exception:
                    pass
        except Exception as e:
            logging.warning(f'Failed to save analyzed issue: {e}')

    return jsonify({
        'success': True,
        'major_issue': major_issue,
        'major_issue_score': major_score,
        'confidence': confidence,
        'candidate_scores_top': top_scores_sorted[:5],
        'evidence_tokens': evidence_tokens,
        'saved': saved,
        'record_id': record_id,
        'mode': 'analysis'
    }), 200

# ---------------- MedlinePlus Medical Information Endpoints ----------------
@app.route('/search_medical_info', methods=['POST'])
@cross_origin(origins='*', methods=['POST','OPTIONS'], allow_headers=['Content-Type','Authorization','X-Requested-With'])
def search_medical_info():
    """
    Search authoritative medical information from MedlinePlus
    Expects JSON: {
        "query": "search term",
        "max_results": 5 (optional, default 3)
    }
    Returns medical information from NIH MedlinePlus database
    """
    try:
        if not MEDLINEPLUS_AVAILABLE:
            return jsonify({
                'success': False,
                'query': None,
                'results': [],
                'message': 'MedlinePlus integration not available. Medical information cannot be retrieved at this time.',
                'source': None,
                'disclaimer': 'This information is provided for educational purposes only and should not replace professional medical advice.'
            }), 200

        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'query': None,
                'results': [],
                'message': 'Invalid JSON in request body.',
                'source': None,
                'disclaimer': 'This information is provided for educational purposes only and should not replace professional medical advice.'
            }), 200

        query = data.get('query', '').strip()
        if not query:
            return jsonify({
                'success': False,
                'query': None,
                'results': [],
                'message': 'Query parameter is required.',
                'source': None,
                'disclaimer': 'This information is provided for educational purposes only and should not replace professional medical advice.'
            }), 200

        max_results = min(data.get('max_results', 3), 10)  # Limit to prevent abuse

        # Get medical information from MedlinePlus
        try:
            medical_info = get_medical_info(query, max_results)
        except Exception as e:
            logging.exception('MedlinePlus get_medical_info failed')
            medical_info = []

        if not medical_info:
            return jsonify({
                'success': True,
                'query': query,
                'results': [],
                'message': 'No medical information found for this query. Please try a different search term or consult a healthcare professional.',
                'source': 'MedlinePlus (NIH)',
                'disclaimer': 'This information is provided for educational purposes only and should not replace professional medical advice.'
            }), 200

        return jsonify({
            'success': True,
            'query': query,
            'results': medical_info,
            'source': 'MedlinePlus (NIH)',
            'disclaimer': 'This information is provided for educational purposes only and should not replace professional medical advice.'
        }), 200

    except Exception as e:
        logging.exception('Medical info search failed (outer catch)')
        return jsonify({
            'success': False,
            'query': None,
            'results': [],
            'message': 'An unexpected error occurred while searching for medical information.',
            'details': str(e),
            'source': None,
            'disclaimer': 'This information is provided for educational purposes only and should not replace professional medical advice.'
        }), 200

@app.route('/get_condition_info', methods=['POST'])
@cross_origin(origins='*', methods=['POST','OPTIONS'], allow_headers=['Content-Type','Authorization','X-Requested-With'])
def get_condition_info():
    """
    Get detailed information about a specific medical condition
    Expects JSON: {
        "condition": "diabetes",
        "include_genetics": false (optional)
    }
    Returns comprehensive medical information
    """
    try:
        if not MEDLINEPLUS_AVAILABLE:
            return jsonify({'error': 'MedlinePlus integration not available'}), 503
            
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid JSON in request body'}), 400
        
        condition = data.get('condition', '').strip()
        if not condition:
            return jsonify({'error': 'Condition parameter is required'}), 400
        
        include_genetics = data.get('include_genetics', False)
        
        # Get basic medical information
        medical_info = get_medical_info(condition, max_results=3)
        
        response_data = {
            'success': True,
            'condition': condition,
            'medical_info': medical_info,
            'source': 'MedlinePlus (NIH)',
            'genetics_info': None
        }
        
        # Optionally include genetics information
        if include_genetics:
            try:
                # Convert condition to URL-friendly format
                condition_slug = condition.lower().replace(' ', '-').replace('_', '-')
                genetics_info = medical_enhancer.medlineplus.get_genetic_condition_info(condition_slug)
                response_data['genetics_info'] = genetics_info
            except Exception as e:
                logging.warning(f'Failed to get genetics info for {condition}: {e}')
        
        return jsonify(response_data), 200
        
    except Exception as e:
        logging.exception('Condition info lookup failed')
        return jsonify({'error': 'Failed to get condition information', 'details': str(e)}), 500

# ---------------- Health Record Endpoints ----------------
@app.route('/add_health_record', methods=['POST'])
def add_health_record():
    """Add a new health record for a user.
    Expects JSON body:
    {
      "uid": "<user uid>",
      "record": {"symptom": "Fever", "date": "2025-10-03", "doctor_notes": "Prescribed Paracetamol"}
    }
    """
    if db is None:
        return jsonify({'error': 'Firestore not initialized'}), 500

    data = request.get_json() or {}
    uid = data.get('uid')  # target patient/user id
    actor_uid = data.get('actor_uid') or uid  # who is performing the action
    record = data.get('record')

    # Validate inputs
    if not uid:
        return jsonify({'error': 'Field "uid" is required in JSON body'}), 400
    if not isinstance(record, dict) or not record:
        return jsonify({'error': 'Field "record" (non-empty object) is required in JSON body'}), 400

    # Authorization: only doctors may create records (patients cannot self-add)
    try:
        actor_doc = db.collection('users').document(actor_uid).get()
        if not actor_doc.exists or (actor_doc.to_dict() or {}).get('role') != 'doctor':
            return jsonify({'error': 'Only doctors can add health records'}), 403
        # Reference to user document: users/{uid}
        user_doc_ref = db.collection('users').document(uid)
        # Subcollection health_history
        health_history_ref = user_doc_ref.collection('health_history')
        # Normalize / enrich record
        record.setdefault('created_at', firestore.SERVER_TIMESTAMP)
        # Add new document with auto-generated ID
        new_doc_ref = health_history_ref.document()
        new_doc_ref.set(record)
        return jsonify({
            'success': True,
            'message': 'Health record added',
            'id': new_doc_ref.id
        }), 201
    except Exception as e:
        logging.exception('Failed to add health record')
        return jsonify({'error': 'Failed to add health record', 'details': str(e)}), 500

@app.route('/get_health_history', methods=['POST'])
def get_health_history():
    """Fetch a user's full health history via POST.
    Expects JSON body: { "uid": "<user uid>" }
    Acts like a GET but uses POST so the UID isn't exposed in URL/query params.
    """
    if db is None:
        return jsonify({'error': 'Firestore not initialized'}), 500

    data = request.get_json() or {}
    uid = data.get('uid')
    if not uid:
        return jsonify({'error': 'Field "uid" is required in JSON body'}), 400

    try:
        user_doc_ref = db.collection('users').document(uid)
        health_history_ref = user_doc_ref.collection('health_history')
        docs = health_history_ref.stream()
        records = []
        for d in docs:
            rec = d.to_dict() or {}
            rec['id'] = d.id  # include document ID for future delete/update operations
            records.append(rec)
        return jsonify({'success': True, 'count': len(records), 'records': records}), 200
    except Exception:
        # Generic error per specification (avoid leaking internal details)
        return jsonify({'error': 'Failed to fetch health history'}), 500

# ---- Helper: automatic analysis for a chat session when switching/ending ----
def auto_analyze_and_store(uid: str, session_id: str):
    """Server-side automatic analysis of a stored chat session.
    Reads the last ~100 messages from users/{uid}/chat_sessions/{session_id}/messages
    Runs same heuristic as analyze_chat_session (lightweight subset) and stores result if found.
    Idempotent: will not overwrite existing major_issue in session doc.
    """
    if db is None or not uid or not session_id:
        return None

@app.route('/auto_analyze_session', methods=['POST'])
def auto_analyze_session():
    if db is None:
        return jsonify({'error':'Firestore not initialized'}), 500
    data = request.get_json() or {}
    uid = data.get('uid')
    session_id = data.get('session_id')
    if not uid or not session_id:
        return jsonify({'error':'uid and session_id required'}), 400
    issue = auto_analyze_and_store(uid, session_id)
    return jsonify({'success': True, 'major_issue': issue}), 200
    try:
        sess_ref = db.collection('users').document(uid).collection('chat_sessions').document(session_id)
        sess_snap = sess_ref.get()
        if not sess_snap.exists:
            return None
        if (sess_snap.to_dict() or {}).get('major_issue'):
            return None  # already analyzed / saved
        msgs_coll = sess_ref.collection('messages').order_by('ts').limit(100).stream()
        corpus = []
        for m in msgs_coll:
            md = m.to_dict() or {}
            if md.get('role') in ('user','doctor','bot'):
                corpus.append(md.get('text',''))
        joined = ' '.join(corpus)[:8000]
        if not joined.strip():
            return None
        # Very light heuristic: reuse existing keyword mapping from responses keys
        best_issue = None; best_score = 0
        for key in responses.keys():
            pat = re.compile(r'\b' + re.escape(key.lower()) + r'\b')
            hits = len(pat.findall(joined.lower()))
            if hits > best_score:
                best_score = hits
                best_issue = key
        if not best_issue:
            return None
        # Store to health history
        hh_ref = db.collection('users').document(uid).collection('health_history').document()
        hh_ref.set({
            'symptom': best_issue.title(),
            'source': 'chat_session_auto',
            'auto': True,
            'created_at': firestore.SERVER_TIMESTAMP
        })
        sess_ref.set({'major_issue': best_issue.title(), 'analyzed_at': firestore.SERVER_TIMESTAMP}, merge=True)
        return best_issue
    except Exception:
        return None

@app.route('/delete_health_record', methods=['POST'])
def delete_health_record():
    """Delete a health history record.
    Expects JSON: { "uid": "..", "id": "recordDocId" }
    """
    if db is None:
        return jsonify({'error': 'Firestore not initialized'}), 500
    data = request.get_json() or {}
    uid = data.get('uid')
    actor_uid = data.get('actor_uid') or uid
    rec_id = data.get('id')
    if not uid or not rec_id:
        return jsonify({'error': 'Fields "uid" and "id" are required'}), 400
    try:
        actor_doc = db.collection('users').document(actor_uid).get()
        if not actor_doc.exists or (actor_doc.to_dict() or {}).get('role') != 'doctor':
            return jsonify({'error': 'Only doctors can delete records'}), 403
        ref = db.collection('users').document(uid).collection('health_history').document(rec_id)
        if not ref.get().exists:
            return jsonify({'error': 'Record not found'}), 404
        ref.delete()
        return jsonify({'success': True, 'message': 'Record deleted'}), 200
    except Exception as e:
        return jsonify({'error': 'Failed to delete record', 'details': str(e)}), 500

@app.route('/update_health_record', methods=['POST'])
def update_health_record():
    """Update specific fields of a health history record.
    Expects JSON: { "uid": "..", "id": "recordDocId", "updates": { ... } }
    """
    if db is None:
        return jsonify({'error': 'Firestore not initialized'}), 500
    data = request.get_json() or {}
    uid = data.get('uid')
    actor_uid = data.get('actor_uid') or uid
    rec_id = data.get('id')
    updates = data.get('updates') or {}
    if not uid or not rec_id:
        return jsonify({'error': 'Fields "uid" and "id" are required'}), 400
    if not isinstance(updates, dict) or not updates:
        return jsonify({'error': 'Field "updates" (non-empty object) is required'}), 400
    try:
        actor_doc = db.collection('users').document(actor_uid).get()
        if not actor_doc.exists or (actor_doc.to_dict() or {}).get('role') != 'doctor':
            return jsonify({'error': 'Only doctors can update records'}), 403
        ref = db.collection('users').document(uid).collection('health_history').document(rec_id)
        if not ref.get().exists:
            return jsonify({'error': 'Record not found'}), 404
        ref.set(updates, merge=True)
        return jsonify({'success': True, 'message': 'Record updated'}), 200
    except Exception as e:
        return jsonify({'error': 'Failed to update record', 'details': str(e)}), 500

@app.route('/schedule_appointment', methods=['POST'])
def schedule_appointment():
    """Schedule a new appointment for a user.
    Expects JSON body:
    {
      "uid": "<user uid>",
      "appointment": {"doctor_name": "Dr. Sharma", "date": "2025-11-05", "time_slot": "4:00 PM"}
    }
    Stores the appointment under users/{uid}/appointments/{autoId}.
    """
    if db is None:
        return jsonify({'error': 'Firestore not initialized'}), 500

    data = request.get_json() or {}
    uid = data.get('uid')
    appointment = data.get('appointment')

    if not uid:
        return jsonify({'error': 'Field "uid" is required in JSON body'}), 400
    if not isinstance(appointment, dict) or not appointment:
        return jsonify({'error': 'Field "appointment" (non-empty object) is required in JSON body'}), 400

    # Accept specialty-based scheduling: if doctor_name missing but speciality provided, auto assign.
    doctor_name = appointment.get('doctor_name') or appointment.get('doctor')
    specialty = appointment.get('speciality') or appointment.get('specialty') or appointment.get('specialization')
    auto_assigned = False
    if not doctor_name:
        # Attempt assignment
        assigned, resolved_key = assign_doctor_for_specialty(specialty)
        appointment['doctor_name'] = assigned
        appointment['speciality'] = resolved_key  # normalize spelling
        auto_assigned = True
    else:
        # Normalize possible speciality misspelling
        if specialty and 'speciality' not in appointment:
            appointment['speciality'] = specialty

    try:
        user_doc_ref = db.collection('users').document(uid)
        appointments_ref = user_doc_ref.collection('appointments')
        appointment.setdefault('created_at', firestore.SERVER_TIMESTAMP)
        new_doc_ref = appointments_ref.document()
        if auto_assigned:
            appointment['auto_assigned'] = True
        new_doc_ref.set(appointment)
        return jsonify({
            'success': True,
            'message': 'Appointment scheduled',
            'id': new_doc_ref.id
        }), 201
    except Exception:
        return jsonify({'error': 'Failed to schedule appointment'}), 500

@app.route('/get_appointments', methods=['POST'])
def get_appointments():
    """Retrieve all scheduled appointments for a user.
    Expects JSON body: { "uid": "<user uid>" }
    Returns list of appointments stored under users/{uid}/appointments.
    """
    if db is None:
        return jsonify({'error': 'Firestore not initialized'}), 500

    data = request.get_json() or {}
    uid = data.get('uid')
    if not uid:
        return jsonify({'error': 'Field "uid" is required in JSON body'}), 400

    try:
        user_doc_ref = db.collection('users').document(uid)
        appointments_ref = user_doc_ref.collection('appointments')
        docs = appointments_ref.stream()
        appointments = []
        for d in docs:
            appt = d.to_dict() or {}
            appt['id'] = d.id
            appointments.append(appt)
        return jsonify({'success': True, 'count': len(appointments), 'appointments': appointments}), 200
    except Exception:
        return jsonify({'error': 'Failed to fetch appointments'}), 500

@app.route('/doctor_appointments', methods=['POST'])
def doctor_appointments():
    """Retrieve appointments for a doctor (by UID -> resolves doctor name if role=doctor, else by provided doctor_name).
    JSON: { "uid": "..." } OR { "doctor_name": "Dr. ..." }
    If user is doctor, matches their name across patient bookings (auto-assigned). This simplistic implementation
    assumes the doctor's full name appears exactly as assigned in appointments.
    """
    if db is None:
        return jsonify({'error': 'Firestore not initialized'}), 500
    data = request.get_json() or {}
    uid = data.get('uid')
    explicit_doctor_name = data.get('doctor_name')
    doctor_name = None
    # Resolve doctor_name from user profile if uid provided
    if uid:
        try:
            doc = db.collection('users').document(uid).get()
            if doc.exists:
                d = doc.to_dict() or {}
                if d.get('role') == 'doctor':
                    # For demo: store a display_name or fallback to email prefix
                    doctor_name = d.get('display_name') or d.get('name')
                    if not doctor_name:
                        email = d.get('email','')
                        doctor_name = 'Dr. ' + email.split('@')[0].replace('.', ' ').title()
        except Exception:
            pass
    if explicit_doctor_name:
        doctor_name = explicit_doctor_name
    if not doctor_name:
        return jsonify({'error': 'Doctor name not resolved'}), 400
    # Query all users appointments scanning (inefficient for production but fine for prototype)
    try:
        users_ref = db.collection('users').stream()
        matched = []
        for u in users_ref:
            try:
                appts = db.collection('users').document(u.id).collection('appointments').stream()
                for a in appts:
                    rec = a.to_dict() or {}
                    if (rec.get('doctor_name') or '').lower() == doctor_name.lower():
                        rec['id'] = a.id
                        rec['patient_uid'] = u.id
                        matched.append(rec)
            except Exception:
                continue
        matched.sort(key=lambda x: (x.get('date') or '', x.get('time_slot') or ''))
        return jsonify({'success': True, 'count': len(matched), 'appointments': matched, 'doctor_name': doctor_name}), 200
    except Exception:
        return jsonify({'error': 'Failed to gather doctor appointments'}), 500

@app.route('/search_external_doctors', methods=['POST'])
def search_external_doctors():
    """Search doctors from external platforms (Lybrate, Practo)
    JSON body: { 
        "specialty": "cardiology", 
        "location": "Mumbai", 
        "filters": {
            "min_experience": 5,
            "min_rating": 4.0,
            "consultation_type": "online",
            "max_fee": 1000
        }
    }
    """
    try:
        data = request.get_json() or {}
        specialty = data.get('specialty', '').strip()
        location = data.get('location', '').strip()
        filters = data.get('filters', {})
        
        if not specialty:
            return jsonify({'error': 'Specialty is required'}), 400
        
        # Start with local doctors
        local_doctors = DOCTOR_DIRECTORY.get(specialty.lower(), [])
        formatted_local = [{
            'name': doc,
            'specialty': specialty,
            'source': 'local',
            'available_modes': ['video', 'phone'],
            'rating': 4.5,  # Default rating for local doctors
            'consultation_fee': 500  # Default fee
        } for doc in local_doctors]
        
        external_doctors = []
        
        # Search external platforms if available
        if healthcare_integrator:
            try:
                external_doctors = healthcare_integrator.unified_doctor_search(
                    specialty=specialty,
                    location=location,
                    filters=filters
                )
            except Exception as e:
                logging.error(f"External doctor search failed: {e}")
        
        # Combine and rank results
        all_doctors = formatted_local + external_doctors
        
        # Apply filters
        if filters.get('max_fee'):
            all_doctors = [d for d in all_doctors if d.get('consultation_fee', 0) <= filters['max_fee']]
        
        if filters.get('min_rating'):
            all_doctors = [d for d in all_doctors if d.get('rating', 0) >= filters['min_rating']]
        
        # Sort by rating and source preference
        all_doctors.sort(key=lambda x: (
            x.get('rating', 0),
            1 if x.get('source') in ['lybrate', 'practo'] else 0  # Prefer external platforms
        ), reverse=True)
        
        return jsonify({
            'doctors': all_doctors[:20],  # Return top 20
            'total_found': len(all_doctors),
            'sources_used': list(set([d.get('source', 'unknown') for d in all_doctors]))
        })
        
    except Exception as e:
        logging.error(f'Error in search_external_doctors: {e}')
        return jsonify({'error': 'Failed to search doctors'}), 500

@app.route('/get_lab_tests', methods=['POST'])
def get_lab_tests():
    """Get available lab tests from external platforms
    JSON body: {
        "location": "Mumbai",
        "category": "blood",  # Optional: blood, urine, cardiac, etc.
        "home_collection": true
    }
    """
    try:
        data = request.get_json() or {}
        location = data.get('location', '').strip()
        category = data.get('category', '').strip()
        home_collection = data.get('home_collection', False)
        
        if not location:
            return jsonify({'error': 'Location is required'}), 400
        
        lab_tests = []
        
        # Get lab tests from Practo if available
        if healthcare_integrator and healthcare_integrator.practo:
            try:
                tests = healthcare_integrator.practo.get_available_lab_tests(
                    location=location,
                    test_category=category
                )
                if home_collection:
                    tests = [t for t in tests if t.get('home_collection', False)]
                lab_tests.extend(tests)
            except Exception as e:
                logging.error(f"Lab tests search failed: {e}")
        
        # Sort by popularity and price
        lab_tests.sort(key=lambda x: (x.get('price', 999999), -len(x.get('name', ''))))
        
        return jsonify({
            'lab_tests': lab_tests,
            'categories': ['blood', 'urine', 'cardiac', 'diabetes', 'thyroid', 'liver', 'kidney'],
            'total_found': len(lab_tests)
        })
        
    except Exception as e:
        logging.error(f'Error in get_lab_tests: {e}')
        return jsonify({'error': 'Failed to get lab tests'}), 500

@app.route('/book_external_appointment', methods=['POST'])
def book_external_appointment():
    """Book appointment with external doctor (Lybrate/Practo)
    JSON body: {
        "doctor_id": "doc123",
        "platform": "lybrate",  # or "practo"
        "patient_info": {
            "name": "John Doe",
            "phone": "+91xxxxxxxxxx",
            "email": "john@example.com",
            "age": 30,
            "gender": "male"
        },
        "appointment_details": {
            "date": "2025-10-15",
            "time": "10:00 AM",
            "symptoms": "chest pain",
            "consultation_mode": "video"
        }
    }
    """
    try:
        data = request.get_json() or {}
        doctor_id = data.get('doctor_id', '').strip()
        platform = data.get('platform', '').strip().lower()
        patient_info = data.get('patient_info', {})
        appointment_details = data.get('appointment_details', {})
        
        if not doctor_id or not platform or not patient_info:
            return jsonify({'error': 'Missing required fields'}), 400
        
        booking_result = {'success': False}
        
        if platform == 'lybrate' and healthcare_integrator and healthcare_integrator.lybrate:
            try:
                booking_result = healthcare_integrator.lybrate.book_consultation(
                    doctor_id=doctor_id,
                    patient_info=patient_info,
                    slot_time=f"{appointment_details.get('date')} {appointment_details.get('time')}",
                    consultation_type=appointment_details.get('consultation_mode', 'video')
                )
            except Exception as e:
                booking_result = {'success': False, 'error': str(e)}
                
        elif platform == 'practo' and healthcare_integrator and healthcare_integrator.practo:
            try:
                booking_result = healthcare_integrator.practo.book_appointment(
                    doctor_id=doctor_id,
                    patient_info=patient_info,
                    appointment_details=appointment_details
                )
            except Exception as e:
                booking_result = {'success': False, 'error': str(e)}
        else:
            return jsonify({'error': f'Platform {platform} not supported or not configured'}), 400
        
        # Store booking in local database for tracking
        if booking_result.get('success') and db is not None:
            try:
                uid = patient_info.get('uid') or 'external_patient'
                booking_record = {
                    'external_booking_id': booking_result.get('booking_id') or booking_result.get('appointment_id'),
                    'platform': platform,
                    'doctor_id': doctor_id,
                    'patient_info': patient_info,
                    'appointment_details': appointment_details,
                    'booking_status': 'confirmed',
                    'booking_timestamp': datetime.now().isoformat(),
                    'meeting_link': booking_result.get('meeting_link') or booking_result.get('meeting_details', {}).get('link'),
                    'payment_link': booking_result.get('payment_link')
                }
                
                db.collection('users').document(uid).collection('external_appointments').add(booking_record)
            except Exception as e:
                logging.error(f"Failed to store external booking locally: {e}")
        
        return jsonify(booking_result)
        
    except Exception as e:
        logging.error(f'Error in book_external_appointment: {e}')
        return jsonify({'error': 'Failed to book external appointment'}), 500

@app.route('/place_autocomplete', methods=['POST'])
def place_autocomplete():
    """Proxy Geoapify place autocomplete to protect API key and constrain to India & rural/local areas.
    JSON: { query:'', limit?:8, bias_lat?:float, bias_lng?:float }
    Returns: { suggestions: [ { id, name, formatted, lat, lng, type } ] }
    """
    if db is None:  # Firestore not needed but keep consistency
        pass
    data = request.get_json() or {}
    q = (data.get('query') or '').strip()
    limit = int(data.get('limit') or 8)
    bias_lat = data.get('bias_lat')
    bias_lng = data.get('bias_lng')
    if len(q) < 2:
        return jsonify({'success': True, 'suggestions': []}), 200

    def format_geoapify(jdata):
        items = []
        raw_list = jdata if isinstance(jdata, list) else jdata.get('results') or jdata.get('features') or []
        for idx, item in enumerate(raw_list):
            try:
                if 'lat' in item and 'lon' in item:
                    latv = item.get('lat') or item.get('latitude') or (item.get('geometry',{}).get('coordinates',[None,None])[1] if item.get('geometry') else None)
                    lonv = item.get('lon') or item.get('longitude') or (item.get('geometry',{}).get('coordinates',[None,None])[0] if item.get('geometry') else None)
                else:
                    geom = item.get('geometry', {})
                    coords = geom.get('coordinates') if isinstance(geom, dict) else None
                    lonv, latv = (coords[0], coords[1]) if coords and len(coords) >= 2 else (None, None)
                props = item.get('properties') if isinstance(item, dict) else item
                name = None
                if isinstance(props, dict):
                    name = props.get('name') or props.get('address_line1') or props.get('formatted') or props.get('city')
                if not name and isinstance(item, dict):
                    name = item.get('formatted') or item.get('name')
                if not name:
                    continue
                place_type = None
                if isinstance(props, dict):
                    place_type = props.get('result_type') or props.get('place_type') or props.get('suburb') or props.get('type')
                formatted = None
                if isinstance(props, dict):
                    formatted = props.get('formatted') or props.get('address_line2')
                items.append({
                    'id': (props.get('place_id') if isinstance(props, dict) else f'idx{idx}') or f'idx{idx}',
                    'name': name,
                    'formatted': formatted or name,
                    'lat': latv,
                    'lng': lonv,
                    'type': place_type,
                    'source': 'geoapify'
                })
            except Exception:
                continue
        return items

    def format_nominatim(jdata):
        items = []
        for idx, item in enumerate(jdata):
            try:
                name = item.get('display_name') or item.get('name')
                if not name:
                    continue
                latv = item.get('lat')
                lonv = item.get('lon')
                typ = item.get('type') or item.get('class')
                items.append({
                    'id': item.get('osm_id') or f'nom{idx}',
                    'name': name.split(',')[0],
                    'formatted': name,
                    'lat': float(latv) if latv else None,
                    'lng': float(lonv) if lonv else None,
                    'type': typ,
                    'source': 'nominatim'
                })
            except Exception:
                continue
        return items

    geo_items = []
    error_geo = None
    if GEOAPIFY_API_KEY:
        try:
            params = {
                'text': q,
                'format': 'json',
                'filter': 'countrycode:in',
                'limit': min(max(limit,1), 15),
                'apiKey': GEOAPIFY_API_KEY,
                'type': 'city,village,hamlet,locality,neighbourhood,town'
            }
            if isinstance(bias_lat, (int,float)) and isinstance(bias_lng, (int,float)):
                params['bias'] = f'proximity:{bias_lng},{bias_lat}'
            resp = requests.get('https://api.geoapify.com/v1/geocode/autocomplete', params=params, timeout=6)
            if resp.status_code == 200:
                geo_items = format_geoapify(resp.json())
            else:
                error_geo = f'status:{resp.status_code} body:{resp.text[:120]}'
        except Exception as eg:
            error_geo = f'exception:{eg}'

    # Fallback to Nominatim if no geoapify results
    nom_items = []
    if not geo_items:
        try:
            nom_params = {
                'q': q,
                'countrycodes': 'in',
                'format': 'json',
                'limit': str(min(max(limit,1), 15))
            }
            headers = {'User-Agent': 'SehatSaathi/1.0 (+https://example.local)'}
            r2 = requests.get('https://nominatim.openstreetmap.org/search', params=nom_params, headers=headers, timeout=6)
            if r2.status_code == 200:
                nom_items = format_nominatim(r2.json())
            else:
                if not error_geo:
                    error_geo = f'nominatim_status:{r2.status_code}'
        except Exception as en:
            if not error_geo:
                error_geo = f'nominatim_exception:{en}'

    merged = geo_items or nom_items
    if merged:
        return jsonify({'success': True, 'count': len(merged), 'suggestions': merged, 'fallback_used': bool(not geo_items), 'geoapify_error': error_geo}), 200
    return jsonify({'error': 'No suggestions', 'details': error_geo or 'unknown'}), 502

# --------- Admin Doctor Verification Endpoints (Prototype - no auth) ---------
@app.route('/admin/list_pending_doctors', methods=['GET'])
def list_pending_doctors():
    if db is None:
        return jsonify({'error': 'Firestore not initialized'}), 500
    try:
        docs = db.collection('doctors').where('status','==','pending').stream()
        pending = []
        for d in docs:
            item = d.to_dict() or {}
            item['uid'] = d.id
            pending.append(item)
        return jsonify({'success': True, 'count': len(pending), 'pending': pending}), 200
    except Exception as e:
        return jsonify({'error': 'Failed to list pending', 'details': str(e)}), 500

@app.route('/admin/verify_doctor', methods=['POST'])
def verify_doctor():
    if db is None:
        return jsonify({'error': 'Firestore not initialized'}), 500
    data = request.get_json() or {}
    uid = data.get('uid')
    action = (data.get('action') or '').lower()  # approve or reject
    if not uid or action not in ('approve','reject'):
        return jsonify({'error': 'Fields "uid" and action (approve/reject) required'}), 400
    try:
        user_ref = db.collection('users').document(uid)
        doc_ref = db.collection('doctors').document(uid)
        user_doc = user_ref.get()
        if not user_doc.exists:
            return jsonify({'error': 'User not found'}), 404
        status_value = 'active' if action=='approve' else 'rejected'
        user_ref.set({'role_status': status_value}, merge=True)
        doc_ref.set({'status': 'approved' if action=='approve' else 'rejected', 'verified_at': firestore.SERVER_TIMESTAMP}, merge=True)
        return jsonify({'success': True, 'uid': uid, 'newStatus': status_value}), 200
    except Exception as e:
        return jsonify({'error': 'Verification failed', 'details': str(e)}), 500

@app.route('/delete_appointment', methods=['POST'])
def delete_appointment():
    """Delete an appointment.
    Expects JSON: { "uid": "..", "id": "appointmentDocId" }
    """
    if db is None:
        return jsonify({'error': 'Firestore not initialized'}), 500
    data = request.get_json() or {}
    uid = data.get('uid')
    appt_id = data.get('id')
    if not uid or not appt_id:
        return jsonify({'error': 'Fields "uid" and "id" are required'}), 400
    try:
        ref = db.collection('users').document(uid).collection('appointments').document(appt_id)
        if not ref.get().exists:
            return jsonify({'error': 'Appointment not found'}), 404
        ref.delete()
        return jsonify({'success': True, 'message': 'Appointment deleted'}), 200
    except Exception as e:
        return jsonify({'error': 'Failed to delete appointment', 'details': str(e)}), 500

@app.route('/update_appointment', methods=['POST'])
def update_appointment():
    """Update fields of an appointment.
    Expects JSON: { "uid": "..", "id": "appointmentDocId", "updates": { ... } }
    """
    if db is None:
        return jsonify({'error': 'Firestore not initialized'}), 500
    data = request.get_json() or {}
    uid = data.get('uid')
    appt_id = data.get('id')
    updates = data.get('updates') or {}
    if not uid or not appt_id:
        return jsonify({'error': 'Fields "uid" and "id" are required'}), 400
    if not isinstance(updates, dict) or not updates:
        return jsonify({'error': 'Field "updates" (non-empty object) is required'}), 400
    try:
        ref = db.collection('users').document(uid).collection('appointments').document(appt_id)
        if not ref.get().exists:
            return jsonify({'error': 'Appointment not found'}), 404
        ref.set(updates, merge=True)
        return jsonify({'success': True, 'message': 'Appointment updated'}), 200
    except Exception as e:
        return jsonify({'error': 'Failed to update appointment', 'details': str(e)}), 500

@app.route('/get_nearby_hospitals', methods=['POST'])
def get_nearby_hospitals():
    """Find nearby hospitals and clinics within 10km of provided coordinates.
    Expects JSON body: { "lat": <latitude>, "lng": <longitude> }
    Returns list of hospitals/clinics with name, type, and coordinates.
    """
    if api is None:
        return jsonify({'error': 'Overpass API not initialized'}), 500

    try:
        # Globals used/modified in AI resolution logic
        global GENAI_MODEL_NAME, _CONSECUTIVE_404S, GENAI_AVAILABLE
        data = request.get_json() or {}
        lat = data.get('lat')
        lng = data.get('lng')
        speciality_filter = (data.get('speciality') or data.get('specialty') or '').strip().lower()
        result_limit = data.get('limit') or 30
        include_unnamed = bool(data.get('includeUnnamed', False))
        debug_naming = bool(data.get('debugNaming', False))
        debug_ai = bool(data.get('debugAI', False))

        # UID can come from body or header (X-User-UID) for flexibility
        uid = data.get('uid') or request.headers.get('X-User-UID')

        # -------- Fetch User Health History (for AI + heuristic fallback) --------
        history_terms_raw = []
        history_record_count = 0
        if uid and db is not None:
            try:
                docs = db.collection('users').document(uid).collection('health_history').stream()
                for d in docs:
                    history_record_count += 1
                    rec = d.to_dict() or {}
                    # Collect key medical fields
                    for k in ('symptom', 'diagnosis', 'condition'):
                        val = rec.get(k)
                        if isinstance(val, str) and val.strip():
                            history_terms_raw.append(val.strip())
                    notes = rec.get('doctor_notes')
                    if isinstance(notes, str) and notes.strip():
                        # Extract simple capitalized tokens (avoid overly long strings)
                        tokens = re.findall(r'[A-Za-z][A-Za-z\- ]{2,}', notes)
                        for t in tokens:
                            t_clean = t.strip()
                            if t_clean and len(t_clean) < 40:
                                history_terms_raw.append(t_clean)
            except Exception:
                # Silently ignore Firestore errors (keep endpoint functional)
                pass

        # Deduplicate (case-insensitive) and clamp length
        seen_hist = set()
        history_terms = []
        for term in history_terms_raw:
            low = term.lower()
            if low not in seen_hist:
                seen_hist.add(low)
                history_terms.append(term)
        history_terms = history_terms[:50]  # soft clamp
        history_str = ', '.join(history_terms[:25]) if history_terms else 'No significant history provided'

        if lat is None or lng is None:
            return jsonify({'error': 'Fields "lat" and "lng" are required in JSON body'}), 400

        # Helper: haversine distance in km
        from math import radians, sin, cos, asin, sqrt
        def haversine(lat1, lon1, lat2, lon2):
            if None in (lat1, lon1, lat2, lon2):
                return None
            R = 6371.0
            dlat = radians(lat2 - lat1)
            dlon = radians(lon2 - lon1)
            a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
            c = 2 * asin(sqrt(a))
            return R * c

        # Progressive search radii (meters)
        radii = [10000, 20000, 30000]
        hospitals_list = []
        radius_used = None
        overpass_error = False

        overpass_attempts = []
        for r in radii:
            query = f"""(
  node["amenity"="hospital"](around:{r},{lat},{lng});
  node["amenity"="clinic"](around:{r},{lat},{lng});
  way["amenity"~"^(hospital|clinic)$"](around:{r},{lat},{lng});
  relation["amenity"~"^(hospital|clinic)$"](around:{r},{lat},{lng});
);out center;"""
            attempt_info = {'radius': r, 'success': False, 'error': None}
            # Retry with exponential backoff on ServerLoadError / timeout
            max_retries = 3
            base_sleep = 1.0
            response = None
            for attempt in range(max_retries):
                try:
                    response = api.get(query)
                    attempt_info['success'] = True
                    break
                except overpass.errors.ServerLoadError as sle:
                    attempt_info['error'] = f'ServerLoadError:{sle}'
                    time.sleep(base_sleep * (2 ** attempt))
                except overpass.errors.TimeoutError as te:
                    attempt_info['error'] = f'TimeoutError:{te}'
                    time.sleep(base_sleep * (2 ** attempt))
                except Exception as ex:
                    attempt_info['error'] = f'Other:{ex}'
                    break
            overpass_attempts.append(attempt_info)
            if not attempt_info['success']:
                overpass_error = True
                continue

            features = response.get('features', []) if isinstance(response, dict) else []
            temp = []
            for feature in features:
                props = feature.get('properties', {}) or {}
                raw_tags = props.get('tags')
                tags = raw_tags if isinstance(raw_tags, dict) else {}
                # Fallback: some overpass lib versions put tags directly in properties
                if not tags and any(k in props for k in ('amenity','name','name:en','official_name','operator','brand')):
                    # Extract probable tag-like entries
                    tags = {k: v for k, v in props.items() if isinstance(k, str) and isinstance(v, (str,int,float))}

                # Build candidate names
                candidate_keys = [
                    'name','name:en','official_name','short_name','alt_name','operator','brand','addr:housename'
                ]
                candidates = []
                for ck in candidate_keys:
                    val = tags.get(ck)
                    if isinstance(val, str):
                        clean = val.strip()
                        if clean and clean.lower() not in ('hospital','clinic','polyclinic'):
                            candidates.append(clean)
                # Additional heuristic: combine housenumber + street if no better name
                if not candidates:
                    housenumber = tags.get('addr:housenumber') or ''
                    street = tags.get('addr:street') or ''
                    combo = (str(housenumber).strip() + ' ' + str(street).strip()).strip()
                    if combo:
                        candidates.append(combo + ' Clinic')
                name = candidates[0] if candidates else 'Unnamed facility'

                # Extract specialty tags if available
                specialty_tags = []
                for spec_key in [
                    'healthcare:speciality','healthcare:specialty',
                    'medical:specialty','medical:speciality',
                    'speciality','specialty'
                ]:
                    val = tags.get(spec_key)
                    if isinstance(val, str) and val.strip():
                        # Split on common delimiters ; , / |
                        parts = re.split(r'[;,/|]', val)
                        for p in parts:
                            p_clean = p.strip().lower()
                            if p_clean and p_clean not in specialty_tags and len(p_clean) < 50:
                                specialty_tags.append(p_clean)

                amenity_type = tags.get('amenity') or tags.get('healthcare')
                geometry = feature.get('geometry', {}) or {}
                coords = geometry.get('coordinates') if geometry else None
                lat_val = None
                lng_val = None
                # Prefer center if provided (for ways/relations)
                center = props.get('center')
                if isinstance(center, dict) and 'lat' in center and 'lon' in center:
                    lat_val = center['lat']
                    lng_val = center['lon']
                elif coords and isinstance(coords, list):
                    try:
                        lng_val, lat_val = coords[0], coords[1]
                    except (IndexError, TypeError):
                        pass

                dist = haversine(lat, lng, lat_val, lng_val)
                entry = {
                    'name': name,
                    'type': amenity_type,
                    'latitude': lat_val,
                    'longitude': lng_val,
                    'distance_km': dist
                }
                if specialty_tags:
                    entry['specialties'] = specialty_tags
                if debug_naming:
                    entry['rawTags'] = tags
                temp.append(entry)
            # If we found any at this radius, stop escalating
            if temp:
                # Sort by distance (none-safe)
                hospitals_list = [t for t in temp if t['distance_km'] is not None]
                hospitals_list.sort(key=lambda x: x['distance_km'])
                radius_used = r
                break

        source = 'overpass'
        # Fallback to static list if none found after all radii
        if not hospitals_list:
            # Provide top 5 static hospitals with distance (if file lat/lon not present we skip distance calc)
            static_results = []
            for h in hospitals_data:
                # Attempt to parse possible lat/lon keys if exist
                h_lat = h.get('lat') or h.get('latitude')
                h_lng = h.get('lng') or h.get('longitude')
                dist = haversine(lat, lng, h_lat, h_lng) if h_lat and h_lng else None
                static_results.append({
                    'name': h.get('name'),
                    'type': 'hospital',
                    'latitude': h_lat,
                    'longitude': h_lng,
                    'distance_km': dist
                })
            # Filter those with distance first
            with_distance = [s for s in static_results if s['distance_km'] is not None]
            without_distance = [s for s in static_results if s['distance_km'] is None]
            with_distance.sort(key=lambda x: x['distance_km'])
            hospitals_list = with_distance[:5] + without_distance[: max(0, 5 - len(with_distance))]
            source = 'fallback'

        # ---- Post Processing ----
        # 1. Dedupe by (rounded coords to 5dp, lowercased name)
        deduped = {}
        for h in hospitals_list:
            name_key = (h.get('name') or '').lower().strip()
            lat_key = round(h.get('latitude'), 5) if h.get('latitude') is not None else None
            lng_key = round(h.get('longitude'), 5) if h.get('longitude') is not None else None
            key = (name_key, lat_key, lng_key)
            if key not in deduped:
                deduped[key] = h
        hospitals_list = list(deduped.values())

        # 2. Filter by speciality keyword if provided
        if speciality_filter:
            keywords = [kw.strip() for kw in speciality_filter.split(',') if kw.strip()]
            filtered = []
            for h in hospitals_list:
                text = (h.get('name') or '').lower()
                if any(k in text for k in keywords):
                    filtered.append(h)
            if filtered:
                hospitals_list = filtered

        # Preserve pre name-filter list (distance ordering already applied earlier)
        pre_name_filter_list = list(hospitals_list)

        # 3. Remove 'Unnamed facility' unless explicitly requested
        excluded_unnamed = 0
        fallback_used = False
        if not include_unnamed:
            filtered_named = []
            for h in hospitals_list:
                if h.get('name') and h['name'].lower() != 'unnamed facility':
                    filtered_named.append(h)
                else:
                    excluded_unnamed += 1
            hospitals_list = filtered_named
            # If everything got removed and we had unnamed options, fallback to top unnamed so user still sees something
            if not hospitals_list and excluded_unnamed > 0:
                hospitals_list = pre_name_filter_list[:result_limit]
                fallback_used = True

        # 4. Limit results (again in case no filtering applied)
        hospitals_list = hospitals_list[:result_limit]

        # -------- AI Recommendation (Hugging Face Zero-Shot) --------
        ai_used = False
        ai_error = None
        recommended_name = None
        recommendation_source = None
        # Maintain compatibility with existing response fields (Gemini removed)
        ai_model_attempted = []  # no models attempted (Gemini removed)
        ai_raw_output = None
        ai_not_run_reason = None
        GENAI_AVAILABLE = False  # Explicitly mark Gemini unavailable now
        GEMINI_STATUS = 'disabled:huggingface-replacement'

        if history_terms and hospitals_list:
            try:
                API_URL = "https://api-inference.huggingface.co/models/facebook/bart-large-mnli"
                hf_token = os.getenv('HUGGINGFACE_API_TOKEN')  # Expect user to set this
                if not hf_token:
                    ai_not_run_reason = 'missing_huggingface_token'
                else:
                    headers = {"Authorization": f"Bearer {hf_token}"}
                    specialty_labels = [
                        'cardiology and heart',
                        'orthopedics and bone',
                        'neurology and brain',
                        'pediatrics and child care',
                        'general medicine'
                    ]
                    payload = {
                        "inputs": history_str,
                        "parameters": {"candidate_labels": specialty_labels}
                    }
                    response_zs = requests.post(API_URL, headers=headers, json=payload, timeout=25)
                    if response_zs.status_code == 200:
                        ai_result = response_zs.json()
                        labels = ai_result.get('labels') or []
                        if labels:
                            top_specialty = labels[0]
                            ai_used = True
                            # derive keywords (basic split & cleanup)
                            keywords_to_match = [kw for kw in re.split(r'[^a-zA-Z]+', top_specialty.lower()) if kw]
                            best_match_hospital = None
                            for hospital in hospitals_list:
                                hospital_name_lower = (hospital.get('name') or '').lower()
                                if any(keyword in hospital_name_lower for keyword in keywords_to_match):
                                    best_match_hospital = hospital
                                    break
                            if best_match_hospital:
                                recommended_name = best_match_hospital.get('name')
                                recommendation_source = 'huggingface-zeroshot'
                        else:
                            ai_error = 'No labels returned from zero-shot model'
                    else:
                        ai_error = f"HF API status {response_zs.status_code}: {response_zs.text[:180]}"
            except Exception as e_hf:
                ai_error = str(e_hf)[:300]
        else:
            if not history_terms:
                ai_not_run_reason = 'no_history_terms'
            elif not hospitals_list:
                ai_not_run_reason = 'no_hospitals'

        # Deterministic fallback if AI failed to produce a recommendation
        # Preserve existing downstream logic: if huggingface produced a recommendation, treat as 'ai'
        recommendation_source = 'ai' if ai_used else recommendation_source
        recommendation_reason_local = None
        if not recommended_name:
            # Simple specialty-aware heuristic
            history_blob = history_str or ''
            history_lower = history_blob.lower()
            specialty_groups = {
                'cardio': ['cardio','cardiac','heart'],
                'eye': ['eye','ophthal'],
                'neuro': ['neuro','brain'],
                'ortho': ['ortho','orthopedic','orthopaedic'],
                'ent': ['ent','ear nose throat'],
                'cancer': ['cancer','onco','oncology'],
                'kidney': ['kidney','renal','nephro']
            }
            # Detect which specialty groups appear in history
            groups_in_history = []
            for g, kws in specialty_groups.items():
                if any(kw in history_lower for kw in kws):
                    groups_in_history.append(g)

            # If heart/cardiac history present, first try strict match to heart-related facilities
            prioritized_match_used = False
            if groups_in_history:
                # Build prioritized candidate list: union of all groups in history (start with more critical domains first)
                priority_order = ['cardio','neuro','cancer','kidney','ortho','eye','ent']
                ordered_history_groups = [g for g in priority_order if g in groups_in_history]
                matched_hospitals = []
                for g in ordered_history_groups:
                    kws = specialty_groups[g]
                    for h in hospitals_list:
                        nm_low = (h.get('name') or '').lower()
                        if any(kw in nm_low for kw in kws):
                            matched_hospitals.append(h)
                # De-duplicate while preserving order
                seen_ids = set()
                dedup_matched = []
                for h in matched_hospitals:
                    key = (h.get('name'), h.get('latitude'), h.get('longitude'))
                    if key not in seen_ids:
                        seen_ids.add(key)
                        dedup_matched.append(h)
                if dedup_matched:
                    # Pick nearest among matched
                    dedup_matched.sort(key=lambda x: (x.get('distance_km') if x.get('distance_km') is not None else 1e9))
                    recommended_name = dedup_matched[0].get('name')
                    recommendation_source = 'fallback-specialty'
                    prioritized_match_used = True

            if prioritized_match_used and recommended_name:
                pass  # already selected
            else:
                # Generic scoring fallback
                def specialty_score(hospital_entry, name_lower):
                    score = 0
                    reasons = []
                    # Match history + name overlap
                    for group, kws in specialty_groups.items():
                        in_name = any(kw in name_lower for kw in kws)
                        in_hist = any(kw in history_lower for kw in kws)
                        if in_name and in_hist:
                            score += 6
                            reasons.append(f"strong {group} match (history+name)")
                        elif in_name:
                            score += 3
                            reasons.append(f"{group} in name")
                    # Specialty tags (if extracted)
                    specs = hospital_entry.get('specialties') or []
                    for s in specs:
                        for group, kws in specialty_groups.items():
                            if s and any(kw in s for kw in kws):
                                if any(kw in history_lower for kw in kws):
                                    score += 5
                                    reasons.append(f"specialty tag {s} matches history ({group})")
                                else:
                                    score += 2
                                    reasons.append(f"specialty tag {s}")
                    # General multi-specialty indicators
                    if any(tok in name_lower for tok in ['multi','general','medical']):
                        score += 1
                        reasons.append('general facility indicator')
                    # Penalize mismatch: if cardiac history present but ortho only center selected
                    if 'cardio' in groups_in_history and any(kw in name_lower for kw in specialty_groups['ortho']) and not any(kw in name_lower for kw in specialty_groups['cardio']):
                        score -= 4
                        reasons.append('penalize ortho for cardiac history')
                    return score, reasons
                best = None
                best_reasons = None
                for h in hospitals_list:
                    nm = (h.get('name') or '').strip()
                    if not nm:
                        continue
                    nlow = nm.lower()
                    score, reasons = specialty_score(h, nlow)
                    dist = h.get('distance_km') or 1e9
                    # Create tuple: higher score better; lower distance better; shorter name minor preference
                    candidate = (score, - (dist if dist is not None else 1e9) * 0.001, -len(nm), nm)
                    if best is None or candidate > best[0]:
                        best = (candidate, nm)
                        best_reasons = reasons
                if best and best[1]:
                    recommended_name = best[1]
                    recommendation_source = 'fallback'
                    recommendation_reason_local = '; '.join(best_reasons[:6]) if best_reasons else None
        # If AI produced a recommendation and no reason yet, add default
        if recommendation_source == 'ai' and recommended_name and not recommendation_reason_local:
            recommendation_reason_local = 'AI model recommendation'
        # Mark recommended hospital (AI or fallback)
        if recommended_name:
            lower_rec = recommended_name.lower()
            for h in hospitals_list:
                h['is_recommended'] = (h.get('name') or '').lower() == lower_rec
        else:
            for h in hospitals_list:
                h['is_recommended'] = False

        return jsonify({
            'success': True,
            'count': len(hospitals_list),
            'hospitals': hospitals_list,
            'radiusUsedMeters': radius_used,
            'overpassAttempts': overpass_attempts,
            'source': source,
            'overpassError': overpass_error,
            'filteredBySpeciality': bool(speciality_filter),
            'specialityQuery': speciality_filter or None,
            'includeUnnamed': include_unnamed,
            'excludedUnnamedCount': excluded_unnamed,
            'fallbackUnnamed': fallback_used,
            'debugNaming': debug_naming,
            'aiUsed': ai_used,
            'aiError': ai_error,
            'aiRecommendation': recommended_name,
            'aiModelAttempts': ai_model_attempted,  # always return attempted models
            'aiRawOutput': ai_raw_output,
            'aiAvailable': GENAI_AVAILABLE,
            'aiStatus': GEMINI_STATUS,
            'aiNotRunReason': ai_not_run_reason,
            'debugAI': debug_ai,
            'recommendationSource': recommendation_source,
            'recommendationReason': recommendation_reason_local,
            'historyRecordCount': history_record_count,
            'historyTermsUsed': history_terms if debug_ai else None
        }), 200
    except Exception as e:
        logging.exception('Failed to fetch nearby hospitals')
        return jsonify({'error': 'Failed to fetch nearby hospitals'}), 500

 # -------------------- Consult & Doctor-Patient Connection Endpoints --------------------

@app.route('/request_consult', methods=['POST'])
def request_consult():
    """Patient escalates AI chat to request a doctor.
    JSON: { uid: patient_uid, messages: [ {role,text}, ... ] }
    Returns: { request_id }
    """
    if db is None:
        return jsonify({'error':'Firestore not initialized'}), 500
    data = request.get_json() or {}
    uid = data.get('uid')
    msgs = data.get('messages') or []
    if not uid:
        return jsonify({'error':'uid required'}), 400
    # Fetch patient basics
    patient_email = None
    patient_id = None
    try:
        udoc = db.collection('users').document(uid).get()
        if udoc.exists:
            udata = udoc.to_dict() or {}
            patient_email = udata.get('email')
            patient_id = udata.get('patient_id')
    except Exception:
        pass
    # Build symptom summary from last few user messages
    user_texts = []
    for m in msgs[-10:]:
        if isinstance(m, dict) and (m.get('role') in ('user','patient')):
            txt = (m.get('text') or '').strip()
            if txt:
                user_texts.append(txt)
    summary_source = ' | '.join(user_texts[-5:])[:300] if user_texts else 'No recent symptoms described.'
    try:
        ref = db.collection('consult_requests').document()
        ref.set({
            'patient_uid': uid,
            'patient_email': patient_email,
            'patient_id': patient_id,
            'created_at': firestore.SERVER_TIMESTAMP,
            'status': 'open',
            'summary': summary_source,
            'doctor_uid': None,
            'doctor_name': None,
            'accepted_at': None
        })
        return jsonify({'success': True, 'request_id': ref.id}), 201
    except Exception as e:
        return jsonify({'error':'Failed to create consult request','details':str(e)}), 500

@app.route('/list_open_consults', methods=['POST'])
def list_open_consults():
    if db is None:
        return jsonify({'error':'Firestore not initialized'}), 500
    data = request.get_json() or {}
    doctor_uid = data.get('doctor_uid')
    # Basic role check
    if doctor_uid:
        try:
            ddoc = db.collection('users').document(doctor_uid).get()
            if not ddoc.exists or (ddoc.to_dict() or {}).get('role') != 'doctor':
                return jsonify({'error':'Not authorized'}), 403
        except Exception:
            return jsonify({'error':'Not authorized'}), 403
    try:
        items = []
        query_ref = db.collection('consult_requests').where('status','==','open')
        docs = query_ref.stream()
        for d in docs:
            rec = d.to_dict() or {}
            # If doctor_uid present and doctor previously skipped, hide
            if doctor_uid and doctor_uid in (rec.get('skipped_by') or []):
                continue
            rec['id'] = d.id
            items.append(rec)
        # Local sort newest first if created_at exists
        def _ts(x):
            ts = x.get('created_at') or x.get('accepted_at')
            try:
                if hasattr(ts, 'timestamp'):
                    return ts.timestamp()
            except Exception:
                pass
            return 0
        items.sort(key=_ts, reverse=True)
        return jsonify({'success': True, 'count': len(items), 'requests': items, 'ordered': False, 'degraded': True}), 200
    except Exception as e:
        logging.exception('list_open_consults failure')
        # Graceful empty list fallback
        return jsonify({'success': True, 'count': 0, 'requests': [], 'error_note': str(e)}), 200

@app.route('/accept_consult', methods=['POST'])
def accept_consult():
    if db is None:
        return jsonify({'error':'Firestore not initialized'}), 500
    data = request.get_json() or {}
    doctor_uid = data.get('doctor_uid')
    request_id = data.get('request_id')
    if not doctor_uid or not request_id:
        return jsonify({'error':'doctor_uid and request_id required'}), 400
    # Validate doctor role
    try:
        ddoc = db.collection('users').document(doctor_uid).get()
        if not ddoc.exists or (ddoc.to_dict() or {}).get('role') != 'doctor':
            return jsonify({'error':'Not authorized'}), 403
        doctor_profile = ddoc.to_dict() or {}
    except Exception:
        return jsonify({'error':'Not authorized'}), 403
    try:
        cref = db.collection('consult_requests').document(request_id)
        snap = cref.get()
        if not snap.exists:
            return jsonify({'error':'Request not found'}), 404
        data_req = snap.to_dict() or {}
        if data_req.get('status') != 'open':
            return jsonify({'error':'Already accepted'}), 409
        doctor_name = doctor_profile.get('display_name') or doctor_profile.get('name')
        if not doctor_name:
            email = doctor_profile.get('email','')
            doctor_name = 'Dr. ' + email.split('@')[0].replace('.',' ').title()
        cref.set({'status':'accepted','doctor_uid':doctor_uid,'doctor_name':doctor_name,'accepted_at':firestore.SERVER_TIMESTAMP}, merge=True)
        return jsonify({'success': True, 'request_id': request_id, 'doctor_name': doctor_name}), 200
    except Exception as e:
        return jsonify({'error':'Failed to accept','details':str(e)}), 500

@app.route('/list_my_consults', methods=['POST'])
def list_my_consults():
    if db is None:
        return jsonify({'error':'Firestore not initialized'}), 500
    data = request.get_json() or {}
    doctor_uid = data.get('doctor_uid')
    if not doctor_uid:
        return jsonify({'error':'doctor_uid required'}), 400
    try:
        res = []
        query_ref = db.collection('consult_requests').where('doctor_uid','==',doctor_uid)
        docs = query_ref.stream()
        for d in docs:
            rec = d.to_dict() or {}
            # Only include active chat consults (accepted)
            if rec.get('status') != 'accepted':
                continue
            rec['id'] = d.id
            res.append(rec)
        def _ts(x):
            ts = x.get('accepted_at') or x.get('created_at')
            try:
                if hasattr(ts,'timestamp'):
                    return ts.timestamp()
            except Exception:
                pass
            return 0
        res.sort(key=_ts, reverse=True)
        return jsonify({'success': True, 'count': len(res), 'consults': res, 'ordered': False, 'degraded': True}), 200
    except Exception as e:
        logging.exception('list_my_consults failure')
        return jsonify({'success': True, 'count': 0, 'consults': [], 'error_note': str(e)}), 200

@app.route('/reject_consult', methods=['POST'])
def reject_consult():
    """Doctor opts out from an open consult. It remains open for other doctors.
    We record the doctor in a skipped_by array so it won't reappear for them."""
    if db is None:
        return jsonify({'error':'Firestore not initialized'}), 500
    data = request.get_json() or {}
    doctor_uid = data.get('doctor_uid')
    request_id = data.get('request_id')
    if not doctor_uid or not request_id:
        return jsonify({'error':'doctor_uid and request_id required'}), 400
    # Validate doctor
    try:
        ddoc = db.collection('users').document(doctor_uid).get()
        if not ddoc.exists or (ddoc.to_dict() or {}).get('role') != 'doctor':
            return jsonify({'error':'Not authorized'}), 403
    except Exception:
        return jsonify({'error':'Not authorized'}), 403
    try:
        cref = db.collection('consult_requests').document(request_id)
        snap = cref.get()
        if not snap.exists:
            return jsonify({'error':'Request not found'}), 404
        meta = snap.to_dict() or {}
        if meta.get('status') != 'open':
            return jsonify({'error':'Only open consults can be skipped'}), 409
        skipped = set(meta.get('skipped_by') or [])
        skipped.add(doctor_uid)
        cref.set({'skipped_by': list(skipped), 'last_skipped_at': firestore.SERVER_TIMESTAMP}, merge=True)
        return jsonify({'success': True, 'request_id': request_id, 'status':'open', 'skipped_by': list(skipped)}), 200
    except Exception as e:
        return jsonify({'error':'Failed to reject','details':str(e)}), 500

@app.route('/close_consult', methods=['POST'])
def close_consult():
    """Doctor closes an active (accepted) consult; marks it done."""
    if db is None:
        return jsonify({'error':'Firestore not initialized'}), 500
    data = request.get_json() or {}
    doctor_uid = data.get('doctor_uid')
    request_id = data.get('request_id')
    remarks = (data.get('remarks') or '').strip()
    prescription = (data.get('prescription') or '').strip()
    if not doctor_uid or not request_id:
        return jsonify({'error':'doctor_uid and request_id required'}), 400
    try:
        ddoc = db.collection('users').document(doctor_uid).get()
        if not ddoc.exists or (ddoc.to_dict() or {}).get('role') != 'doctor':
            return jsonify({'error':'Not authorized'}), 403
    except Exception:
        return jsonify({'error':'Not authorized'}), 403
    try:
        cref = db.collection('consult_requests').document(request_id)
        snap = cref.get()
        if not snap.exists:
            return jsonify({'error':'Consult not found'}), 404
        meta = snap.to_dict() or {}
        if meta.get('status') != 'accepted':
            return jsonify({'error':'Only accepted consults can be closed'}), 409
        if meta.get('doctor_uid') != doctor_uid:
            return jsonify({'error':'Not owner of consult'}), 403
        update_payload = {'status':'closed','closed_at':firestore.SERVER_TIMESTAMP}
        if remarks:
            update_payload['doctor_remarks'] = remarks
        if prescription:
            update_payload['prescription'] = prescription
        cref.set(update_payload, merge=True)
        # Store doctor remarks into patient health history if provided
        if (remarks or prescription) and db is not None:
            try:
                patient_uid = meta.get('patient_uid')
                if patient_uid:
                    hh_ref = db.collection('users').document(patient_uid).collection('health_history').document()
                    hh_ref.set({
                        'symptom': meta.get('primary_issue') or meta.get('reason') or 'Consultation Summary',
                        'doctor_remarks': remarks or None,
                        'prescription': prescription or None,
                        'consult_id': request_id,
                        'source': 'consult_close',
                        'created_at': firestore.SERVER_TIMESTAMP
                    })
            except Exception:
                pass
        # Lightweight inference of primary issue from consult messages if absent
        try:
            if not meta.get('primary_issue'):
                msgs_stream = cref.collection('messages').order_by('ts').limit(80).stream()
                text_blob = ' '.join([ (m.to_dict() or {}).get('text','') for m in msgs_stream ])[:6000].lower()
                best_issue=None; best_hits=0
                for key in responses.keys():
                    hits = len(re.findall(r'\b'+re.escape(key.lower())+r'\b', text_blob))
                    if hits>best_hits:
                        best_hits=hits; best_issue=key
                if best_issue:
                    cref.set({'primary_issue': best_issue.title()}, merge=True)
                    if (remarks or prescription) and patient_uid:
                        # Update the just-created health history entry with inferred symptom if generic label used
                        pass
        except Exception:
            pass
        return jsonify({'success': True, 'request_id': request_id, 'status':'closed', 'remarks_saved': bool(remarks)}), 200
    except Exception as e:
        return jsonify({'error':'Failed to close','details':str(e)}), 500

@app.route('/get_consult_messages', methods=['POST'])
def get_consult_messages():
    if db is None:
        return jsonify({'error':'Firestore not initialized'}), 500
    data = request.get_json() or {}
    request_id = data.get('request_id')
    if not request_id:
        return jsonify({'error':'request_id required'}), 400
    try:
        cref = db.collection('consult_requests').document(request_id)
        if not cref.get().exists:
            return jsonify({'error':'Not found'}), 404
        msgs = []
        stream = cref.collection('messages').order_by('ts').stream()
        for m in stream:
            rec = m.to_dict() or {}
            rec['id'] = m.id
            msgs.append(rec)
        meta = cref.get().to_dict() or {}
        # If doctor requesting, optionally include patient details only if consult accepted/closed
        requester_uid = (data.get('requester_uid') or '').strip()
        patient_detail = None
        if requester_uid and meta.get('doctor_uid') == requester_uid and meta.get('patient_uid'):
            if (meta.get('status') in ('accepted','closed')):
                try:
                    pdoc = db.collection('users').document(meta.get('patient_uid')).get()
                    if pdoc.exists:
                        pdata = pdoc.to_dict() or {}
                        patient_detail = {
                            'display_name': pdata.get('display_name'),
                            'patient_id': pdata.get('patient_id'),
                            'email': pdata.get('email'),
                            'mobile': pdata.get('mobile')
                        }
                except Exception:
                    patient_detail = None
        # Include attachment list (prototype) so doctor sees patient uploads & vice versa
        attachments = _list_consult_attachments(request_id)
        return jsonify({'success': True, 'messages': msgs, 'status': meta.get('status'), 'doctor_uid': meta.get('doctor_uid'), 'patient_uid': meta.get('patient_uid'), 'patient_detail': patient_detail, 'attachments': attachments}), 200
    except Exception as e:
        return jsonify({'error':'Failed to fetch messages','details':str(e)}), 500

@app.route('/consult_stream')
def consult_stream():
    """Server-Sent Events stream for consult messages + attachments (prototype polling server-side).
    Query args: request_id=<consult_id>
    Emits event every time message count changes (or every 25s keep-alive).
    """
    if db is None:
        return jsonify({'error':'Firestore not initialized'}), 500
    request_id = request.args.get('request_id')
    if not request_id:
        return jsonify({'error':'request_id required'}), 400
    def event_stream():
        last_count = -1
        last_emit = time.time()
        while True:
            try:
                cref = db.collection('consult_requests').document(request_id)
                if not cref.get().exists:
                    yield 'event: end\ndata: {"error":"not_found"}\n\n'
                    break
                msgs = []
                stream = cref.collection('messages').order_by('ts').stream()
                for m in stream:
                    rec = m.to_dict() or {}
                    rec['id'] = m.id
                    msgs.append(rec)
                count = len(msgs)
                now = time.time()
                if count != last_count:
                    attachments = _list_consult_attachments(request_id)
                    payload = json.dumps({'messages': msgs, 'attachments': attachments, 'count': count})
                    yield f'data: {payload}\n\n'
                    last_count = count
                    last_emit = now
                elif (now - last_emit) > 25:
                    yield 'event: heartbeat\ndata: {}\n\n'
                    last_emit = now
                time.sleep(1.8)
            except GeneratorExit:
                break
            except Exception as e:
                yield f'event: error\ndata: {{"error":"{str(e)}"}}\n\n'
                time.sleep(4)
    return Response(event_stream(), mimetype='text/event-stream')

@app.route('/send_consult_message', methods=['POST'])
def send_consult_message():
    if db is None:
        return jsonify({'error':'Firestore not initialized'}), 500
    data = request.get_json() or {}
    request_id = data.get('request_id')
    uid = data.get('uid')
    role = (data.get('role') or '').lower()
    text = (data.get('text') or '').strip()
    if not all([request_id, uid, role, text]):
        return jsonify({'error':'request_id, uid, role, text required'}), 400
    if role not in ('doctor','patient'):
        return jsonify({'error':'role must be doctor or patient'}), 400
    try:
        cref = db.collection('consult_requests').document(request_id)
        snap = cref.get()
        if not snap.exists:
            return jsonify({'error':'Consult not found'}), 404
        meta = snap.to_dict() or {}
        if meta.get('status') != 'accepted':
            return jsonify({'error':'Consult not active'}), 409
        # Basic authorization: ensure uid matches doctor_uid or patient_uid
        if uid not in (meta.get('doctor_uid'), meta.get('patient_uid')):
            return jsonify({'error':'Not authorized for this consult'}), 403
        msg_doc = cref.collection('messages').document()
        payload = {
            'uid': uid,
            'role': role,
            'text': text,
            'ts': firestore.SERVER_TIMESTAMP,
            'created_at': firestore.SERVER_TIMESTAMP
        }
        msg_doc.set(payload)
        return jsonify({'success': True, 'message_id': msg_doc.id, 'echo': {'role': role, 'text': text}}), 200
    except Exception as e:
        return jsonify({'error':'Failed to send message','details':str(e)}), 500

@app.route('/debug_consult', methods=['POST'])
def debug_consult():
    """Diagnostic helper: returns consult meta + message count (no auth - prototype). JSON {id:""}"""
    if db is None:
        return jsonify({'error':'Firestore not initialized'}), 500
    data = request.get_json() or {}
    cid = data.get('id')
    if not cid:
        return jsonify({'error':'id required'}), 400
    try:
        ref = db.collection('consult_requests').document(cid)
        snap = ref.get()
        if not snap.exists:
            return jsonify({'error':'not found'}), 404
        meta = snap.to_dict() or {}
        msgs = list(ref.collection('messages').stream())
        return jsonify({'success': True, 'meta': meta, 'message_count': len(msgs)}), 200
    except Exception as e:
        return jsonify({'error':'debug failure','details':str(e)}), 500

@app.route('/search_patients', methods=['POST'])
def search_patients():
    if db is None:
        return jsonify({'error':'Firestore not initialized'}), 500
    data = request.get_json() or {}
    doctor_uid = data.get('doctor_uid')
    query = (data.get('query') or '').strip().lower()
    if not doctor_uid:
        return jsonify({'error':'doctor_uid required'}), 400
    # Validate doctor
    try:
        ddoc = db.collection('users').document(doctor_uid).get()
        if not ddoc.exists or (ddoc.to_dict() or {}).get('role') != 'doctor':
            return jsonify({'error':'Not authorized'}), 403
    except Exception:
        return jsonify({'error':'Not authorized'}), 403
    try:
        # Simple scan (prototype)
        users_stream = db.collection('users').where('role','==','patient').stream()
        results = []
        for u in users_stream:
            d = u.to_dict() or {}
            pid = str(d.get('patient_id') or '')
            email = (d.get('email') or '')
            dn = d.get('display_name') or ''
            mobile = (d.get('mobile') or '')
            # retro assign if missing and role patient
            if not pid and d.get('role') == 'patient':
                pid = _assign_patient_id_if_missing(u.id) or ''
            haystacks = [email.lower(), pid.lower(), dn.lower(), mobile.lower()]
            if not query or any(query in h for h in haystacks):
                results.append({'uid': u.id, 'email': email, 'patient_id': pid, 'display_name': dn or None, 'mobile': mobile})
            if len(results) >= 100:
                break
        return jsonify({'success': True, 'count': len(results), 'patients': results}), 200
    except Exception as e:
        return jsonify({'error':'Failed to search patients','details':str(e)}), 500

@app.route('/patient_history_overview', methods=['POST'])
def patient_history_overview():
    """Doctor-wide patient history browser with optional fuzzy query across patient_id, name, email.
    JSON: { doctor_uid:'', query?:'' }
    Returns limited recent history per patient (up to 10 records) for quick browsing.
    """
    if db is None:
        return jsonify({'error':'Firestore not initialized'}), 500
    data = request.get_json() or {}
    doctor_uid = data.get('doctor_uid')
    query = (data.get('query') or '').strip().lower()
    if not doctor_uid:
        return jsonify({'error':'doctor_uid required'}), 400
    try:
        ddoc = db.collection('users').document(doctor_uid).get()
        if not ddoc.exists or (ddoc.to_dict() or {}).get('role') != 'doctor':
            return jsonify({'error':'Not authorized'}), 403
    except Exception:
        return jsonify({'error':'Not authorized'}), 403
    try:
        users_stream = db.collection('users').where('role','==','patient').stream()
        out = []
        for u in users_stream:
            d = u.to_dict() or {}
            pid = str(d.get('patient_id') or '')
            if not pid and d.get('role') == 'patient':
                pid = _assign_patient_id_if_missing(u.id) or ''
            email = (d.get('email') or '')
            dn = (d.get('display_name') or '')
            if query and not (query in email.lower() or query in pid.lower() or query in dn.lower()):
                continue
            # recent health history (limit 10)
            history = []
            try:
                hq = db.collection('users').document(u.id).collection('health_history').order_by('created_at', direction=firestore.Query.DESCENDING).limit(10).stream()
                for h in hq:
                    rec = h.to_dict() or {}
                    rec['id'] = h.id
                    history.append(rec)
            except Exception:
                history = []
            out.append({
                'uid': u.id,
                'patient_id': pid,
                'email': email,
                'display_name': dn or None,
                'history': history,
                'history_count': len(history)
            })
            if len(out) >= 300:  # precaution limiter
                break
        # sort by patient_id if present else email
        out.sort(key=lambda x: (x.get('patient_id') or 'ZZZ', x.get('email') or ''))
        return jsonify({'success': True, 'count': len(out), 'patients': out, 'query': query}), 200
    except Exception as e:
        return jsonify({'error':'Failed to build overview','details': str(e)}), 500

@app.route('/get_all_patient_data', methods=['POST'])
def get_all_patient_data():
    """Return comprehensive patient data (health history + consult remarks) optionally filtered by patient_id.
    JSON: { doctor_uid: '', patient_id: 'SS001'? }
    """
    if db is None:
        return jsonify({'error':'Firestore not initialized'}), 500
    data = request.get_json() or {}
    doctor_uid = data.get('doctor_uid')
    filter_pid = (data.get('patient_id') or '').strip()
    if not doctor_uid:
        return jsonify({'error':'doctor_uid required'}), 400
    # Validate doctor
    try:
        ddoc = db.collection('users').document(doctor_uid).get()
        if not ddoc.exists or (ddoc.to_dict() or {}).get('role') != 'doctor':
            return jsonify({'error':'Not authorized'}), 403
    except Exception:
        return jsonify({'error':'Not authorized'}), 403
    try:
        patients_query = db.collection('users').where('role','==','patient')
        stream = patients_query.stream()
        out = []
        for snap in stream:
            doc = snap.to_dict() or {}
            pid = doc.get('patient_id')
            if filter_pid and pid != filter_pid:
                continue
            # Health history
            history = []
            try:
                hstream = db.collection('users').document(snap.id).collection('health_history').order_by('created_at', direction=firestore.Query.DESCENDING).limit(50).stream()
                for h in hstream:
                    hr = h.to_dict() or {}
                    hr['id'] = h.id
                    history.append(hr)
            except Exception:
                history = []
            # Consult remarks (closed consults) involving this patient
            remarks = []
            try:
                # naive scan limited by recent 100 closed consults (optimization area)
                cstream = db.collection('consult_requests').where('patient_uid','==',snap.id).where('status','==','closed').stream()
                for c in cstream:
                    cr = c.to_dict() or {}
                    if 'doctor_remarks' in cr:
                        remarks.append({
                            'consult_id': c.id,
                            'doctor_uid': cr.get('doctor_uid'),
                            'doctor_remarks': cr.get('doctor_remarks'),
                            'closed_at': cr.get('closed_at'),
                            'primary_issue': cr.get('primary_issue') or cr.get('reason')
                        })
            except Exception:
                remarks = []
            out.append({
                'uid': snap.id,
                'patient_id': pid,
                'email': doc.get('email'),
                'display_name': doc.get('display_name'),
                'mobile': doc.get('mobile'),
                'history': history,
                'consult_remarks': remarks
            })
            if filter_pid:
                break
        out.sort(key=lambda x: x.get('patient_id') or '')
        return jsonify({'success': True, 'count': len(out), 'patients': out, 'filtered': bool(filter_pid)}), 200
    except Exception as e:
        return jsonify({'error':'Failed to gather patient data','details': str(e)}), 500

@app.after_request
def add_cors_headers(resp):
    resp.headers.setdefault('Access-Control-Allow-Origin', '*')
    resp.headers.setdefault('Access-Control-Allow-Credentials', 'true')
    resp.headers.setdefault('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With')
    resp.headers.setdefault('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    return resp

@app.errorhandler(500)
def internal_error(e):
    resp = jsonify({'error':'internal server error','details': str(e)} )
    resp.status_code = 500
    resp.headers.setdefault('Access-Control-Allow-Origin', '*')
    resp.headers.setdefault('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With')
    resp.headers.setdefault('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    return resp
for _ep in [
    '/request_consult','/list_open_consults','/accept_consult','/list_my_consults',
    '/get_consult_messages','/send_consult_message','/search_patients','/get_patient_history',
    '/get_patient_active_consult','/get_chat_session_messages','/list_chat_sessions','/analyze_chat_session','/auto_analyze_session','/get_profile','/get_all_patient_data','/update_profile','/rename_chat_session','/place_autocomplete','/upload_consult_attachment','/list_consult_attachments','/get_consult_attachment','/search_medical_info','/get_condition_info'
]:
    app.add_url_rule(_ep, methods=['OPTIONS'], endpoint=f'options_{_ep.strip("/")}', view_func=lambda: ('',204))

# Add OPTIONS for new endpoints
for _ep in ['/reject_consult','/close_consult']:
    app.add_url_rule(_ep, methods=['OPTIONS'], endpoint=f'options_{_ep.strip("/")}', view_func=lambda: ('',204))
# Add OPTIONS for new overview endpoint
app.add_url_rule('/patient_history_overview', methods=['OPTIONS'], endpoint='options_patient_history_overview', view_func=lambda: ('',204))

@app.route('/upload_consult_attachment', methods=['POST'])
def upload_consult_attachment():
    """Upload an attachment for a consult (patient or doctor). JSON: { consult_id:'', uid:'', role:'patient|doctor', filename:'', content_base64:'' }
    Prototype: stores to disk; metadata not persisted to Firestore yet except listing derived from filenames.
    """
    data = request.get_json() or {}
    consult_id = data.get('consult_id'); uid = data.get('uid'); role = (data.get('role') or '').lower()
    filename = data.get('filename'); b64 = data.get('content_base64')
    if not all([consult_id, uid, filename, b64]):
        return jsonify({'error':'consult_id, uid, filename, content_base64 required'}), 400
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_ATTACHMENT_EXT:
        return jsonify({'error': f'Extension {ext} not allowed'}), 400
    try:
        raw = base64.b64decode(b64)
    except Exception:
        return jsonify({'error':'Invalid base64'}), 400
    if len(raw) > MAX_ATTACHMENT_BYTES:
        return jsonify({'error':'File too large (limit 2MB)'}), 400
    path = _consult_attachment_path(consult_id, filename)
    try:
        with open(path, 'wb') as f:
            f.write(raw)
        return jsonify({'success': True, 'filename': filename, 'size': len(raw)}), 201
    except Exception as e:
        return jsonify({'error':'Failed to store file','details': str(e)}), 500

@app.route('/list_consult_attachments', methods=['POST'])
def list_consult_attachments():
    data = request.get_json() or {}
    consult_id = data.get('consult_id')
    if not consult_id:
        return jsonify({'error':'consult_id required'}), 400
    files = _list_consult_attachments(consult_id)
    return jsonify({'success': True, 'files': files}), 200

@app.route('/get_consult_attachment', methods=['POST'])
def get_consult_attachment():
    data = request.get_json() or {}
    consult_id = data.get('consult_id'); filename = data.get('filename')
    if not consult_id or not filename:
        return jsonify({'error':'consult_id and filename required'}), 400
    path = _consult_attachment_path(consult_id, filename)
    if not os.path.exists(path):
        return jsonify({'error':'not found'}), 404
    try:
        with open(path,'rb') as f:
            raw = f.read()
        encoded = base64.b64encode(raw).decode('utf-8')
        return jsonify({'success': True, 'filename': filename, 'content_base64': encoded}), 200
    except Exception as e:
        return jsonify({'error':'Failed to read file','details': str(e)}), 500


@app.route('/get_patient_history', methods=['POST'])
def get_patient_history():
    """Doctor-scoped patient history: returns health records and chat session summaries.
    JSON: { doctor_uid: '', patient_uid: '' } OR { doctor_uid:'', patient_id:'123456' }
    """
    if db is None:
        return jsonify({'error':'Firestore not initialized'}), 500
    data = request.get_json() or {}
    doctor_uid = data.get('doctor_uid')
    patient_uid = data.get('patient_uid')
    patient_id = data.get('patient_id')
    if not doctor_uid:
        return jsonify({'error':'doctor_uid required'}), 400
    try:
        ddoc = db.collection('users').document(doctor_uid).get()
        if not ddoc.exists or (ddoc.to_dict() or {}).get('role') != 'doctor':
            return jsonify({'error':'Not authorized'}), 403
    except Exception:
        return jsonify({'error':'Not authorized'}), 403
    if not patient_uid and patient_id:
        try:
            q = db.collection('users').where('patient_id','==',str(patient_id)).limit(1).stream()
            for doc in q:
                patient_uid = doc.id
                break
        except Exception:
            pass
    if not patient_uid:
        return jsonify({'error':'patient not found'}), 404
    try:
        user_ref = db.collection('users').document(patient_uid)
        user_doc = user_ref.get()
        if not user_doc.exists:
            return jsonify({'error':'patient not found'}), 404
        profile = user_doc.to_dict() or {}
        history = []
        try:
            for h in user_ref.collection('health_history').order_by('created_at', direction=firestore.Query.DESCENDING).limit(100).stream():
                rec = h.to_dict() or {}
                rec['id'] = h.id
                history.append(rec)
        except Exception:
            pass
        sessions = []
        try:
            for s in user_ref.collection('chat_sessions').order_by('last_updated', direction=firestore.Query.DESCENDING).limit(50).stream():
                sd = s.to_dict() or {}
                sd['id'] = s.id
                snippet = None
                try:
                    msgs_stream = s.reference.collection('messages').order_by('ts').limit(2).stream()
                    parts = []
                    for m in msgs_stream:
                        md = m.to_dict() or {}
                        parts.append((md.get('role') or '') + ': ' + (md.get('text') or '')[:120])
                    if parts:
                        snippet = ' | '.join(parts)[:240]
                except Exception:
                    pass
                if snippet and not sd.get('summary_excerpt'):
                    sd['summary_excerpt'] = snippet
                sessions.append(sd)
        except Exception:
            pass
        return jsonify({'success': True, 'patient_uid': patient_uid, 'patient_id': profile.get('patient_id'), 'email': profile.get('email'), 'health_history': history, 'chat_sessions': sessions}), 200
    except Exception as e:
        return jsonify({'error':'Failed to fetch patient history','details':str(e)}), 500

@app.route('/list_chat_sessions', methods=['POST'])
def list_chat_sessions():
    if db is None:
        return jsonify({'error':'Firestore not initialized'}), 500
    data = request.get_json() or {}
    uid = data.get('uid')
    limit = int(data.get('limit') or 20)
    if not uid:
        return jsonify({'error':'uid required'}), 400
    try:
        ref = db.collection('users').document(uid).collection('chat_sessions')
        # We may not have indexes; stream all then sort in memory capped to 100
        sessions = []
        for s in ref.stream():
            d = s.to_dict() or {}
            d['id'] = s.id
            if not d.get('title'):
                try:
                    first_msg_stream = s.reference.collection('messages').order_by('ts').limit(1).stream()
                    for fm in first_msg_stream:
                        mrec = fm.to_dict() or {}
                        role_m = (mrec.get('role') or '').lower()
                        if role_m in ('user','patient','doctor') and mrec.get('text'):
                            d['title'] = (mrec.get('text') or '').strip().split('\n')[0][:80]
                            break
                except Exception:
                    pass
            sessions.append(d)
        def _ts(x):
            ts = x.get('last_updated') or x.get('created_at')
            try:
                if hasattr(ts,'timestamp'): return ts.timestamp()
            except Exception: pass
            return 0
        sessions.sort(key=_ts, reverse=True)
        sessions = sessions[:limit]
        return jsonify({'success': True, 'count': len(sessions), 'sessions': sessions}), 200
    except Exception as e:
        return jsonify({'error':'Failed to list chat sessions','details':str(e)}), 500

@app.route('/get_chat_session_messages', methods=['POST'])
def get_chat_session_messages():
    if db is None:
        return jsonify({'error':'Firestore not initialized'}), 500
    data = request.get_json() or {}
    uid = data.get('uid')
    session_id = data.get('session_id')
    if not uid or not session_id:
        return jsonify({'error':'uid and session_id required'}), 400
    try:
        sess_ref = db.collection('users').document(uid).collection('chat_sessions').document(session_id)
        if not sess_ref.get().exists:
            return jsonify({'error':'session not found'}), 404
        msgs = []
        for m in sess_ref.collection('messages').order_by('ts').stream():
            md = m.to_dict() or {}
            md['id'] = m.id
            msgs.append(md)
        meta = sess_ref.get().to_dict() or {}
        return jsonify({'success': True, 'messages': msgs, 'meta': meta}), 200
    except Exception as e:
        return jsonify({'error':'Failed to fetch session messages','details':str(e)}), 500

@app.route('/rename_chat_session', methods=['POST'])
def rename_chat_session():
    if db is None:
        return jsonify({'error':'Firestore not initialized'}), 500
    data = request.get_json() or {}
    uid = data.get('uid')
    session_id = data.get('session_id')
    new_title = (data.get('title') or '').strip()
    if not uid or not session_id or not new_title:
        return jsonify({'error':'uid, session_id, title required'}), 400
    if len(new_title) > 120:
        new_title = new_title[:120]
    try:
        sess_ref = db.collection('users').document(uid).collection('chat_sessions').document(session_id)
        if not sess_ref.get().exists:
            return jsonify({'error':'not found'}), 404
        sess_ref.set({'title': new_title, 'title_auto': False, 'title_renamed_at': firestore.SERVER_TIMESTAMP}, merge=True)
        return jsonify({'success': True, 'session_id': session_id, 'title': new_title}), 200
    except Exception as e:
        return jsonify({'error':'Failed to rename','details': str(e)}), 500

@app.route('/get_patient_active_consult', methods=['POST'])
def get_patient_active_consult():
    if db is None:
        return jsonify({'error':'Firestore not initialized'}), 500
    data = request.get_json() or {}
    uid = data.get('uid')
    if not uid:
        return jsonify({'error':'uid required'}), 400
    try:
        q = db.collection('consult_requests').where('patient_uid','==',uid).stream()
        found = []
        for c in q:
            d = c.to_dict() or {}
            st = d.get('status')
            if st in ('open','accepted'):
                d['id'] = c.id
                found.append(d)
        def _ts(x):
            ts = x.get('accepted_at') or x.get('created_at')
            try:
                if hasattr(ts,'timestamp'): return ts.timestamp()
            except Exception: pass
            return 0
        found.sort(key=_ts, reverse=True)
        if not found:
            return jsonify({'success': True, 'active': None}), 200
        active = found[0]
        messages = []
        if active.get('status')=='accepted':
            try:
                ref = db.collection('consult_requests').document(active['id']).collection('messages')
                for m in ref.order_by('ts').limit(50).stream():
                    md = m.to_dict() or {}
                    md['id'] = m.id
                    messages.append(md)
            except Exception:
                pass
        return jsonify({'success': True, 'active': active, 'messages': messages}), 200
    except Exception as e:
        return jsonify({'error':'Failed to fetch active consult','details':str(e)}), 500

if __name__ == '__main__':
    app.run(port=5000, debug=True)
