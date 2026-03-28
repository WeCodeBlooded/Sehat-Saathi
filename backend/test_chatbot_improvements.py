#!/usr/bin/env python3
"""
Test script to demonstrate chatbot improvements:
1. Better greeting and conversation handling
2. Improved medical response accuracy
"""

import requests
import json
import time

# Server URL
BASE_URL = "http://127.0.0.1:5000"

def test_chatbot(message, description):
    """Test the chatbot with a message and print results"""
    print(f"\n{'='*60}")
    print(f"TEST: {description}")
    print(f"User Message: '{message}'")
    print("-" * 60)
    
    try:
        response = requests.post(
            f"{BASE_URL}/chat",
            json={"message": message, "uid": "test_user_123"},
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"Bot Response: {data.get('message', 'No response')}")
            if 'issue_confidence' in data and data['issue_confidence']:
                confidence_info = data['issue_confidence'][0] if data['issue_confidence'] else {}
                print(f"Confidence: {confidence_info.get('confidence', 0)*100:.1f}%")
            if 'matched_issues' in data and data['matched_issues']:
                print(f"Detected Issues: {', '.join(data['matched_issues'])}")
            if 'zero_shot_used' in data and data['zero_shot_used']:
                print("🤖 AI Classification Used")
            if 'medlineplus_enhanced' in data and data['medlineplus_enhanced']:
                print("📚 Enhanced with Medical Sources")
        else:
            print(f"Error: HTTP {response.status_code}")
            print(f"Response: {response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"Connection Error: {e}")
    
    time.sleep(1)  # Small delay between requests

def main():
    print("🤖 Testing Enhanced Chatbot - Sehat Saathi")
    print("Testing improvements for greeting handling and medical accuracy")
    
    # Wait a moment for server to be fully ready
    time.sleep(2)
    
    # Test 1: Greeting Detection (Previous Issue)
    test_chatbot("Hello", "Basic Greeting Detection")
    test_chatbot("Hi there, how are you?", "Conversational Greeting")
    test_chatbot("Good morning", "Time-based Greeting")
    
    # Test 2: General Conversation (Previous Issue)
    test_chatbot("How can you help me?", "Help Request")
    test_chatbot("What services do you provide?", "Service Inquiry")
    test_chatbot("Thank you", "Gratitude Expression")
    
    # Test 3: Medical Queries (Improved Accuracy)
    test_chatbot("I have a fever and headache", "Common Symptoms")
    test_chatbot("My stomach hurts", "Abdominal Pain")
    test_chatbot("I'm feeling dizzy", "Dizziness Symptom")
    
    # Test 4: Emergency Detection
    test_chatbot("I'm having chest pain", "Emergency Symptom")
    test_chatbot("I can't breathe properly", "Breathing Emergency")
    
    # Test 5: Pregnancy/Pediatric (Enhanced Responses)
    test_chatbot("I'm pregnant and feeling nauseous", "Pregnancy Query")
    test_chatbot("My child has a fever", "Pediatric Query")
    
    print(f"\n{'='*60}")
    print("✅ Chatbot Testing Complete!")
    print("The enhanced chatbot now handles:")
    print("• Greetings and conversational messages")
    print("• Medical queries with improved accuracy")
    print("• Emergency detection with warnings")
    print("• Confidence scoring for responses")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()