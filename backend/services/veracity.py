import math

from backend.config import W_BIAS, W_DOMAIN, W_EVIDENCE
from backend.database import get_db_connection
from backend.services.ingestion import extract_domain

# Lists of domain credibility ratings
TRUSTED_DOMAINS = {
    "reuters.com": 1.0,
    "bbc.com": 1.0,
    "bbc.co.uk": 1.0,
    "apnews.com": 1.0,
    "nytimes.com": 0.95,
    "washingtonpost.com": 0.95,
    "factcheck.org": 1.0,
    "politifact.com": 1.0,
    "snopes.com": 1.0,
    "cdc.gov": 1.0,
    "who.int": 1.0,
    "nih.gov": 1.0,
    "fda.gov": 1.0,
    "nature.com": 1.0,
    "science.org": 1.0
}

DUBIOUS_DOMAINS = {
    "naturalnews.com": 0.1,
    "infowars.com": 0.0,
    "breitbart.com": 0.2,
    "thegatewaypundit.com": 0.1,
    "dailymail.co.uk": 0.5, # tabloid, medium risk
    "buzzfeed.com": 0.6,
    "rt.com": 0.3,
    "sputniknews.com": 0.2,
    "worldnewsdailyreport.com": 0.0, # satire/fake news
    "now8news.com": 0.0,
    "beforeitsnews.com": 0.1
}

SENSATIONAL_WORDS = {
    "shocking", "miracle", "secret", "conspiracy", "exposed", "must read",
    "hidden truth", "unbelievable", "disaster", "danger", "alert", "cured",
    "hoax", "agenda", "hiding", "proven", "100%", "guaranteed", "plot"
}

def analyze_linguistic_bias(text: str) -> float:
    """
    Computes a linguistic bias/sensationalism score between 0.0 (neutral) and 1.0 (highly sensational).
    Looks at:
    - Proportion of words in ALL CAPS (excluding short words like I, A).
    - Presence and count of exclamation marks/question marks.
    - Matches with a database of known clickbait/sensationalist words.
    """
    if not text:
        return 0.0
        
    text_lower = text.lower()
    words = text.split()
    if not words:
        return 0.0
        
    # 1. Caps Ratio
    capitalized_words = [w for w in words if w.isupper() and len(w) > 1]
    caps_ratio = len(capitalized_words) / len(words)
    
    # 2. Exclamation ratio
    excl_count = text.count("!")
    q_count = text.count("?")
    punc_score = min((excl_count * 0.2) + (q_count * 0.1), 0.5)
    
    # 3. Sensational word match
    matched_words = sum(1 for w in SENSATIONAL_WORDS if w in text_lower)
    word_score = min(matched_words * 0.15, 0.5)
    
    # Combine (caps up to 0.3, punctuation up to 0.3, words up to 0.4)
    bias_score = min((caps_ratio * 3.0) * 0.3 + punc_score * 0.6 + word_score * 0.8, 1.0)
    
    return float(bias_score)

def get_domain_credibility(url_or_domain: str) -> float:
    """Returns a credibility score between 0.0 and 1.0 for a given URL or domain name."""
    if not url_or_domain:
        return 0.5 # Neutral fallback for text-only inputs with no source URL
        
    domain = url_or_domain
    if "/" in domain or "http" in domain:
        domain = extract_domain(url_or_domain)
        
    domain = domain.lower()
    
    # Check direct match
    if domain in TRUSTED_DOMAINS:
        return TRUSTED_DOMAINS[domain]
    if domain in DUBIOUS_DOMAINS:
        return DUBIOUS_DOMAINS[domain]
        
    # Check parent domain match (e.g. support.apple.com -> apple.com)
    parts = domain.split(".")
    if len(parts) > 2:
        parent_domain = ".".join(parts[-2:])
        if parent_domain in TRUSTED_DOMAINS:
            return TRUSTED_DOMAINS[parent_domain]
        if parent_domain in DUBIOUS_DOMAINS:
            return DUBIOUS_DOMAINS[parent_domain]
            
    # Default score for unknown domains
    return 0.5

def calculate_evidence_stance(evidence_list: list) -> float:
    """
    Computes a stance score between 0.0 (all articles support/verify the claim)
    and 1.0 (all articles refute/debunk the claim).
    """
    if not evidence_list:
        return 0.5 # Neutral fallback when no evidence is found
        
    refute_count = 0
    support_count = 0
    neutral_count = 0
    
    refute_keywords = {"false", "debunked", "myth", "misleading", "fake", "incorrect", "unproven", "dangerous"}
    support_keywords = {"true", "correct", "verified", "accurate", "confirmed"}
    
    for article in evidence_list:
        rating_text = article.get("rating", "").lower()
        snippet_text = article.get("snippet", "").lower()
        title_text = article.get("title", "").lower()
        
        # Determine if it's refuting or supporting
        is_refuting = False
        is_supporting = False
        
        # Check rating text first
        if any(kw in rating_text for kw in refute_keywords):
            is_refuting = True
        elif any(kw in rating_text for kw in support_keywords):
            is_supporting = True
            
        # Check snippet/title if rating is inconclusive
        if not is_refuting and not is_supporting:
            if "debunk" in title_text or "debunk" in snippet_text or "false claim" in snippet_text:
                is_refuting = True
            elif "confirm" in title_text or "verif" in title_text:
                is_supporting = True
                
        if is_refuting:
            refute_count += 1
        elif is_supporting:
            support_count += 1
        else:
            neutral_count += 1
            
    total = refute_count + support_count + (neutral_count * 0.5)
    if total == 0:
        return 0.5
        
    # High score means it contradicts/refutes the claim (higher risk)
    stance_score = (refute_count + (neutral_count * 0.25)) / total
    return float(stance_score)

