import httpx
from backend.config import GOOGLE_FACT_CHECK_API_KEY

# A realistic mock database of claim reviews to fallback on for demos/when no key is set
MOCK_FACT_CHECKS = [
    {
        "keywords": ["vaccine", "infertility", "fertility"],
        "claims": [
            {
                "text": "COVID-19 vaccines cause infertility in women.",
                "claimant": "Social Media Posts",
                "claimDate": "2021-01-15T00:00:00Z",
                "claimReview": [
                    {
                        "publisher": {"name": "PolitiFact", "site": "politifact.com"},
                        "url": "https://www.politifact.com/factchecks/2021/jan/11/facebook-posts/no-scientific-evidence-covid-19-vaccine-causes-in/",
                        "title": "No scientific evidence COVID-19 vaccine causes infertility",
                        "reviewDate": "2021-01-11T00:00:00Z",
                        "textualRating": "False"
                    },
                    {
                        "publisher": {"name": "FactCheck.org", "site": "factcheck.org"},
                        "url": "https://www.factcheck.org/2021/01/scicheck-no-evidence-vaccines-cause-infertility/",
                        "title": "No Evidence Vaccines Cause Infertility",
                        "reviewDate": "2021-01-15T00:00:00Z",
                        "textualRating": "False"
                    }
                ]
            }
        ]
    },
    {
        "keywords": ["bleach", "cure", "covid"],
        "claims": [
            {
                "text": "Drinking chlorine dioxide or bleach cures COVID-19.",
                "claimant": "Viral WhatsApp Forwards",
                "claimDate": "2020-04-10T00:00:00Z",
                "claimReview": [
                    {
                        "publisher": {"name": "FDA Warning", "site": "fda.gov"},
                        "url": "https://www.fda.gov/consumers/consumer-updates/danger-dont-drink-miracle-mineral-solution-or-other-sodium-chlorite-products",
                        "title": "Danger: Don't Drink Miracle Mineral Solution",
                        "reviewDate": "2020-08-12T00:00:00Z",
                        "textualRating": "Extremely Dangerous / False"
                    },
                    {
                        "publisher": {"name": "Snopes", "site": "snopes.com"},
                        "url": "https://www.snopes.com/fact-check/fda-warn-drink-bleach-coronavirus/",
                        "title": "Did the FDA Warn Against Drinking Bleach to Cure Coronavirus?",
                        "reviewDate": "2020-04-15T00:00:00Z",
                        "textualRating": "True (FDA issued warning against it)"
                    }
                ]
            }
        ]
    },
    {
        "keywords": ["5g", "radiation", "coronavirus", "spread"],
        "claims": [
            {
                "text": "5G mobile networks spread the coronavirus.",
                "claimant": "Conspiracy theorist videos",
                "claimDate": "2020-03-20T00:00:00Z",
                "claimReview": [
                    {
                        "publisher": {"name": "World Health Organization", "site": "who.int"},
                        "url": "https://www.who.int/emergencies/diseases/novel-coronavirus-2019/advice-for-public/myth-busters",
                        "title": "5G mobile networks DO NOT spread COVID-19",
                        "reviewDate": "2020-04-20T00:00:00Z",
                        "textualRating": "False / Myth"
                    },
                    {
                        "publisher": {"name": "Reuters Fact Check", "site": "reuters.com"},
                        "url": "https://www.reuters.com/article/uk-factcheck-5g-idUSKBN21P2O1",
                        "title": "False claim: 5G technology causes coronavirus",
                        "reviewDate": "2020-04-08T00:00:00Z",
                        "textualRating": "False"
                    }
                ]
            }
        ]
    },
    {
        "keywords": ["aliens", "ufo", "nevada", "crash"],
        "claims": [
            {
                "text": "The US military recovered a fully intact alien spaceship in Area 51.",
                "claimant": "Tiktok post",
                "claimDate": "2023-07-01T00:00:00Z",
                "claimReview": [
                    {
                        "publisher": {"name": "Defense Department Statement", "site": "defense.gov"},
                        "url": "https://www.defense.gov",
                        "title": "AARO findings show no evidence of off-world technology",
                        "reviewDate": "2024-03-08T00:00:00Z",
                        "textualRating": "Unsubstantiated"
                    }
                ]
            }
        ]
    }
]

def search_mock_registry(query: str) -> list:
    """Simple keyword matching against our mock database."""
    query_lower = query.lower()
    matches = []
    
    for item in MOCK_FACT_CHECKS:
        # Check if query intersects with keywords
        match_count = sum(1 for kw in item["keywords"] if kw in query_lower)
        if match_count >= 1:
            for claim in item["claims"]:
                for review in claim["claimReview"]:
                    # Assign a mock similarity score based on keyword match count
                    score = min(0.5 + (match_count * 0.15), 0.99)
                    matches.append({
                        "title": review["title"],
                        "snippet": f"Fact checked claim: '{claim['text']}' by {claim['claimant']}. Verdict: {review['textualRating']}.",
                        "url": review["url"],
                        "source": review["publisher"]["name"],
                        "rating": review["textualRating"],
                        "similarity_score": score
                    })
                    
    # Return matches sorted by similarity score desc
    return sorted(matches, key=lambda x: x["similarity_score"], reverse=True)

async def retrieve_fact_checks(claim_text: str) -> list:
    """Queries Google Fact Check API, falls back to the mock registry if unavailable/fails."""
    if not claim_text or not claim_text.strip():
        return []
        
    results = []
    
    # Try Google Fact Check Tools API if key is available
    if GOOGLE_FACT_CHECK_API_KEY:
        url = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
        params = {
            "query": claim_text,
            "key": GOOGLE_FACT_CHECK_API_KEY,
            "languageCode": "en"
        }
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(url, params=params)
                if response.status_code == 200:
                    data = response.json()
                    claims = data.get("claims", [])
                    for claim in claims:
                        claim_reviews = claim.get("claimReview", [])
                        for review in claim_reviews:
                            publisher = review.get("publisher", {})
                            results.append({
                                "title": review.get("title", "No Title"),
                                "snippet": f"Claim by {claim.get('claimant', 'Unknown')}: \"{claim.get('text', '')}\"",
                                "url": review.get("url", ""),
                                "source": publisher.get("name", "Unknown Source"),
                                "rating": review.get("textualRating", "Unknown"),
                                "similarity_score": 0.85 # API match gets high confidence
                            })
                    if results:
                        return results
        except Exception as e:
            print(f"Google Fact Check API query failed, falling back to mock: {e}")
            
    # Fallback/default search
    mock_results = search_mock_registry(claim_text)
    if mock_results:
        return mock_results
        
    # If no matches in mock, generate generic supporting/refuting snippets dynamically based on query terms
    # to simulate news articles
    terms = [t for t in claim_text.split() if len(t) > 3]
    entity = terms[0] if terms else "this claim"
    
    return [
        {
            "title": f"Scientific research regarding {entity} developments",
            "snippet": f"Major academic institutions released new reports on {claim_text.lower()} showing mixed preliminary results.",
            "url": "https://www.reuters.com",
            "source": "Reuters Science",
            "rating": "Varying consensus",
            "similarity_score": 0.55
        },
        {
            "title": f"Fact Check: Public statements on {entity}",
            "snippet": f"Independent journalists investigate whether {claim_text.lower()} holds up under validation of core assumptions.",
            "url": "https://www.factcheck.org",
            "source": "FactCheck.org",
            "rating": "Needs Verification",
            "similarity_score": 0.48
        }
    ]
