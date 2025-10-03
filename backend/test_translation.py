#!/usr/bin/env python3
# Test script to check translation

try:
    from deep_translator import GoogleTranslator
    from langdetect import detect
    
    hindi_text = "मुझे बुखार है"
    print(f"Original Hindi text: {hindi_text}")
    
    # Detect language
    detected_lang = detect(hindi_text)
    print(f"Detected language: {detected_lang}")
    
    # Translate to English
    translator = GoogleTranslator(source=detected_lang, target='en')
    translated = translator.translate(hindi_text)
    print(f"Translated to English: {translated}")
    print(f"Lowercase: {translated.lower()}")
    
    # Check if fever-related keywords are in the translation
    fever_keywords = ["fever", "have fever", "have a fever", "feeling feverish", "temperature"]
    print("\n--- Checking for fever keywords ---")
    found_match = False
    for keyword in fever_keywords:
        if keyword in translated.lower():
            print(f"✅ Found keyword '{keyword}' in translation")
            found_match = True
        else:
            print(f"❌ Keyword '{keyword}' not found in translation")
    
    if found_match:
        # Test back translation
        response = "Drink plenty of fluids and rest. If it persists, see a doctor."
        print(f"\n--- Testing back translation ---")
        print(f"English response: {response}")
        
        back_translator = GoogleTranslator(source='en', target=detected_lang)
        hindi_response = back_translator.translate(response)
        print(f"Hindi response: {hindi_response}")
    
except Exception as e:
    print(f"Error: {e}")