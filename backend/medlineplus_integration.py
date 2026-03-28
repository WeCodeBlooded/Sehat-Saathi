"""
MedlinePlus Integration Module for Sehat-Saathi
Provides medical information from NIH's MedlinePlus database
"""

import requests
import xml.etree.ElementTree as ET
import json
import logging
import time
from typing import List, Dict, Optional
from functools import lru_cache
import re

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MedlinePlusAPI:
    """
    Interface to MedlinePlus Health Topics Web Service
    Documentation: https://medlineplus.gov/webservices.html
    """
    
    BASE_URL = "https://wsearch.nlm.nih.gov/ws/query"
    GENETICS_BASE_URL = "https://medlineplus.gov/download/genetics/condition"
    
    def __init__(self, tool_name="SehatSaathi", email="support@sehatsaathi.ai"):
        self.tool_name = tool_name
        self.email = email
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': f'{tool_name}/1.0 (Healthcare Chatbot; {email})'
        })
        
        # Rate limiting - MedlinePlus allows reasonable usage
        self.last_request_time = 0
        self.min_request_interval = 0.5  # 500ms between requests
    
    def _rate_limit(self):
        """Implement basic rate limiting"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.min_request_interval:
            time.sleep(self.min_request_interval - time_since_last)
        self.last_request_time = time.time()
    
    def search_health_topics(self, term: str, max_results: int = 5) -> List[Dict]:
        """
        Search MedlinePlus Health Topics for a given term
        
        Args:
            term: Search term (condition, symptom, etc.)
            max_results: Maximum number of results to return
            
        Returns:
            List of health topic dictionaries with title, url, summary
        """
        self._rate_limit()
        
        params = {
            "db": "healthTopics",
            "term": term,
            "retmax": max_results,
            "tool": self.tool_name,
            "email": self.email
        }
        
        try:
            logger.info(f"Searching MedlinePlus for: {term}")
            response = self.session.get(self.BASE_URL, params=params, timeout=10)
            response.raise_for_status()
            logger.info(f"MedlinePlus raw XML response: {response.text[:1000]}")
            
            topics = self._parse_health_topics_xml(response.text)
            logger.info(f"MedlinePlus parsed topics: {json.dumps(topics, indent=2)[:1000]}")
            return topics
            
        except requests.RequestException as e:
            logger.error(f"MedlinePlus API request failed: {e}")
            return []
        except Exception as e:
            logger.error(f"Error parsing MedlinePlus response: {e}")
            return []
    
    def _parse_health_topics_xml(self, xml_content: str) -> List[Dict]:
        """Parse XML response from MedlinePlus Health Topics API"""
        try:
            root = ET.fromstring(xml_content)
            topics = []
            
            for doc in root.findall(".//document"):
                # Extract all content fields
                title = self._get_content_field(doc, 'title')
                url_link = self._get_content_field(doc, 'url')
                full_summary = self._get_content_field(doc, 'FullSummary')
                summary = self._get_content_field(doc, 'summary')
                organization = self._get_content_field(doc, 'organizationName')
                
                if title:  # Only include if we have at least a title
                    topic = {
                        "title": title,
                        "url": url_link or "",
                        "summary": full_summary or summary or "",
                        "organization": organization or "MedlinePlus",
                        "source": "MedlinePlus Health Topics"
                    }
                    topics.append(topic)
            
            logger.info(f"Found {len(topics)} health topics")
            return topics
            
        except ET.ParseError as e:
            logger.error(f"XML parsing error: {e}")
            return []
    
    def _get_content_field(self, doc_element, field_name: str) -> Optional[str]:
        """Extract a specific content field from document element"""
        content = doc_element.find(f".//content[@name='{field_name}']")
        return content.text.strip() if content is not None and content.text else None
    
    @lru_cache(maxsize=100)
    def get_genetic_condition_info(self, condition_slug: str) -> Optional[Dict]:
        """
        Get detailed genetic condition information
        
        Args:
            condition_slug: URL-friendly condition name (e.g., 'alzheimer-disease')
            
        Returns:
            Dictionary with genetic condition details or None
        """
        self._rate_limit()
        
        url = f"{self.GENETICS_BASE_URL}/{condition_slug}.json"
        
        try:
            logger.info(f"Fetching genetic info for: {condition_slug}")
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Extract key information
            return {
                "title": data.get("title", ""),
                "summary": data.get("summary", ""),
                "description": data.get("description", ""),
                "frequency": data.get("frequency", ""),
                "causes": data.get("causes", ""),
                "inheritance": data.get("inheritance", ""),
                "url": url.replace('.json', '.html'),
                "source": "MedlinePlus Genetics"
            }
            
        except requests.RequestException as e:
            logger.warning(f"Could not fetch genetic info for {condition_slug}: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON for genetic condition {condition_slug}: {e}")
            return None

class MedicalKnowledgeEnhancer:
    """
    Enhances chatbot responses with MedlinePlus medical knowledge
    """
    
    def __init__(self):
        self.medlineplus = MedlinePlusAPI()
        self.cache = {}  # Simple in-memory cache
        # very small stopword set for basic relevance scoring
        self._stop = set('a an and are as at be by for from has have in is it of on or that the to was were will with you your about into over under around through up down out off than then this those these their them they she he we i our ours mine yours his her its'.split())
        # minimal synonym expansion to guide MedlinePlus queries
        self._synonyms = [
            (re.compile(r"\b(rapid|fast|high)\s+heart\s+(rate|beat)s?\b", re.I), ["tachycardia", "palpitations", "arrhythmia"]),
            (re.compile(r"\bchest\s+pain\b", re.I), ["angina", "myocardial ischemia"]),
            (re.compile(r"\bshort(ness)?\s+of\s+breath\b|\bbreath(ing)?\s+difficult(y|ies)\b", re.I), ["dyspnea", "asthma", "copd"]),
            (re.compile(r"\bhigh\s+blood\s+pressure\b|\bhbp\b", re.I), ["hypertension"]),
        ]

    def _expand_query_terms(self, user_query: str) -> list:
        terms = []
        for pat, syns in self._synonyms:
            if pat.search(user_query or ''):
                terms.extend(syns)
        # de-duplicate while preserving order
        seen = set()
        out = []
        for t in terms:
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out

    def _tokens(self, text: str):
        if not text:
            return set()
        # alnum tokens, lowercase, remove very small stop set
        toks = re.findall(r"[a-zA-Z0-9']+", text.lower())
        return {t for t in toks if t not in self._stop and len(t) > 2}

    def _relevance_score(self, topic: Dict, focus_tokens: set) -> int:
        """Simple relevance score using token overlap. Title matches weigh more."""
        title = (topic.get('title') or '').lower()
        summary = (topic.get('summary') or '').lower()
        title_tokens = self._tokens(title)
        # consider only the first ~400 chars of summary for speed
        summary_tokens = self._tokens(summary[:400])
        title_overlap = len(title_tokens & focus_tokens)
        summary_overlap = len(summary_tokens & focus_tokens)
        score = 2 * title_overlap + 1 * summary_overlap
        return score
    
    def enhance_medical_response(self, user_query: str, detected_conditions: List[str]) -> Dict:
        """
        Enhance chatbot response with authoritative medical information
        
        Args:
            user_query: Original user query
            detected_conditions: List of medical conditions detected by the chatbot
            
        Returns:
            Dictionary with enhanced medical information
        """
        enhanced_info = {
            "medical_sources": [],
            "authoritative_summary": "",
            "additional_resources": [],
            "confidence_boost": False
        }

        # Prefer the user's query first, then synonyms, then detected conditions
        all_topics: List[Dict] = []
        syns = self._expand_query_terms(user_query)
        core_terms = [user_query] + syns[:2] + list(detected_conditions or [])[:1]
        focus_tokens = self._tokens(user_query) or self._tokens(' '.join(detected_conditions or []))

        for term in core_terms:
            if term in self.cache:
                topics = self.cache[term]
            else:
                topics = self.medlineplus.search_health_topics(term, max_results=2)
                self.cache[term] = topics

            # Attach relevance score to topics
            for t in topics:
                t['_score'] = self._relevance_score(t, focus_tokens)
            all_topics.extend(topics)

        # Remove duplicates based on title
        unique_topics: List[Dict] = []
        seen_titles = set()
        for topic in all_topics:
            if topic["title"] not in seen_titles:
                unique_topics.append(topic)
                seen_titles.add(topic["title"])

        # Filter out clearly off-topic items using minimal overlap with the user query
        filtered = [t for t in unique_topics if t.get('_score', 0) >= 1]
        if not filtered and unique_topics:
            # Fallback: keep items whose title contains any focus token
            filtered = [t for t in unique_topics if any(ft in (t.get('title','').lower()) for ft in focus_tokens)] or unique_topics[:2]

        # Sort primarily by score, secondarily by summary length
        filtered.sort(key=lambda x: (x.get('_score', 0), len(x.get('summary', ''))), reverse=True)

        if filtered:
            enhanced_info["medical_sources"] = [{k:v for k,v in t.items() if not k.startswith('_')} for t in filtered[:3]]

            # Create authoritative summary
            best_topic = filtered[0]
            summary = best_topic.get("summary", "")
            if summary:
                # Clean and truncate summary
                clean_summary = self._clean_medical_text(summary)
                enhanced_info["authoritative_summary"] = clean_summary[:500] + "..." if len(clean_summary) > 500 else clean_summary
                enhanced_info["confidence_boost"] = True

            # Add URLs as additional resources
            enhanced_info["additional_resources"] = [
                {"title": t["title"], "url": t["url"]}
                for t in filtered[:3]
                if t.get("url")
            ]

        return enhanced_info
    
    def _clean_medical_text(self, text: str) -> str:
        """Clean and format medical text for display"""
        if not text:
            return ""
        
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text.strip())
        
        # Remove HTML tags if present
        text = re.sub(r'<[^>]+>', '', text)
        
        # Ensure proper sentence endings
        if text and not text.endswith(('.', '!', '?')):
            text += '.'
        
        return text
    
    def search_medical_info(self, query: str, max_results: int = 3) -> List[Dict]:
        """
        Direct search for medical information
        
        Args:
            query: Search query
            max_results: Maximum number of results
            
        Returns:
            List of medical information dictionaries
        """
        topics = self.medlineplus.search_health_topics(query, max_results=max_results)
        focus_tokens = self._tokens(query)
        for t in topics:
            t['_score'] = self._relevance_score(t, focus_tokens)
        topics.sort(key=lambda x: (x.get('_score', 0), len(x.get('summary',''))), reverse=True)
        filtered = [t for t in topics if t.get('_score', 0) >= 1]
        if not filtered:
            # Try synonyms once if no relevant hits from the raw query
            syns = self._expand_query_terms(query)
            for term in syns[:2]:
                extra = self.medlineplus.search_health_topics(term, max_results=2)
                for e in extra:
                    e['_score'] = self._relevance_score(e, focus_tokens)
                filtered.extend(extra)
            if filtered:
                filtered.sort(key=lambda x: (x.get('_score', 0), len(x.get('summary',''))), reverse=True)
        # Strip helper field before returning
        return [{k:v for k,v in t.items() if not k.startswith('_')} for t in (filtered or topics)[:max_results]]

# Global instance for use in main app
medical_enhancer = MedicalKnowledgeEnhancer()

def get_medical_info(query: str, max_results: int = 3) -> List[Dict]:
    """
    Convenience function to get medical information
    """
    return medical_enhancer.search_medical_info(query, max_results=max_results)

def enhance_chatbot_response(user_query: str, detected_conditions: List[str]) -> Dict:
    """
    Convenience function to enhance chatbot response
    """
    return medical_enhancer.enhance_medical_response(user_query, detected_conditions)

# Test function
def test_medlineplus_integration():
    """Test the MedlinePlus integration"""
    print("Testing MedlinePlus Integration...")
    
    # Test basic search
    results = get_medical_info("asthma")
    print(f"\nFound {len(results)} results for 'asthma':")
    for i, result in enumerate(results[:2]):
        print(f"{i+1}. {result['title']}")
        print(f"   Summary: {result['summary'][:100]}...")
    
    # Test enhancement
    enhancement = enhance_chatbot_response("I have trouble breathing", ["asthma", "breathing difficulty"])
    print(f"\nEnhancement confidence boost: {enhancement['confidence_boost']}")
    if enhancement['authoritative_summary']:
        print(f"Authoritative summary: {enhancement['authoritative_summary'][:100]}...")

if __name__ == "__main__":
    test_medlineplus_integration()