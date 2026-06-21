import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "emews.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create clusters table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS clusters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        claim_title TEXT NOT NULL,
        main_entities TEXT,
        average_risk REAL DEFAULT 0.0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Create posts table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        claim_text TEXT,
        url TEXT,
        domain TEXT,
        verdict TEXT NOT NULL,
        confidence REAL DEFAULT 0.0,
        overall_risk REAL DEFAULT 0.0,
        explanation TEXT,
        linguistic_bias REAL,
        domain_credibility REAL,
        evidence_contradiction REAL,
        image_analysis TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        cluster_id INTEGER,
        FOREIGN KEY (cluster_id) REFERENCES clusters(id)
    )
    """)

    # Lightweight migrations for databases created by earlier versions.
    cursor.execute("PRAGMA table_info(posts)")
    post_columns = {row[1] for row in cursor.fetchall()}
    for column in ("linguistic_bias", "domain_credibility", "evidence_contradiction", "image_analysis"):
        if column not in post_columns:
            column_type = "TEXT" if column == "image_analysis" else "REAL"
            cursor.execute(f"ALTER TABLE posts ADD COLUMN {column} {column_type}")
    
    # Create evidence table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS evidence (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        title TEXT,
        snippet TEXT,
        url TEXT,
        source TEXT,
        type TEXT CHECK(type IN ('support', 'refute', 'fact-check')),
        similarity_score REAL,
        FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
    )
    """)
    
    # Create highlights table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS highlights (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        phrase TEXT NOT NULL,
        category TEXT CHECK(category IN ('sensational', 'fallacy', 'unverified')),
        FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
    )
    """)

    # Votes are append-only audit events. A browser-generated voter token makes
    # submissions idempotent while preserving anonymous feedback.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        voter_token TEXT NOT NULL,
        vote INTEGER NOT NULL CHECK(vote IN (-1, 1)),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(post_id, voter_token),
        FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE
    )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_cluster_timestamp ON posts(cluster_id, timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_post ON feedback(post_id)")
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
