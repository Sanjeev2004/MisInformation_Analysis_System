import json
import re
from google import genai
from backend.config import GEMINI_API_KEY
from backend.services.claim_extractor import get_gemini_client
from backend.services.veracity import SENSATIONAL_WORDS

def fallback_explain(text: str, verdict: str, metrics: dict) -> dict:
    """Fallback explainer when Gemini API is unavailable."""
    text_lower = text.lower()
    highlights = []
    
    # Highlight sensational words
    for word in SENSATIONAL_WORDS:
        # Match word boundaries
        matches = re.finditer(rf"\b{re.escape(word)}\w*\b", text_lower)
        for m in matches:
            phrase = text[m.start():m.end()]
            highlights.append({
                "phrase": phrase,
                "category": "sensational"
            })
            
    # Highlight uppercase words as "sensational" if they are part of ALL CAPS words
    for word in text.split():
        if word.isupper() and len(word) > 3 and word.lower() not in SENSATIONAL_WORDS:
            highlights.append({
                "phrase": word,
                "category": "sensational"
            })
            
    # Deduplicate highlights
    unique_highlights = []
    seen = set()
    for h in highlights:
        if h["phrase"].lower() not in seen:
            seen.add(h["phrase"].lower())
            unique_highlights.append(h)
            
    # Simple rule-based explanation narrative
    bias = metrics.get("linguistic_bias", 0.0)
    domain = metrics.get("domain_credibility", 0.5)
    evidence = metrics.get("evidence_contradiction", 0.5)
    
    reasons = []
    if bias > 0.5:
        reasons.append("sensationalist or emotional language")
    if domain < 0.4:
        reasons.append("a source domain with a low reputation")
    if evidence > 0.6:
        reasons.append("contradictions found in reputable fact-checking databases")
        
    reason_str = " + ".join(reasons) if reasons else "insufficient supporting articles and verified coverage"
    explanation = f"Verdict: {verdict}. Reason: The content shows signs of {reason_str}."
    
    return {
        "explanation": explanation,
        "highlights": unique_highlights[:5]
    }

def generate_explanation_and_highlights(text: str, verdict: str, metrics: dict, evidence_list: list) -> dict:
    """
    Calls Gemini to generate a human-readable 2-3 sentence explanation of the risk verdict
    and extract exact substrings (phrases) to highlight as sensational, logical fallacies, or unverified claims.
    """
    if not text or not text.strip():
        return {"explanation": "", "highlights": []}
        
    client = get_gemini_client()
    if not client:
        return fallback_explain(text, verdict, metrics)
        
    evidence_summary = ""
    if evidence_list:
        ev_strings = []
        for i, ev in enumerate(evidence_list[:3]):
            ev_strings.append(f"- Source: {ev['source']} ({ev['url']}) says: {ev['title']} (Rating: {ev.get('rating', 'N/A')})")
        evidence_summary = "External Evidence found:\n" + "\n".join(ev_strings)
        
    prompt = (
        "You are an expert fact-checking and explainable AI assistant.\n"
        "Analyze the text and explain why the system classified it as having this risk profile.\n\n"
        f"Text to evaluate:\n\"\"\"\n{text}\n\"\"\"\n\n"
        f"System Verdict: {verdict}\n"
        f"Linguistic Bias/Sensationalism (0-1): {metrics.get('linguistic_bias', 0)}\n"
        f"Source Domain Credibility (0-1): {metrics.get('domain_credibility', 0.5)}\n"
        f"Evidence Contradiction (0-1): {metrics.get('evidence_contradiction', 0.5)}\n"
        f"{evidence_summary}\n\n"
        "Provide a JSON response with two keys:\n"
        "1. 'explanation': A 2-3 sentence clear, objective explanation of the verdict (referencing source credibility, language style, and consensus among fact-checkers if applicable).\n"
        "2. 'highlights': A list of objects. Each object represents a exact substring (phrase) from the original text that should be highlighted. Each object must have:\n"
        "   - 'phrase': The EXACT case-sensitive substring from the input text.\n"
        "   - 'category': One of: 'sensational' (sensationalism/clickbait/emotional cue), 'fallacy' (logical fallacy/unsupported claim), 'unverified' (highly specific claim lacking evidence).\n\n"
        "Respond ONLY with a valid JSON block. Do not include markdown backticks or any other text."
    )
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        
        response_text = response.text.strip()
        if response_text.startswith("```"):
            response_text = re.sub(r"^```(?:json)?\n", "", response_text)
            response_text = re.sub(r"\n```$", "", response_text)
            
        data = json.loads(response_text.strip())
        
        # Verify highlights exist in text
        valid_highlights = []
        for h in data.get("highlights", []):
            phrase = h.get("phrase", "")
            category = h.get("category", "")
            if phrase and phrase in text and category in ["sensational", "fallacy", "unverified"]:
                valid_highlights.append({
                    "phrase": phrase,
                    "category": category
                })
                
        return {
            "explanation": data.get("explanation", ""),
            "highlights": valid_highlights
        }
    except Exception as e:
        print(f"Error during explanation generation via Gemini: {e}")
        
    return fallback_explain(text, verdict, metrics)
