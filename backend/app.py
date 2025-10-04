from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import random
import firebase_admin
from firebase_admin import credentials, firestore, auth
import logging, re, os, textwrap, time
import overpass
import requests  # Added for Hugging Face zero-shot classification

# Optional Gemini / Generative AI
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

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
        user = auth.create_user(email=email, password=password)

        profile_created = False
        role_status = 'active'
        patient_id = None
        if role == 'doctor':
            # Newly registered doctors require verification
            role_status = 'pending'
        else:
            # Generate unique 6-digit patient id
            if db is not None:
                attempt = 0
                while attempt < 10:
                    candidate = str(random.randint(100000, 999999))
                    # Ensure uniqueness
                    exists = False
                    try:
                        snap = db.collection('users').where('patient_id','==',candidate).limit(1).stream()
                        for _ in snap:
                            exists = True
                            break
                    except Exception:
                        exists = False
                    if not exists:
                        patient_id = candidate
                        break
                    attempt += 1
                if patient_id is None:
                    patient_id = str(random.randint(100000, 999999))  # fallback even if uniqueness uncertain
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
            'patientId': patient_id
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
    """Personalized chat endpoint.
    Expects JSON body: { "uid": "<user uid>", "message": "<user message>" }
    Steps:
      1. Fetch user's past symptoms from health_history.
      2. Detect if current message mentions any past symptom (recurrence).
      3. Match keyword advice from responses data.
      4. If recurring and advice found, prepend personalized notice.
      5. Return advice or default fallback.
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
                detected_language = detect(user_message)
                # Heuristic: very short / simple ASCII phrases often misclassified (e.g. as 'da')
                ascii_ratio = sum(1 for ch in user_message if ord(ch) < 128) / max(1, len(user_message))
                english_stop_hits = sum(1 for w in re.findall(r"[a-zA-Z']+", user_message.lower()) if w in {'i','am','is','are','the','and','of','to','in','cold','feel','feeling','hurt','pain','have','having'})
                # If detected non-English but looks strongly like basic English, override
                if detected_language != 'en' and ascii_ratio > 0.95 and english_stop_hits >= 1:
                    original_language = 'en'
                else:
                    original_language = detected_language
                if original_language != 'en':
                    user_message = GoogleTranslator(source=original_language, target='en').translate(user_message)
                    translated_inbound = True
            except Exception:
                original_language = 'en'
                translated_inbound = False

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
                # Swallow Firestore history fetch errors; continue without personalization
                past_symptoms = []

        # --- Step 2: Check for Recurring Symptoms ---
        user_message_lower = user_message.lower()
        is_recurring = False
        for s in past_symptoms:
            if s and s in user_message_lower:
                is_recurring = True
                break

        # --- Step 3: Use Standard Keyword Logic ---
        advice = None
        for keyword, text in responses.items():
            if keyword.lower() in user_message_lower:
                advice = text
                break

        # --- Step 4: Personalize the Response ---
        if advice and is_recurring:
            personalized_prefix = (
                "I see from your history that you've experienced this before. Please monitor your symptoms and seek professional help if they persist or worsen.\n\n"
            )
            advice = personalized_prefix + advice

        # --- Step 5: Return the Final Response ---
        if not advice:
            advice = "I'm sorry, I don't have information on that. Please consult a doctor for further help."
        # --- Optional Translation (Outbound) ---
        if TRANSLATION_AVAILABLE and original_language != 'en':
            try:
                advice_translated = GoogleTranslator(source='en', target=original_language).translate(advice)
                advice = advice_translated
            except Exception:
                # Keep English fallback if translation fails
                pass

        # ---- Persist chat session & messages (prototype) ----
        stored_session_id = session_id
        if db is not None and uid:
            try:
                sessions_ref = db.collection('users').document(uid).collection('chat_sessions')
                # Create session document if not provided
                if not stored_session_id:
                    new_ref = sessions_ref.document()
                    new_ref.set({
                        'created_at': firestore.SERVER_TIMESTAMP,
                        'last_updated': firestore.SERVER_TIMESTAMP,
                        'major_issue': None,
                        'message_count': 0
                    })
                    stored_session_id = new_ref.id
                # Append user + bot messages
                if stored_session_id:
                    sess_doc_ref = sessions_ref.document(stored_session_id)
                    # store two message docs
                    msg_coll = sess_doc_ref.collection('messages')
                    now_server = firestore.SERVER_TIMESTAMP
                    msg_coll.add({'role': 'user', 'text': user_message, 'ts': now_server})
                    msg_coll.add({'role': 'bot', 'text': advice, 'ts': now_server})
                    # increment message_count (read-modify-write minimal)
                    sess_doc_ref.set({'last_updated': firestore.SERVER_TIMESTAMP, 'message_count': firestore.Increment(2)}, merge=True)
            except Exception:
                pass

        return jsonify({
            'message': advice,
            'language': original_language,
            'translatedInbound': translated_inbound,
            'session_id': stored_session_id
        }), 200

    except Exception:
        return jsonify({'error': 'Failed to process chat'}), 500

@app.route('/analyze_chat_session', methods=['POST'])
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

    # Try to match known response keywords (keys of responses json)
    # Normalize response keys (e.g. "fever" or multi words) -> count presence
    candidate_scores = {}
    for key in responses.keys():
        k_low = key.lower()
        # simple exact token match OR substring presence
        score = 0
        if k_low in freq:
            score += freq[k_low] * 3  # strong weight
        # Boost if phrase words appear
        parts = re.findall(r'[a-zA-Z]+', k_low)
        overlap = sum(freq.get(p,0) for p in parts)
        score += overlap
        if score > 0:
            candidate_scores[key] = score

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
    uid = data.get('uid')
    record = data.get('record')

    # Validate inputs
    if not uid:
        return jsonify({'error': 'Field "uid" is required in JSON body'}), 400
    if not isinstance(record, dict) or not record:
        return jsonify({'error': 'Field "record" (non-empty object) is required in JSON body'}), 400

    try:
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

@app.route('/delete_health_record', methods=['POST'])
def delete_health_record():
    """Delete a health history record.
    Expects JSON: { "uid": "..", "id": "recordDocId" }
    """
    if db is None:
        return jsonify({'error': 'Firestore not initialized'}), 500
    data = request.get_json() or {}
    uid = data.get('uid')
    rec_id = data.get('id')
    if not uid or not rec_id:
        return jsonify({'error': 'Fields "uid" and "id" are required'}), 400
    try:
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
    rec_id = data.get('id')
    updates = data.get('updates') or {}
    if not uid or not rec_id:
        return jsonify({'error': 'Fields "uid" and "id" are required'}), 400
    if not isinstance(updates, dict) or not updates:
        return jsonify({'error': 'Field "updates" (non-empty object) is required'}), 400
    try:
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
        cref.set({'status':'closed','closed_at':firestore.SERVER_TIMESTAMP}, merge=True)
        return jsonify({'success': True, 'request_id': request_id, 'status':'closed'}), 200
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
        return jsonify({'success': True, 'messages': msgs, 'status': meta.get('status'), 'doctor_uid': meta.get('doctor_uid'), 'patient_uid': meta.get('patient_uid')}), 200
    except Exception as e:
        return jsonify({'error':'Failed to fetch messages','details':str(e)}), 500

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
            if not query or query in email.lower() or query == pid.lower():
                results.append({'uid': u.id, 'email': email, 'patient_id': pid})
            if len(results) >= 50:
                break
        return jsonify({'success': True, 'count': len(results), 'patients': results}), 200
    except Exception as e:
        return jsonify({'error':'Failed to search patients','details':str(e)}), 500

@app.after_request
def add_cors_headers(resp):
    # Double-layer CORS safety in case Flask-CORS missed something
    resp.headers.setdefault('Access-Control-Allow-Origin', '*')
    resp.headers.setdefault('Access-Control-Allow-Credentials', 'true')
    resp.headers.setdefault('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With')
    resp.headers.setdefault('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    return resp

# Explicit OPTIONS handlers (some browsers/frameworks can be picky for non-simple POST endpoints)
for _ep in [
    '/request_consult','/list_open_consults','/accept_consult','/list_my_consults',
    '/get_consult_messages','/send_consult_message','/search_patients','/get_patient_history',
    '/get_patient_active_consult','/get_chat_session_messages','/list_chat_sessions'
]:
    app.add_url_rule(_ep, methods=['OPTIONS'], endpoint=f'options_{_ep.strip("/")}', view_func=lambda: ('',204))

# Add OPTIONS for new endpoints
for _ep in ['/reject_consult','/close_consult']:
    app.add_url_rule(_ep, methods=['OPTIONS'], endpoint=f'options_{_ep.strip("/")}', view_func=lambda: ('',204))


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
    # Validate doctor
    try:
        ddoc = db.collection('users').document(doctor_uid).get()
        if not ddoc.exists or (ddoc.to_dict() or {}).get('role') != 'doctor':
            return jsonify({'error':'Not authorized'}), 403
    except Exception:
        return jsonify({'error':'Not authorized'}), 403
    # Resolve patient uid by patient_id if necessary
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
        # Health history
        history = []
        try:
            for h in user_ref.collection('health_history').order_by('created_at', direction=firestore.Query.DESCENDING).limit(100).stream():
                rec = h.to_dict() or {}
                rec['id'] = h.id
                history.append(rec)
        except Exception:
            pass
        # Chat sessions summaries
        sessions = []
        try:
            for s in user_ref.collection('chat_sessions').order_by('last_updated', direction=firestore.Query.DESCENDING).limit(50).stream():
                sd = s.to_dict() or {}
                sd['id'] = s.id
                # Fetch a small snippet from first 2 messages
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

# -------------------- Patient Chat / Session Retrieval --------------------
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
        # sort newest
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
        # include limited messages if accepted
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
    # Ensure all routes are registered before starting the development server
    # (Moved to end so newly added routes below previous position are active.)
    app.run(port=5000, debug=True)
