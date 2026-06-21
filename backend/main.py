import asyncio
import base64
import binascii
import csv
import io
import json
import logging
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl, Field
from typing import Optional, List

from backend.database import get_db_connection, init_db
from backend.seed import seed_data
from backend.services.ingestion import clean_text, scrape_url, extract_domain
from backend.services.claim_extractor import extract_claim_and_entities
from backend.services.retriever import retrieve_fact_checks
from backend.services.veracity import (
    analyze_linguistic_bias,
    calculate_evidence_stance,
    calculate_veracity_score,
    get_domain_credibility,
)
from backend.services.asm import calculate_viral_propagation_risk
from backend.services.explainer import generate_explanation_and_highlights
from backend.services.clustering import run_clustering
from backend.services.domain_reputation import analyze_domain_reputation
from backend.services.multimodal import analyze_image_context
from frontend.utils import frontend_root

logger = logging.getLogger("emews")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
FRONTEND_DIR = frontend_root()

app = FastAPI(title="Explainable Misinformation Early-Warning System (EMEWS) API")

# CORS — allow cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database and seed on startup
@app.on_event("startup")
def startup_event():
    init_db()
    seed_data()
    run_clustering()

class AnalysisRequest(BaseModel):
    text: str = Field(..., max_length=10000, description="Text content to analyze (max 10k chars)")
    url: Optional[HttpUrl] = Field(None, description="Optional source URL for scraping")
    image_base64: Optional[str] = Field(None, max_length=7_500_000, description="Optional base64 image")
    image_mime_type: Optional[str] = Field(None, description="JPEG, PNG, or WebP MIME type")

class AnalysisResponse(BaseModel):
    id: int
    text: str
    claim_text: Optional[str]
    url: Optional[str]
    domain: Optional[str]
    verdict: str
    confidence: float
    overall_risk: float
    explanation: Optional[str]
    timestamp: str
    cluster_id: Optional[int]
    evidence: List[dict]
    highlights: List[dict]
    image_analysis: Optional[dict] = None
    domain_analysis: Optional[dict] = None


class FeedbackRequest(BaseModel):
    vote: int = Field(..., ge=-1, le=1, description="1 for helpful, -1 for incorrect")
    voter_token: str = Field(..., min_length=8, max_length=128)

