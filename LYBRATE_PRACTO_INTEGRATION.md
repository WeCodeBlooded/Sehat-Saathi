# Lybrate & Practo Integration Guide for Sehat-Saathi

## Overview
This guide explains how to integrate Lybrate and Practo APIs into your Sehat-Saathi healthcare platform to provide enhanced doctor discovery, teleconsultation booking, and lab test services.

## Benefits of Integration

### 1. **Expanded Doctor Network**
- Access to thousands of verified doctors across specialties
- Real-time availability and appointment booking
- Multiple consultation modes (video, phone, chat)
- Verified credentials and patient reviews

### 2. **Professional Teleconsultation**
- Direct integration with doctor scheduling systems
- Automated meeting link generation
- Payment gateway integration
- Follow-up and prescription management

### 3. **Comprehensive Lab Services**
- Extensive test catalog with home collection
- Competitive pricing and package deals
- Multiple lab partner networks
- Digital report delivery

### 4. **Enhanced User Experience**
- Seamless booking across platforms
- Unified search and comparison
- Integrated health records
- Professional medical services

## API Integration Setup

### Step 1: Get API Keys

#### Lybrate API
```bash
# Contact Lybrate Business Development
# Email: business@lybrate.com
# Website: https://business.lybrate.com/api

# Required Information:
- Company Details
- Use Case Description
- Expected Monthly Volume
- Compliance Certifications
```

#### Practo API
```bash
# Contact Practo Partner Solutions
# Email: partners@practo.com
# Website: https://www.practo.com/partners

# Required Information:
- Healthcare Business License
- Technical Integration Plan
- Compliance Documentation
- Revenue Sharing Model
```

### Step 2: Environment Configuration

```bash
# Copy the example environment file
cp backend/.env.example backend/.env

# Add your API keys
LYBRATE_API_KEY=your_lybrate_api_key
LYBRATE_PARTNER_ID=your_partner_id
PRACTO_API_KEY=your_practo_api_key
PRACTO_CLIENT_ID=your_client_id

# Enable features
ENABLE_EXTERNAL_DOCTOR_SEARCH=true
ENABLE_LAB_TESTS_BOOKING=true
ENABLE_HEALTH_RECORDS_SYNC=true
```

### Step 3: Install Dependencies

```bash
cd backend
pip install requests python-dotenv

cd ../frontend
npm install
```

### Step 4: Test Integration

```bash
# Start backend
cd backend
python app.py

# Test doctor search
curl -X POST http://localhost:5000/search_external_doctors \
  -H "Content-Type: application/json" \
  -d '{"specialty": "cardiology", "location": "Mumbai"}'

# Test lab tests
curl -X POST http://localhost:5000/get_lab_tests \
  -H "Content-Type: application/json" \
  -d '{"location": "Mumbai", "category": "blood"}'
```

## Frontend Integration

### Add New Components to App.jsx

```jsx
import EnhancedDoctorSearch from './components/EnhancedDoctorSearch';
import LabTestBooking from './components/LabTestBooking';

// Add to FEATURE_SETS
const FEATURE_SETS = {
  patient: {
    chatbot: { label: 'Chatbot', icon: '💬' },
    tele: { label: 'Tele-Counselling', icon: '🗓️' },
    enhanced_doctors: { label: 'Find Doctors', icon: '👩‍⚕️' },
    lab_tests: { label: 'Lab Tests', icon: '🧪' },
    hospitals: { label: 'Hospital Locator', icon: '🗺️' },
    history: { label: 'Health History', icon: '📘' }
  }
};

// Add to component rendering
{activeFeature === 'enhanced_doctors' && (
  <EnhancedDoctorSearch backend={backend} uid={user?.uid} />
)}
{activeFeature === 'lab_tests' && (
  <LabTestBooking backend={backend} uid={user?.uid} />
)}
```

## Revenue Model Integration

### Commission-Based Booking
```python
# In booking endpoints, calculate commission
def calculate_commission(booking_amount, platform):
    commission_rates = {
        'lybrate': 0.15,  # 15%
        'practo': 0.12,   # 12%
        'local': 0.05     # 5% for local doctors
    }
    
    commission = booking_amount * commission_rates.get(platform, 0.10)
    return {
        'gross_amount': booking_amount,
        'commission': commission,
        'net_amount': booking_amount - commission
    }
```

### Subscription Plans
```python
# Enhanced features for premium users
def check_subscription_access(uid, feature):
    user_plan = get_user_subscription(uid)
    
    feature_access = {
        'basic': ['local_doctors', 'basic_chat'],
        'premium': ['external_doctors', 'lab_tests', 'priority_support'],
        'enterprise': ['all_features', 'dedicated_support', 'custom_integration']
    }
    
    return feature in feature_access.get(user_plan, [])
```

## Data Privacy & Compliance