def get_feedback_adjusted_weights() -> dict:
    """Learn small, bounded weight changes from prior thumbs-up/down votes."""
    base = {
        "linguistic_bias": W_BIAS,
        "domain_risk": W_DOMAIN,
        "evidence_contradiction": W_EVIDENCE,
    }
    conn = get_db_connection()
    try:
        rows = conn.execute("""
            SELECT f.vote, p.linguistic_bias,
                   1.0 - p.domain_credibility AS domain_risk,
                   p.evidence_contradiction
            FROM feedback f JOIN posts p ON p.id = f.post_id
            WHERE p.linguistic_bias IS NOT NULL
              AND p.domain_credibility IS NOT NULL
              AND p.evidence_contradiction IS NOT NULL
        """).fetchall()
    finally:
        conn.close()

    if not rows:
        return base

    # Positive feedback reinforces the components that drove a confident result;
    # negative feedback gently attenuates them. Exponential scaling stays positive.
    adjusted = {}
    for name, weight in base.items():
        signal = sum(row["vote"] * abs(float(row[name]) - 0.5) for row in rows) / len(rows)
        adjusted[name] = weight * math.exp(0.35 * signal)

    total = sum(adjusted.values())
    return {name: value / total for name, value in adjusted.items()}


def calculate_veracity_score(
    text: str, source_url: str, evidence_list: list,
    domain_credibility: float | None = None,
    image_mismatch_score: float | None = None,
) -> dict:
    """
    Calculates the final overall risk score (0 to 100) and maps it to a verdict.
    Risk Score = w1 * Bias + w2 * (1 - DomainCredibility) + w3 * EvidenceStance
    """
    bias_score = analyze_linguistic_bias(text)
    
    domain_score = get_domain_credibility(source_url) if domain_credibility is None else domain_credibility
    domain_risk = 1.0 - domain_score
    
    stance_score = calculate_evidence_stance(evidence_list)
    
    # Calculate weighted risk (0.0 to 1.0)
    weights = get_feedback_adjusted_weights()
    risk_factor = (
        weights["linguistic_bias"] * bias_score
        + weights["domain_risk"] * domain_risk
        + weights["evidence_contradiction"] * stance_score
    )
    if image_mismatch_score is not None:
        # Visual context is a strong supplementary signal, but cannot overwhelm
        # source and evidence analysis on its own.
        risk_factor = (0.8 * risk_factor) + (0.2 * max(0.0, min(image_mismatch_score, 1.0)))
    overall_risk = float(risk_factor * 100)
    
    # Map overall risk to verdict
    if overall_risk >= 70:
        verdict = "Likely False"
    elif overall_risk >= 40:
        verdict = "Suspicious"
    else:
        # If there's high support count, it's Likely True, otherwise Uncertain
        support_count = sum(1 for e in evidence_list if "true" in e.get("rating", "").lower() or "verified" in e.get("rating", "").lower())
        if support_count > 0 and overall_risk < 30:
            verdict = "Likely True"
        else:
            verdict = "Uncertain"
            
    # Compute confidence score (0 to 100) based on how much evidence we found
    # and consistency of evidence
    evidence_weight = min(len(evidence_list) * 20, 60) # Up to 60 points for quantity
    
    # Consistency check
    ratings = [e.get("rating", "").lower() for e in evidence_list]
    false_ratings = sum(1 for r in ratings if any(kw in r for kw in ["false", "debunked", "myth", "misleading"]))
    true_ratings = sum(1 for r in ratings if any(kw in r for kw in ["true", "verified", "correct"]))
    
    consistency_bonus = 0
    if len(evidence_list) > 0:
        consensus_ratio = max(false_ratings, true_ratings) / len(evidence_list)
        consistency_bonus = consensus_ratio * 40 # Up to 40 points for alignment
        
    confidence = float(min(evidence_weight + consistency_bonus, 100))
    if len(evidence_list) == 0:
        confidence = 30.0 # Standard low confidence if zero search results found
        
    return {
        "overall_risk": round(overall_risk, 1),
        "verdict": verdict,
        "confidence": round(confidence, 1),
        "metrics": {
            "linguistic_bias": round(bias_score, 2),
            "domain_credibility": round(domain_score, 2),
            "evidence_contradiction": round(stance_score, 2),
            "visual_mismatch": round(image_mismatch_score, 2) if image_mismatch_score is not None else None,
        },
        "weights": {name: round(value, 3) for name, value in weights.items()}
    }
