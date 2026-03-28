"""
Lybrate API Integration for Doctor Discovery and Consultation
Provides access to verified doctors, their profiles, and availability
"""

import requests
import json
from typing import Dict, List, Optional
import logging
from datetime import datetime, timedelta

class LybrateAPI:
    def __init__(self, api_key: str, base_url: str = "https://api.lybrate.com/v1"):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
    
    def search_doctors(self, specialty: str, location: str = "", experience_years: int = 0, 
                      rating_min: float = 0.0, limit: int = 10) -> List[Dict]:
        """
        Search for doctors by specialty and location
        """
        try:
            params = {
                'specialty': specialty,
                'location': location,
                'min_experience': experience_years,
                'min_rating': rating_min,
                'limit': limit,
                'availability': 'online'  # Focus on teleconsultation
            }
            
            response = requests.get(
                f"{self.base_url}/doctors/search",
                headers=self.headers,
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return self._format_doctor_profiles(data.get('doctors', []))
            else:
                logging.error(f"Lybrate API error: {response.status_code}")
                return []
                
        except Exception as e:
            logging.error(f"Error searching Lybrate doctors: {e}")
            return []
    
    def get_doctor_availability(self, doctor_id: str, date_range_days: int = 7) -> Dict:
        """
        Get doctor's available time slots for teleconsultation
        """
        try:
            end_date = datetime.now() + timedelta(days=date_range_days)
            params = {
                'doctor_id': doctor_id,
                'start_date': datetime.now().isoformat(),
                'end_date': end_date.isoformat(),
                'consultation_type': 'video'
            }
            
            response = requests.get(
                f"{self.base_url}/doctors/{doctor_id}/availability",
                headers=self.headers,
                params=params,
                timeout=20
            )
            
            if response.status_code == 200:
                return response.json()
            return {'available_slots': []}
            
        except Exception as e:
            logging.error(f"Error getting doctor availability: {e}")
            return {'available_slots': []}
    
    def book_consultation(self, doctor_id: str, patient_info: Dict, 
                         slot_time: str, consultation_type: str = "video") -> Dict:
        """
        Book a teleconsultation appointment
        """
        try:
            booking_data = {
                'doctor_id': doctor_id,
                'patient_info': patient_info,
                'appointment_time': slot_time,
                'consultation_type': consultation_type,
                'symptoms': patient_info.get('symptoms', ''),
                'medical_history': patient_info.get('medical_history', '')
            }
            
            response = requests.post(
                f"{self.base_url}/consultations/book",
                headers=self.headers,
                json=booking_data,
                timeout=30
            )
            
            if response.status_code == 201:
                return {
                    'success': True,
                    'booking_id': response.json().get('booking_id'),
                    'meeting_link': response.json().get('meeting_url'),
                    'booking_details': response.json()
                }
            else:
                return {
                    'success': False,
                    'error': f"Booking failed: {response.status_code}"
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f"Booking error: {str(e)}"
            }
    
    def get_consultation_history(self, patient_id: str) -> List[Dict]:
        """
        Retrieve patient's consultation history
        """
        try:
            response = requests.get(
                f"{self.base_url}/patients/{patient_id}/consultations",
                headers=self.headers,
                timeout=20
            )
            
            if response.status_code == 200:
                return response.json().get('consultations', [])
            return []
            
        except Exception as e:
            logging.error(f"Error getting consultation history: {e}")
            return []
    
    def _format_doctor_profiles(self, doctors: List[Dict]) -> List[Dict]:
        """
        Format doctor data for Sehat-Saathi integration
        """
        formatted = []
        for doc in doctors:
            formatted.append({
                'id': doc.get('doctor_id'),
                'name': doc.get('full_name'),
                'specialty': doc.get('specialization'),
                'experience_years': doc.get('experience_years', 0),
                'rating': doc.get('rating', 0.0),
                'consultation_fee': doc.get('consultation_fee', 0),
                'languages': doc.get('languages_spoken', []),
                'profile_image': doc.get('profile_photo_url'),
                'qualifications': doc.get('degrees', []),
                'hospital_affiliations': doc.get('hospitals', []),
                'available_for_video': doc.get('video_consultation', False),
                'available_for_chat': doc.get('chat_consultation', False),
                'next_available': doc.get('next_available_slot'),
                'bio': doc.get('bio_summary', ''),
                'source': 'lybrate'
            })
        return formatted

# Enhanced doctor directory integration
class EnhancedDoctorDirectory:
    def __init__(self, lybrate_api_key: str):
        self.lybrate = LybrateAPI(lybrate_api_key) if lybrate_api_key else None
        
    def search_comprehensive_doctors(self, specialty: str, location: str = "", 
                                   user_preferences: Dict = {}) -> List[Dict]:
        """
        Search doctors from multiple sources including Lybrate
        """
        all_doctors = []
        
        # Get doctors from Lybrate
        if self.lybrate:
            lybrate_docs = self.lybrate.search_doctors(
                specialty=specialty,
                location=location,
                experience_years=user_preferences.get('min_experience', 0),
                rating_min=user_preferences.get('min_rating', 0.0)
            )
            all_doctors.extend(lybrate_docs)
        
        # Sort by rating and availability
        all_doctors.sort(key=lambda x: (x.get('rating', 0), x.get('available_for_video', False)), reverse=True)
        
        return all_doctors[:20]  # Return top 20 results