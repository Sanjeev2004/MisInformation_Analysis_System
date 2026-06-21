import json
import re

from google.genai import types

from backend.services.claim_extractor import get_gemini_client

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def analyze_image_context(image_bytes: bytes, mime_type: str, claim_text: str = "") -> dict:
    """Use Gemini vision to determine whether an image supports its accompanying claim."""
    if mime_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError("Image must be JPEG, PNG, or WebP")
    if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("Image must be between 1 byte and 5 MB")

    client = get_gemini_client()
    if not client:
        return {
            "status": "unavailable",
            "image_description": "Image received; configure GEMINI_API_KEY for visual analysis.",
            "relationship": "unknown",
            "mismatch_score": 0.5,
            "explanation": "Multimodal analysis is unavailable without a Gemini API key.",
        }

    prompt = (
        "Act as a misinformation image-context investigator. Inspect this image and compare it "
        "with the accompanying claim. Look for signs that the image is old, unrelated, edited, "
        "synthetic, or being used without enough context. Do not identify unknown people. "
        "Return ONLY JSON with: image_description (string), relationship (one of supports, "
        "contradicts, out_of_context, insufficient_context), mismatch_score (number 0 to 1, where "
        "1 is clearly mismatched), and explanation (concise string).\n\n"
        f"Accompanying claim: {claim_text or '[No text supplied; describe and assess the image alone.]'}"
    )
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[prompt, types.Part.from_bytes(data=image_bytes, mime_type=mime_type)],
        )
        raw = response.text.strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
        result = json.loads(raw)
        relationship = result.get("relationship", "insufficient_context")
        if relationship not in {"supports", "contradicts", "out_of_context", "insufficient_context"}:
            relationship = "insufficient_context"
        return {
            "status": "complete",
            "image_description": str(result.get("image_description", ""))[:1000],
            "relationship": relationship,
            "mismatch_score": max(0.0, min(float(result.get("mismatch_score", 0.5)), 1.0)),
            "explanation": str(result.get("explanation", ""))[:1000],
        }
    except Exception as exc:
        return {
            "status": "error",
            "image_description": "The image could not be interpreted.",
            "relationship": "unknown",
            "mismatch_score": 0.5,
            "explanation": f"Gemini vision analysis failed: {type(exc).__name__}",
        }
