import asyncio
import datetime as dt
import math
import re
import socket
import ssl
import httpx
import numpy as np
from sklearn.linear_model import LogisticRegression

from backend.services.ingestion import extract_domain

SUSPICIOUS_TLDS = {"zip", "mov", "click", "top", "xyz", "buzz", "rest", "country", "gq", "tk"}

# Curated feature profiles provide a small, deterministic starter model. Features:
# log domain age, valid TLS, RDAP record, suspicious TLD, length, digit ratio, hyphens.
_TRAIN_X = np.array([
    [8.9, 1, 1, 0, .25, 0, 0], [9.4, 1, 1, 0, .35, 0, 0],
    [8.1, 1, 1, 0, .42, 0, 0], [7.5, 1, 1, 0, .30, .02, 0],
    [6.8, 1, 1, 0, .48, 0, 1], [5.9, 1, 1, 0, .38, .03, 0],
    [0.8, 0, 0, 1, .72, .18, 2], [1.4, 1, 1, 1, .82, .20, 3],
    [2.0, 0, 1, 0, .90, .25, 4], [0.2, 0, 0, 0, .65, .12, 2],
    [3.0, 1, 1, 1, .55, .08, 1], [1.0, 1, 0, 0, .95, .30, 3],
], dtype=float)
_TRAIN_Y = np.array([1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0])
_MODEL = LogisticRegression(C=1.2, random_state=7).fit(_TRAIN_X, _TRAIN_Y)


def _tls_valid(domain: str) -> bool:
    try:
        context = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=2.5) as raw:
            with context.wrap_socket(raw, server_hostname=domain):
                return True
    except (OSError, ssl.SSLError):
        return False


async def _rdap_features(domain: str) -> tuple[bool, int | None]:
    try:
        async with httpx.AsyncClient(timeout=3.5, follow_redirects=True) as client:
            response = await client.get(f"https://rdap.org/domain/{domain}")
        if response.status_code != 200:
            return False, None
        data = response.json()
        dates = []
        for event in data.get("events", []):
            if event.get("eventAction") in {"registration", "registered"} and event.get("eventDate"):
                dates.append(dt.datetime.fromisoformat(event["eventDate"].replace("Z", "+00:00")))
        if not dates:
            return True, None
        created = min(dates)
        age = max(0, (dt.datetime.now(dt.timezone.utc) - created).days)
        return True, age
    except (httpx.HTTPError, ValueError, TypeError):
        return False, None


def _vector(domain: str, age_days: int | None, tls_valid: bool, rdap_available: bool) -> np.ndarray:
    label = domain.split(".")[0]
    digits = sum(ch.isdigit() for ch in domain)
    tld = domain.rsplit(".", 1)[-1]
    return np.array([[
        math.log1p(age_days or 0), float(tls_valid), float(rdap_available),
        float(tld in SUSPICIOUS_TLDS), min(len(domain) / 50, 1),
        digits / max(len(domain), 1), min(label.count("-"), 4),
    ]], dtype=float)


async def analyze_domain_reputation(url_or_domain: str | None) -> dict:
    if not url_or_domain:
        return {"score": 0.5, "status": "no_domain", "features": {}}
    domain = extract_domain(url_or_domain) if "://" in url_or_domain else url_or_domain.lower()
    domain = re.sub(r"^www\.", "", domain).strip(".")
    if not domain:
        return {"score": 0.5, "status": "invalid_domain", "features": {}}

    tls_valid, (rdap_available, age_days) = await asyncio.gather(
        asyncio.to_thread(_tls_valid, domain), _rdap_features(domain)
    )
    probability = float(_MODEL.predict_proba(_vector(domain, age_days, tls_valid, rdap_available))[0, 1])
    # Missing registration data increases uncertainty, so gently pull toward neutral.
    if not rdap_available:
        probability = 0.65 * probability + 0.35 * 0.5
    return {
        "score": round(probability, 3), "status": "complete",
        "features": {"domain": domain, "age_days": age_days, "tls_valid": tls_valid,
                     "whois_rdap_available": rdap_available},
    }