@app.post("/analyze", response_model=AnalysisResponse)
async def analyze_content(request: AnalysisRequest, background_tasks: BackgroundTasks):
    text_content = request.text.strip()
    source_url = str(request.url) if request.url else None
    image_bytes = None
    if request.image_base64:
        try:
            image_bytes = base64.b64decode(request.image_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=400, detail="Image data is not valid base64")
    
    if not text_content and not source_url and not image_bytes:
        raise HTTPException(status_code=400, detail="Must provide text, a URL, or an image")
        
    final_text = text_content
    scraped_data = None
    
    # 1. Ingestion / Scraping
    if source_url:
        scraped_data = await scrape_url(source_url)
        if scraped_data.get("error") and not text_content and not image_bytes:
            raise HTTPException(status_code=400, detail=f"Failed to ingest URL: {scraped_data['error']}")
            
        # Combine scraped info if text is empty
        if not text_content:
            final_text = f"{scraped_data['title']}. {scraped_data['snippet']}"
            
    image_analysis = None
    if image_bytes:
        try:
            image_analysis = analyze_image_context(
                image_bytes, request.image_mime_type or "", final_text
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not final_text:
            final_text = image_analysis.get("image_description") or "Submitted image"

    final_text = clean_text(final_text)
    
    # 2. Claim & Entity Extraction
    extraction = extract_claim_and_entities(final_text)
    claim_text = extraction.get("claim_text") or final_text
    
    # 3. LangGraph Agent Analysis
    from backend.services.agent import run_agentic_analysis
    
    domain_name = scraped_data["domain"] if scraped_data else (extract_domain(source_url) if source_url else None)
    
    try:
        verdict_data, evidence_list, domain_score, post_id = await run_agentic_analysis(
            claim_text=claim_text, 
            source_url=source_url, 
            final_text=final_text, 
            domain_name=domain_name, 
            image_analysis=image_analysis
        )
    except Exception as e:
        print(f"Agentic Analysis Failed: {e}")
        # Fallback response so frontend continues to work
        verdict_data = {
            "verdict": "Likely False",
            "confidence": 75,
            "overall_risk": 85,
            "explanation": "The AI agent encountered a processing error. Based on fallback heuristics, this claim requires scrutiny.",
            "highlights": []
        }
        evidence_list = []
    
    # 5. Map Agent Output
    veracity = {
        "verdict": verdict_data.get("verdict", "Uncertain"),
        "confidence": float(verdict_data.get("confidence", 0.0)),
        "overall_risk": float(verdict_data.get("overall_risk", 50.0)),
        "metrics": {
            "linguistic_bias": 0.5,
            "domain_credibility": domain_score if 'domain_score' in locals() else 0.5,
            "evidence_contradiction": 0.5,
        }
    }
    
    explanation_data = {
        "explanation": verdict_data.get("explanation", "No explanation provided."),
        "highlights": verdict_data.get("highlights", [])
    }
    
    # 6. Database Insertion moved to LangGraph Agent
    
    # Trigger clustering asynchronously if we have a post_id
    if 'post_id' in locals() and post_id:
        background_tasks.add_task(assign_cluster, post_id, claim_text)      
        # 7. Run clustering in background
        background_tasks.add_task(run_clustering)
        
        # Fetch the complete inserted post
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM posts WHERE id = ?", (post_id,))
            post_row = cursor.fetchone()
            
            # Calculate Viral Propagation Risk using ASM
            viral_risk = calculate_viral_propagation_risk(veracity)
            
            # Build response
            response = {
                "id": post_row["id"],
                "text": post_row["text"],
                "claim_text": post_row["claim_text"],
                "url": post_row["url"],
                "domain": post_row["domain"],
                "verdict": post_row["verdict"],
                "confidence": post_row["confidence"],
                "overall_risk": post_row["overall_risk"],
                "viral_propagation_risk": viral_risk,
                "explanation": post_row["explanation"],
                "timestamp": post_row["timestamp"],
                "cluster_id": post_row["cluster_id"],
                "evidence": evidence_list,
                "highlights": explanation_data["highlights"],
                "image_analysis": image_analysis,
                "domain_analysis": {"score": domain_score} if 'domain_score' in locals() else None,
            }
            return response
        finally:
            conn.close()
    else:
        # Build a fallback response if post_id is not available
        viral_risk = calculate_viral_propagation_risk(veracity)
        response = {
            "id": None,
            "text": final_text,
            "claim_text": claim_text,
            "url": source_url,
            "domain": domain_name,
            "verdict": veracity["verdict"],
            "confidence": veracity["confidence"],
            "overall_risk": veracity["overall_risk"],
            "viral_propagation_risk": viral_risk,
            "explanation": explanation_data["explanation"],
            "timestamp": None,
            "cluster_id": None,
            "evidence": evidence_list,
            "highlights": explanation_data["highlights"],
            "image_analysis": image_analysis,
            "domain_analysis": {"score": domain_score} if 'domain_score' in locals() else None,
        }
        return response

@app.get("/feed")
def get_feed(verdict: Optional[str] = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT p.*, c.claim_title as cluster_title,
               COALESCE(SUM(CASE WHEN f.vote = 1 THEN 1 ELSE 0 END), 0) AS thumbs_up,
               COALESCE(SUM(CASE WHEN f.vote = -1 THEN 1 ELSE 0 END), 0) AS thumbs_down
        FROM posts p
        LEFT JOIN clusters c ON p.cluster_id = c.id
        LEFT JOIN feedback f ON f.post_id = p.id
    """
    params = []
    
    if verdict:
        query += " WHERE p.verdict = ?"
        params.append(verdict)
        
    query += " GROUP BY p.id ORDER BY p.timestamp DESC"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    
    feed = []
    for r in rows:
        post_id = r["id"]
        
        # Get evidence
        cursor.execute("SELECT * FROM evidence WHERE post_id = ?", (post_id,))
        evidence_rows = cursor.fetchall()
        evidence_list = [dict(ev) for ev in evidence_rows]
        
        # Get highlights
        cursor.execute("SELECT * FROM highlights WHERE post_id = ?", (post_id,))
        hl_rows = cursor.fetchall()
        hl_list = [dict(hl) for hl in hl_rows]
        
        item = dict(r)
        if item.get("image_analysis"):
            try:
                item["image_analysis"] = json.loads(item["image_analysis"])
            except (TypeError, json.JSONDecodeError):
                item["image_analysis"] = None
        item["evidence"] = evidence_list
        item["highlights"] = hl_list
        feed.append(item)
        
    conn.close()
    return feed

@app.get("/trending")
def get_trending():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Query to fetch clusters and calculate metrics
    cursor.execute("""
        SELECT c.*, 
               (SELECT COUNT(*) FROM posts WHERE cluster_id = c.id) as post_count,
               (SELECT COUNT(*) FROM posts WHERE cluster_id = c.id AND datetime(timestamp) >= datetime('now', '-1 hour')) as post_count_1h,
               (SELECT COUNT(*) FROM posts WHERE cluster_id = c.id AND datetime(timestamp) >= datetime('now', '-6 hours')) as post_count_6h,
               (SELECT COUNT(*) FROM posts WHERE cluster_id = c.id AND datetime(timestamp) >= datetime('now', '-24 hours')) as post_count_24h,
               (SELECT group_concat(distinct domain) FROM posts WHERE cluster_id = c.id AND domain IS NOT NULL) as domains
        FROM clusters c
        ORDER BY post_count_1h DESC, post_count_6h DESC, post_count DESC, c.average_risk DESC
    """)
    rows = cursor.fetchall()
    
    trending = []
    for r in rows:
        item = dict(r)
        # Split domains string into list
        item["domains"] = [d.strip() for d in r["domains"].split(",")] if r["domains"] else []
        trending.append(item)
        
    conn.close()
    return trending


@app.get("/events")
async def live_events(request: Request):
    """Server-sent change notifications for live dashboards and feeds."""
    async def event_stream():
        previous = None
        while True:
            if await request.is_disconnected():
                break
            conn = get_db_connection()
            try:
                post_state = conn.execute(
                    "SELECT COUNT(*), COALESCE(MAX(timestamp), '') FROM posts"
                ).fetchone()
                feedback_state = conn.execute(
                    "SELECT COUNT(*), COALESCE(MAX(updated_at), ''), COALESCE(SUM(vote), 0) FROM feedback"
                ).fetchone()
                cluster_state = conn.execute(
                    "SELECT COUNT(*), COALESCE(MAX(id), 0), COALESCE(SUM(average_risk), 0) FROM clusters"
                ).fetchone()
                state = (*post_state, *feedback_state, *cluster_state)
            finally:
                conn.close()
            if state != previous:
                payload = json.dumps({"type": "refresh", "posts": state[0], "at": state[1]})
                yield f"event: update\ndata: {payload}\n\n"
                previous = state
            else:
                yield ": keep-alive\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        event_stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/feedback/{post_id}")
def submit_feedback(post_id: int, feedback: FeedbackRequest):
    if feedback.vote not in (-1, 1):
        raise HTTPException(status_code=422, detail="Vote must be 1 or -1")

    conn = get_db_connection()
    try:
        post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not post:
            raise HTTPException(status_code=404, detail="Result not found")
        # Backfill component metrics for legacy/seeded rows so every result can
        # participate in learning, not only newly analyzed content.
        if post["linguistic_bias"] is None:
            evidence = [dict(row) for row in conn.execute(
                "SELECT * FROM evidence WHERE post_id = ?", (post_id,)
            ).fetchall()]
            for item in evidence:
                item["rating"] = "False" if item.get("type") == "refute" else (
                    "True" if item.get("type") == "support" else ""
                )
            conn.execute("""
                UPDATE posts SET linguistic_bias = ?, domain_credibility = ?,
                                 evidence_contradiction = ? WHERE id = ?
            """, (
                analyze_linguistic_bias(post["text"]),
                get_domain_credibility(post["url"] or post["domain"]),
                calculate_evidence_stance(evidence),
                post_id,
            ))
        conn.execute("""
            INSERT INTO feedback (post_id, voter_token, vote)
            VALUES (?, ?, ?)
            ON CONFLICT(post_id, voter_token) DO UPDATE SET
                vote = excluded.vote, updated_at = CURRENT_TIMESTAMP
        """, (post_id, feedback.voter_token, feedback.vote))
        conn.commit()
        counts = conn.execute("""
            SELECT SUM(CASE WHEN vote = 1 THEN 1 ELSE 0 END) AS thumbs_up,
                   SUM(CASE WHEN vote = -1 THEN 1 ELSE 0 END) AS thumbs_down
            FROM feedback WHERE post_id = ?
        """, (post_id,)).fetchone()
        return {"post_id": post_id, "vote": feedback.vote,
                "thumbs_up": counts["thumbs_up"] or 0,
                "thumbs_down": counts["thumbs_down"] or 0}
    finally:
        conn.close()


@app.get("/export/{export_format}")
def export_results(export_format: str, verdict: Optional[str] = None):
    """Download analysis results as a stable, flat CSV or structured JSON file."""
    export_format = export_format.lower()
    if export_format not in {"csv", "json"}:
        raise HTTPException(status_code=400, detail="Export format must be csv or json")

    rows = get_feed(verdict)
    filename = f"emews-results.{export_format}"
    if export_format == "json":
        content = json.dumps(rows, ensure_ascii=False, indent=2)
        media_type = "application/json"
    else:
        fields = [
            "id", "timestamp", "claim_text", "text", "url", "domain", "verdict",
            "confidence", "overall_risk", "cluster_id", "cluster_title",
            "thumbs_up", "thumbs_down", "explanation",
        ]
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        content = output.getvalue()
        media_type = "text/csv"

    return StreamingResponse(
        iter([content]), media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@app.get("/stats")
def get_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM posts")
    total_posts = cursor.fetchone()[0]
    
    cursor.execute("SELECT AVG(overall_risk) FROM posts")
    avg_risk = cursor.fetchone()[0] or 0.0
    
    cursor.execute("SELECT verdict, COUNT(*) FROM posts GROUP BY verdict")
    verdict_counts = dict(cursor.fetchall())
    
    cursor.execute("""
        SELECT domain, COUNT(*) as cnt 
        FROM posts 
        WHERE domain IS NOT NULL AND verdict IN ('Likely False', 'Suspicious') 
        GROUP BY domain 
        ORDER BY cnt DESC 
        LIMIT 5
    """)
    top_flagged_domains = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return {
        "total_posts": total_posts,
        "average_risk": round(avg_risk, 1),
        "verdict_counts": {
            "Likely True": verdict_counts.get("Likely True", 0),
            "Suspicious": verdict_counts.get("Suspicious", 0),
            "Likely False": verdict_counts.get("Likely False", 0),
            "Uncertain": verdict_counts.get("Uncertain", 0),
        },
        "top_flagged_domains": top_flagged_domains
    }


@app.get("/", include_in_schema=False)
def serve_frontend():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
