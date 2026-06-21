import math
from typing import Dict, Any

def calculate_viral_propagation_risk(veracity_data: Dict[str, Any]) -> float:
    """
    Simulates an Awareness Spread Model (ASM) based on epidemiological principles (SIR).
    Calculates a "Viral Propagation Risk" score (0.0 to 100.0) representing the
    likely velocity and spread of the misinformation.
    
    Factors considered:
    1. Overall Risk (from the Multi-Agent system) - acts as the baseline infectivity.
    2. Domain Credibility - lower credibility often leads to higher emotional sharing.
    3. Confidence - highly confident lies spread faster.
    """
    overall_risk = float(veracity_data.get("overall_risk", 50.0))
    confidence = float(veracity_data.get("confidence", 50.0))
    metrics = veracity_data.get("metrics", {})
    
    # Extract domain credibility (default 0.5)
    domain_cred = float(metrics.get("domain_credibility", 0.5))
    
    # Higher overall risk means it's likely more sensational or contradictory
    base_infectivity = overall_risk / 100.0
    
    # Highly confident falsehoods are shared more rapidly
    confidence_multiplier = 1.0 + (confidence / 100.0) * 0.5 
    
    # Suspicious domains (low credibility) often employ clickbait, increasing spread
    # We map domain cred (0-1) to a spread multiplier (e.g., 0.1 cred -> 1.45 multiplier)
    domain_multiplier = 1.0 + (1.0 - domain_cred) * 0.5
    
    # Calculate the basic reproduction number (R0) equivalent
    # Using a simple logarithmic curve to ensure it maxes out at 100
    viral_potential = base_infectivity * confidence_multiplier * domain_multiplier
    
    # Scale back to 0-100 range
    viral_risk_score = min(max(viral_potential * 100.0, 0.0), 100.0)
    
    # Round to 1 decimal place
    return round(viral_risk_score, 1)
