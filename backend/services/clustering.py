import logging
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from backend.database import get_db_connection
from backend.services.claim_extractor import get_gemini_client
from backend.config import GEMINI_EMBEDDING_MODEL

logger = logging.getLogger("emews.clustering")


def build_similarity_matrix(texts: list[str]) -> tuple[np.ndarray, str]:
    """Prefer Gemini semantic embeddings, with an offline TF-IDF fallback."""
    client = get_gemini_client()
    if client:
        try:
            response = client.models.embed_content(
                model=GEMINI_EMBEDDING_MODEL,
                contents=texts,
            )
            vectors = np.asarray([embedding.values for embedding in response.embeddings], dtype=float)
            if vectors.shape[0] != len(texts):
                raise ValueError("Embedding API returned an unexpected vector count")
            return cosine_similarity(vectors), "gemini"
        except Exception as exc:
            logger.warning("Gemini embeddings unavailable; using TF-IDF fallback: %s", exc)

    try:
        matrix = TfidfVectorizer(stop_words="english").fit_transform(texts)
        return cosine_similarity(matrix), "tfidf"
    except Exception as exc:
        logger.warning("Could not vectorize claims; using exact isolation: %s", exc)
        return np.eye(len(texts)), "identity"

def summarize_cluster_title(claims: list) -> str:
    """Uses Gemini to generate a clean, consolidated claim title from a group of claims."""
    if not claims:
        return "Unknown Claim"
    if len(claims) == 1:
        return claims[0]
        
    client = get_gemini_client()
    if not client:
        return claims[0] # Fallback to first claim
        
    prompt = (
        "You are an expert editor. Below is a list of similar claims/rumors circulating online. "
        "Consolidate them into a single, clean, objective, neutral headline (max 10 words) representing this claim topic.\n\n"
        "Claims:\n" + "\n".join(f"- {c}" for c in claims) + "\n\n"
        "Return ONLY the consolidated title string. Do not use quotes or introductory words."
    )
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        return response.text.strip().strip('"').strip("'")
    except Exception:
        return claims[0]

def run_clustering():
    """
    Groups posts with Gemini semantic embeddings and cosine similarity. Falls back
    to TF-IDF when Gemini is not configured or temporarily unavailable.
    Updates the posts and clusters tables, calculating average risk scores.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Fetch all posts
    cursor.execute("SELECT id, text, claim_text, overall_risk FROM posts")
    rows = cursor.fetchall()
    
    if not rows:
        conn.close()
        return
        
    posts = []
    for r in rows:
        posts.append({
            "id": r["id"],
            "text": r["text"],
            "claim_text": r["claim_text"] or r["text"], # fallback to raw text if claim_text is empty
            "overall_risk": r["overall_risk"]
        })
        
    # Clear current cluster assignments in DB and delete empty clusters
    cursor.execute("UPDATE posts SET cluster_id = NULL")
    cursor.execute("DELETE FROM clusters")
    conn.commit()
    
    # If there is only 1 post, create a single cluster
    if len(posts) == 1:
        claim_title = posts[0]["claim_text"]
        cursor.execute(
            "INSERT INTO clusters (claim_title, average_risk) VALUES (?, ?)",
            (claim_title, posts[0]["overall_risk"])
        )
        cluster_id = cursor.lastrowid
        cursor.execute("UPDATE posts SET cluster_id = ? WHERE id = ?", (cluster_id, posts[0]["id"]))
        conn.commit()
        conn.close()
        return
        
    # 2. Extract texts and compute semantic similarity
    texts = [p["claim_text"] for p in posts]
    sim_matrix, similarity_source = build_similarity_matrix(texts)
        
    # 3. Simple threshold-based clustering (distance threshold = 0.5)
    similarity_threshold = 0.72 if similarity_source == "gemini" else 0.4
    assigned_clusters = {} # post_id -> cluster_id
    clusters_data = {} # cluster_id -> list of posts
    
    cluster_counter = 1
    
    for i, post in enumerate(posts):
        post_id = post["id"]
        if post_id in assigned_clusters:
            continue
            
        # Find all other posts with similarity above threshold
        similar_indices = np.where(sim_matrix[i] >= similarity_threshold)[0]
        
        # Group them
        group_posts = []
        for idx in similar_indices:
            other_post = posts[idx]
            other_id = other_post["id"]
            if other_id not in assigned_clusters:
                assigned_clusters[other_id] = cluster_counter
                group_posts.append(other_post)
                
        if group_posts:
            clusters_data[cluster_counter] = group_posts
            cluster_counter += 1
            
    # 4. Insert clusters into DB and link posts
    for cluster_id, c_posts in clusters_data.items():
        claims = [p["claim_text"] for p in c_posts]
        claim_title = summarize_cluster_title(claims)
        
        # Calculate average risk
        avg_risk = float(np.mean([p["overall_risk"] for p in c_posts]))
        
        # We can extract main entities as well by collecting all entities (mock or combine)
        # In a real system we could query DB for entities of these posts
        entities = []
        
        cursor.execute(
            "INSERT INTO clusters (claim_title, main_entities, average_risk) VALUES (?, ?, ?)",
            (claim_title, ",".join(entities), avg_risk)
        )
        db_cluster_id = cursor.lastrowid
        
        # Update posts
        for p in c_posts:
            cursor.execute("UPDATE posts SET cluster_id = ? WHERE id = ?", (db_cluster_id, p["id"]))
            
    conn.commit()
    conn.close()
    logger.info("Clustering completed using %s similarity.", similarity_source)
