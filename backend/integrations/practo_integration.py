"""
Practo API Integration for Healthcare Services
Provides access to doctors, clinics, lab tests, and health records
"""

import requests
import json
from typing import Dict, List, Optional
import logging
from datetime import datetime, timedelta

class PractoAPI:
    def __init__(self, api_key: str, base_url: str = "https://api.practo.com/v1"):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'X-API-Version': '1.0'
        }
    
    def search_doctors(self, specialty: str, city: str, area: str = "",
                      consultation_type: str = "online", limit: int = 15) -> List[Dict]:
        """
        Search doctors on Practo platform
        """
        try:
            params = {
                'specialization': specialty,
                'city': city,
                'area': area,
                'consultation_type': consultation_type,  # online, clinic, both
                'limit': limit,
                'sort_by': 'rating'
            }
            
            response = requests.get(
                f"{self.base_url}/doctors/search",
                headers=self.headers,
                params=params,
                timeout=25
            )
            
            if response.status_code == 200:
                data = response.json()
                return self._format_practo_doctors(data.get('data', []))
            else:
                logging.error(f"Practo API error: {response.status_code}")
                return []
                
        except Exception as e:
            logging.error(f"Error searching Practo doctors: {e}")
            return []
    
    def search_clinics_hospitals(self, location: str, specialty: str = "", 
                               radius_km: float = 10.0) -> List[Dict]:
        """
        Search for clinics and hospitals near a location
        """
        try:
            params = {
                'location': location,
                'specialty': specialty,
                'radius': radius_km,
                'type': 'hospital,clinic',
                'verified_only': True
            }
            
            response = requests.get(
                f"{self.base_url}/healthcare-providers/search",
                headers=self.headers,
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return self._format_healthcare_providers(data.get('providers', []))
            return []
            
        except Exception as e:
            logging.error(f"Error searching Practo providers: {e}")
            return []
    
    def get_available_lab_tests(self, location: str, test_category: str = "") -> List[Dict]:
        """
        Get available lab tests and health checkup packages
        """
        try:
            params = {
                'location': location,
                'category': test_category,  # blood, urine, cardiac, diabetes, etc.
                'home_collection': True
            }
            
            response = requests.get(
                f"{self.base_url}/lab-tests/search",
                headers=self.headers,
                params=params,
                timeout=25
            )
            
            if response.status_code == 200:
                data = response.json()
                return self._format_lab_tests(data.get('tests', []))
            return []
            
        except Exception as e:
            logging.error(f"Error getting lab tests: {e}")
            return []
    
    def book_appointment(self, doctor_id: str, patient_info: Dict, 
                        appointment_details: Dict) -> Dict:
        """
        Book appointment with doctor through Practo
        """
        try:
            booking_data = {
                'doctor_id': doctor_id,
                'patient': {
                    'name': patient_info.get('name'),
                    'phone': patient_info.get('phone'),
                    'email': patient_info.get('email'),
                    'age': patient_info.get('age'),
                    'gender': patient_info.get('gender')
                },
                'appointment': {
                    'date': appointment_details.get('date'),
                    'time': appointment_details.get('time'),
                    'type': appointment_details.get('type', 'consultation'),
                    'symptoms': appointment_details.get('symptoms', ''),
                    'consultation_mode': appointment_details.get('mode', 'video')
                }
            }
            
            response = requests.post(
                f"{self.base_url}/appointments/book",
                headers=self.headers,
                json=booking_data,
                timeout=30
            )
            
            if response.status_code == 201:
                result = response.json()
                return {
                    'success': True,
                    'appointment_id': result.get('appointment_id'),
                    'booking_reference': result.get('booking_reference'),
                    'payment_link': result.get('payment_url'),
                    'meeting_details': result.get('meeting_info'),
                    'confirmation': result
                }
            else:
                return {
                    'success': False,
                    'error': f"Booking failed: {response.text}"
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f"Booking error: {str(e)}"
            }
    
    def get_health_records(self, patient_id: str) -> Dict:
        """
        Retrieve patient's health records and medical history
        """
        try:
            response = requests.get(
                f"{self.base_url}/patients/{patient_id}/health-records",
                headers=self.headers,
                timeout=20
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'medical_history': data.get('medical_history', []),
                    'prescriptions': data.get('prescriptions', []),
                    'lab_reports': data.get('lab_reports', []),
                    'vaccination_records': data.get('vaccinations', []),
                    'allergies': data.get('allergies', []),
                    'chronic_conditions': data.get('chronic_conditions', [])
                }
            return {}
            
        except Exception as e:
            logging.error(f"Error getting health records: {e}")
            return {}
    
    def _format_practo_doctors(self, doctors: List[Dict]) -> List[Dict]:
        """
        Format Practo doctor data for Sehat-Saathi
        """
        formatted = []
        for doc in doctors:
            formatted.append({
                'id': doc.get('id'),
                'name': doc.get('name'),
                'specialty': doc.get('specialization'),
                'experience_years': doc.get('experience', 0),
                'rating': doc.get('rating', 0.0),
                'total_reviews': doc.get('review_count', 0),
                'consultation_fee': doc.get('fee', 0),
                'clinic_name': doc.get('clinic', {}).get('name', ''),
                'clinic_address': doc.get('clinic', {}).get('address', ''),
                'languages': doc.get('languages', []),
                'qualifications': doc.get('qualifications', []),
                'profile_image': doc.get('profile_photo'),
                'available_modes': doc.get('consultation_modes', []),
                'next_available': doc.get('next_slot'),
                'bio': doc.get('about', ''),
                'practo_profile_url': doc.get('profile_url'),
                'source': 'practo'
            })
        return formatted
    
    def _format_healthcare_providers(self, providers: List[Dict]) -> List[Dict]:
        """
        Format healthcare provider data
        """
        formatted = []
        for provider in providers:
            formatted.append({
                'id': provider.get('id'),
                'name': provider.get('name'),
                'type': provider.get('type', 'hospital'),
                'address': provider.get('address'),
                'latitude': provider.get('coordinates', {}).get('lat'),
                'longitude': provider.get('coordinates', {}).get('lng'),
                'phone': provider.get('phone'),
                'specialties': provider.get('specializations', []),
                'rating': provider.get('rating', 0.0),
                'total_reviews': provider.get('reviews_count', 0),
                'facilities': provider.get('facilities', []),
                'insurance_accepted': provider.get('insurance_partners', []),
                'emergency_services': provider.get('emergency', False),
                'distance_km': provider.get('distance'),
                'practo_url': provider.get('profile_url'),
                'source': 'practo'
            })
        return formatted
    
    def _format_lab_tests(self, tests: List[Dict]) -> List[Dict]:
        """
        Format lab test data
        """
        formatted = []
        for test in tests:
            formatted.append({
                'id': test.get('id'),
                'name': test.get('name'),
                'category': test.get('category'),
                'price': test.get('price', 0),
                'discount_price': test.get('discounted_price'),
                'description': test.get('description', ''),
                'preparation_instructions': test.get('preparation', ''),
                'sample_type': test.get('sample_type'),
                'reporting_time': test.get('report_time', ''),
                'home_collection': test.get('home_collection', False),
                'fasting_required': test.get('fasting', False),
                'lab_partners': test.get('labs', []),
                'source': 'practo'
            })
        return formatted


# Combined healthcare services integration
class HealthcareServicesIntegrator:
    def __init__(self, lybrate_key: str = None, practo_key: str = None):
        self.lybrate = LybrateAPI(lybrate_key) if lybrate_key else None
        self.practo = PractoAPI(practo_key) if practo_key else None
    
    def unified_doctor_search(self, specialty: str, location: str, 
                            filters: Dict = {}) -> List[Dict]:
        """
        Search doctors across multiple platforms
        """
        all_doctors = []
        
        # Search Lybrate
        if self.lybrate:
            try:
                lybrate_doctors = self.lybrate.search_doctors(
                    specialty=specialty,
                    location=location,
                    experience_years=filters.get('min_experience', 0),
                    rating_min=filters.get('min_rating', 0.0)
                )
                all_doctors.extend(lybrate_doctors)
            except Exception as e:
                logging.error(f"Lybrate search failed: {e}")
        
        # Search Practo
        if self.practo:
            try:
                practo_doctors = self.practo.search_doctors(
                    specialty=specialty,
                    city=location,
                    consultation_type=filters.get('consultation_type', 'online')
                )
                all_doctors.extend(practo_doctors)
            except Exception as e:
                logging.error(f"Practo search failed: {e}")
        
        # Remove duplicates and sort by rating
        unique_doctors = {}
        for doc in all_doctors:
            key = f"{doc['name'].lower()}_{doc['specialty'].lower()}"
            if key not in unique_doctors or doc['rating'] > unique_doctors[key]['rating']:
                unique_doctors[key] = doc
        
        result = list(unique_doctors.values())
        result.sort(key=lambda x: (x.get('rating', 0), x.get('total_reviews', 0)), reverse=True)
        
        return result[:25]  # Return top 25 results
    
    def unified_hospital_search(self, latitude: float, longitude: float, 
                               specialty: str = "", radius_km: float = 10.0) -> List[Dict]:
        """
        Search hospitals/clinics across platforms
        """
        all_providers = []
        location_str = f"{latitude},{longitude}"
        
        # Search Practo
        if self.practo:
            try:
                practo_providers = self.practo.search_clinics_hospitals(
                    location=location_str,
                    specialty=specialty,
                    radius_km=radius_km
                )
                all_providers.extend(practo_providers)
            except Exception as e:
                logging.error(f"Practo hospital search failed: {e}")
        
        # Sort by rating and distance
        all_providers.sort(key=lambda x: (x.get('rating', 0), -x.get('distance_km', 999)), reverse=True)
        
        return all_providers