### HIPAA Compliance
```python
# Encrypt sensitive health data
from cryptography.fernet import Fernet

class HealthDataEncryption:
    def __init__(self):
        self.key = os.getenv('ENCRYPTION_KEY')
        self.cipher = Fernet(self.key)
    
    def encrypt_health_data(self, data):
        return self.cipher.encrypt(json.dumps(data).encode())
    
    def decrypt_health_data(self, encrypted_data):
        decrypted = self.cipher.decrypt(encrypted_data)
        return json.loads(decrypted.decode())
```

### Audit Logging
```python
def log_medical_access(user_id, action, data_type, platform=None):
    audit_log = {
        'timestamp': datetime.utcnow().isoformat(),
        'user_id': user_id,
        'action': action,  # 'search', 'book', 'view', 'cancel'
        'data_type': data_type,  # 'doctor', 'lab_test', 'health_record'
        'platform': platform,  # 'lybrate', 'practo', 'local'
        'ip_address': request.remote_addr,
        'user_agent': request.headers.get('User-Agent')
    }
    
    # Store in secure audit database
    db.collection('audit_logs').add(audit_log)
```

## Monitoring & Analytics

### API Performance Monitoring
```python
import time
from functools import wraps

def monitor_api_performance(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        
        try:
            result = func(*args, **kwargs)
            success = True
            error = None
        except Exception as e:
            result = None
            success = False
            error = str(e)
        
        end_time = time.time()
        
        # Log performance metrics
        metrics = {
            'function': func.__name__,
            'duration': end_time - start_time,
            'success': success,
            'error': error,
            'timestamp': datetime.utcnow()
        }
        
        # Send to monitoring service
        log_performance_metrics(metrics)
        
        if not success:
            raise Exception(error)
        
        return result
    
    return wrapper
```

### Business Analytics
```python
def track_business_metrics(event_type, user_id, platform, amount=None):
    metrics = {
        'event_type': event_type,  # 'search', 'booking', 'payment'
        'user_id': user_id,
        'platform': platform,
        'amount': amount,
        'timestamp': datetime.utcnow(),
        'source': 'sehat_saathi'
    }
    
    # Send to analytics service (Google Analytics, Mixpanel, etc.)
    analytics_service.track(metrics)
```

## Scaling Considerations

### Rate Limiting
```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

@app.route('/search_external_doctors', methods=['POST'])
@limiter.limit("10 per minute")
def search_external_doctors():
    # Implementation with rate limiting
    pass
```

### Caching Strategy
```python
from flask_caching import Cache

cache = Cache(app, config={
    'CACHE_TYPE': 'redis',
    'CACHE_REDIS_URL': os.getenv('REDIS_URL')
})

@cache.memoize(timeout=300)  # Cache for 5 minutes
def get_doctor_availability(doctor_id, date):
    # Cache expensive API calls
    return external_api.get_availability(doctor_id, date)
```

### Load Balancing
```nginx
# nginx.conf
upstream sehat_saathi_backend {
    server 127.0.0.1:5000 weight=3;
    server 127.0.0.1:5001 weight=2;
    server 127.0.0.1:5002 weight=1;
}

server {
    listen 80;
    server_name sehat-saathi.com;
    
    location /api {
        proxy_pass http://sehat_saathi_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Future Enhancements

### AI-Powered Recommendations
- Symptom-to-doctor matching using NLP
- Personalized lab test suggestions
- Health risk assessment integration

### Blockchain Integration
- Secure health record sharing
- Immutable prescription tracking
- Decentralized identity verification

### IoT Device Integration
- Wearable device data sync
- Remote monitoring capabilities
- Real-time health alerts

## Support & Maintenance

### Error Handling
```python
def handle_external_api_error(platform, error):
    error_mapping = {
        'timeout': 'Service temporarily unavailable. Please try again.',
        'unauthorized': 'API authentication failed. Contact support.',
        'rate_limit': 'Too many requests. Please wait before retrying.',
        'not_found': 'Requested resource not available.'
    }
    
    # Log error for monitoring
    logger.error(f"{platform} API error: {error}")
    
    # Return user-friendly message
    return error_mapping.get(error.type, 'Service error occurred.')
```

### Health Checks
```python
@app.route('/health')
def health_check():
    checks = {
        'database': check_database_connection(),
        'lybrate_api': check_lybrate_connectivity(),
        'practo_api': check_practo_connectivity(),
        'redis_cache': check_redis_connection()
    }
    
    all_healthy = all(checks.values())
    
    return jsonify({
        'status': 'healthy' if all_healthy else 'degraded',
        'checks': checks,
        'timestamp': datetime.utcnow().isoformat()
    }), 200 if all_healthy else 503
```

This integration will transform your Sehat-Saathi platform into a comprehensive healthcare marketplace with professional medical services, significantly increasing your platform's value proposition and revenue potential.