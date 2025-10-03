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
CORS(app)

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
        if db is not None:
            try:
                db.collection('users').document(user.uid).set({
                    'email': user.email,
                    'created_at': firestore.SERVER_TIMESTAMP,
                    'uid': user.uid
                }, merge=True)
                profile_created = True
            except Exception as fe:
                logging.warning(f"Firestore profile creation failed for {user.uid}: {fe}")

        return jsonify({
            'success': True,
            'message': 'User created successfully',
            'uid': user.uid,
            'email': user.email,
            'profileCreated': profile_created
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
        
        return jsonify({
            'success': True,
            'message': 'User found',
            'uid': user.uid,
            'email': user.email,
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

        return jsonify({
            'message': advice,
            'language': original_language,
            'translatedInbound': translated_inbound
        }), 200

    except Exception:
        return jsonify({'error': 'Failed to process chat'}), 500

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

    try:
        user_doc_ref = db.collection('users').document(uid)
        appointments_ref = user_doc_ref.collection('appointments')
        appointment.setdefault('created_at', firestore.SERVER_TIMESTAMP)
        new_doc_ref = appointments_ref.document()
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

if __name__ == '__main__':
    app.run(port=5000, debug=True)
