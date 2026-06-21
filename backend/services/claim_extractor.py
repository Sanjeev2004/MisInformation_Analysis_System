import json
import re
from google import genai
from backend.config import GEMINI_API_KEY

def get_gemini_client():
    if not GEMINI_API_KEY:
        return None
    try:
        return genai.Client(api_key=GEMINI_API_KEY)
    except Exception:
        return None

def fallback_extract(text: str) -> dict:
    """Fallback parser if Gemini is unavailable or fails."""
    # Simple heuristic-based extraction
    sentences = [s.strip() for s in text.split('.') if s.strip()]
    claim = sentences[0] if sentences else text
    if len(claim) > 100:
        claim = claim[:97] + "..."
        
    # Naive entity extraction (capitalized words)
    words = re.findall(r'\b[A-Z][a-z]+\b', text)
    entities = list(set(words))[:5]
    
    return {
        "claim_text": claim,
        "entities": entities
    }



def extract_claim_and_entities(text: str) -> dict:
    """Uses Gemini API to extract a clean declarative claim and a list of entities."""
    if not text or not text.strip():
        return {"claim_text": "", "entities": []}
        
    client = get_gemini_client()
    if not client:
        return fallback_extract(text)
        
    prompt = (
        "Analyze the following text, which might be a news article snippet, WhatsApp message, or tweet. "
        "Extract the core underlying assertion or rumor into a single, clean, declarative claim sentence (10-15 words max). "
        "Also extract the key entities (people, products, organizations, topics, or viruses) mentioned.\n\n"
        "Text: \n"
        f"\"\"\"\n{text}\n\"\"\"\n\n"
        "Return ONLY a JSON object with two keys: 'claim_text' (string) and 'entities' (list of strings). "
        "Do not include any markdown backticks or explanation outside the JSON."
    )
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        
        response_text = response.text.strip()
        # Clean potential markdown JSON blocks
        if response_text.startswith("```"):
            response_text = re.sub(r"^```(?:json)?\n", "", response_text)
            response_text = re.sub(r"\n```$", "", response_text)
            
        data = json.loads(response_text.strip())
        if "claim_text" in data and "entities" in data:
            return {
                "claim_text": data["claim_text"],
                "entities": data["entities"]
            }
    except Exception as e:
        print(f"Error during claim extraction via Gemini: {e}")
        
    return fallback_extract(text)
