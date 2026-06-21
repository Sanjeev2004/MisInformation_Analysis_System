import os

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GOOGLE_FACT_CHECK_API_KEY = os.environ.get("GOOGLE_FACT_CHECK_API_KEY", "")
GEMINI_EMBEDDING_MODEL = os.environ.get("GEMINI_EMBEDDING_MODEL", "text-embedding-004")

# Veracity engine weights
W_BIAS = 0.3
W_DOMAIN = 0.3
W_EVIDENCE = 0.4
