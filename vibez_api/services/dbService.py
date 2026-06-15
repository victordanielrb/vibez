import json
import os
import time
import uuid
import sqlite3
import struct
import sqlite_vec

DB_PATH = os.getenv("DB_PATH", "vibez.db")
_DEAD_THRESHOLD = 1800  # seconds — a running job older than this is considered dead

IMAGE_SEARCH_LIMIT = int(os.getenv("IMAGE_SEARCH_LIMIT", "20"))
TRACK_INGEST_LIMIT = int(os.getenv("TRACK_INGEST_LIMIT", "200"))
TOKEN_DAILY_LIMIT = int(os.getenv("TOKEN_DAILY_LIMIT", "50000"))

# Global limits matching Gemini 3.1 Flash Lite free tier
GLOBAL_RPM_LIMIT = int(os.getenv("GLOBAL_RPM_LIMIT", "15"))
GLOBAL_TPM_LIMIT = int(os.getenv("GLOBAL_TPM_LIMIT", "250000"))
GLOBAL_RPD_LIMIT = int(os.getenv("GLOBAL_RPD_LIMIT", "500"))

_conn: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.enable_load_extension(True)
        sqlite_vec.load(_conn)
        _conn.enable_load_extension(False)
        _init_schema(_conn)
    return _conn


def _init_schema(conn: sqlite3.Connection) -> None:
    # Detect old schema (track_vectors rowid → tracks.id) and reset it
    has_chunks = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='track_chunks'"
    ).fetchone()
    if not has_chunks:
        conn.execute("DROP TABLE IF EXISTS track_vectors")
        conn.commit()

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tracks (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            name    TEXT NOT NULL,
            author  TEXT NOT NULL,
            url     TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS track_chunks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id    INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
            offset      INTEGER NOT NULL,
            description TEXT,
            features    TEXT
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS track_vectors USING vec0(
            embedding FLOAT[768] distance_metric=cosine
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id           TEXT PRIMARY KEY,
            playlist_url TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'running',
            started_at   REAL,
            finished_at  REAL,
            error        TEXT,
            processed    INTEGER DEFAULT 0,
            total        INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS searches (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            image_data  TEXT NOT NULL,
            description TEXT NOT NULL,
            created_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS search_results (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            search_id INTEGER NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
            track_id  INTEGER NOT NULL REFERENCES tracks(id),
            rank      INTEGER NOT NULL,
            reason    TEXT,
            distance  REAL
        );

        CREATE TABLE IF NOT EXISTS api_usage (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            client_ip  TEXT NOT NULL,
            operation  TEXT NOT NULL,
            model      TEXT NOT NULL DEFAULT '',
            tokens_in  INTEGER DEFAULT 0,
            tokens_out INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    for migration in [
        "ALTER TABLE tracks ADD COLUMN description TEXT",
        "ALTER TABLE searches ADD COLUMN client_ip TEXT",
        "ALTER TABLE jobs ADD COLUMN callback_url TEXT",
        "ALTER TABLE track_chunks ADD COLUMN description TEXT",
        "ALTER TABLE track_chunks ADD COLUMN features TEXT",
    ]:
        try:
            conn.execute(migration)
            conn.commit()
        except Exception:
            pass


def _serialize(embedding: list[float]) -> bytes:
    return struct.pack(f"{len(embedding)}f", *embedding)


def insert_track_chunks(
    name: str,
    author: str,
    url: str,
    chunks: list[dict],  # each: {offset, embedding, description, ...}
) -> int:
    conn = get_conn()
    description = chunks[0].get("description") if chunks else None
    cur = conn.execute(
        "INSERT INTO tracks (name, author, url, description) VALUES (?, ?, ?, ?)"
        " ON CONFLICT(url) DO UPDATE SET"
        "   name = excluded.name,"
        "   author = excluded.author,"
        "   description = excluded.description",
        (name, author, url, description),
    )
    conn.commit()

    track_id: int = cur.lastrowid or conn.execute(
        "SELECT id FROM tracks WHERE url = ?", (url,)
    ).fetchone()[0]

    old_chunk_ids = [
        r[0] for r in conn.execute(
            "SELECT id FROM track_chunks WHERE track_id = ?", (track_id,)
        ).fetchall()
    ]
    for cid in old_chunk_ids:
        conn.execute("DELETE FROM track_vectors WHERE rowid = ?", (cid,))
    conn.execute("DELETE FROM track_chunks WHERE track_id = ?", (track_id,))
    conn.commit()

    for chunk in chunks:
        features = {k: chunk[k] for k in (
            "bpm", "key", "scale", "loudness_db",
            "energy", "valence", "danceability", "acoustic", "voice", "genres",
        ) if k in chunk}
        cur2 = conn.execute(
            "INSERT INTO track_chunks (track_id, offset, description, features) VALUES (?, ?, ?, ?)",
            (track_id, chunk["offset"], chunk.get("description"), json.dumps(features)),
        )
        chunk_id: int = cur2.lastrowid
        conn.execute(
            "INSERT INTO track_vectors (rowid, embedding) VALUES (?, ?)",
            (chunk_id, _serialize(chunk["embedding"])),
        )
    conn.commit()
    return track_id


def search_by_embedding(embedding: list[float], limit: int = 10) -> list[dict]:
    conn = get_conn()
    # Fetch extra candidates to have margin after 2-per-track dedup
    fetch_k = limit * 6
    rows = conn.execute(
        """
        SELECT tc.track_id, tc.offset, t.name, t.author, t.url,
               COALESCE(tc.description, t.description), v.distance, tc.features
        FROM track_vectors v
        JOIN track_chunks tc ON tc.id = v.rowid
        JOIN tracks t ON t.id = tc.track_id
        WHERE v.embedding MATCH ?
          AND k = ?
        ORDER BY v.distance
        """,
        (_serialize(embedding), fetch_k),
    ).fetchall()

    # Dedup: max 2 chunks per track, keeping closest distance first
    seen: dict[int, int] = {}
    deduped = []
    for r in rows:
        track_id = r[0]
        count = seen.get(track_id, 0)
        if count < 2:
            deduped.append(r)
            seen[track_id] = count + 1
        if len(deduped) >= limit:
            break

    return [
        {
            "id": r[0],
            "offset": r[1],
            "name": r[2],
            "author": r[3],
            "url": r[4],
            "description": r[5],
            "distance": r[6],
            "features": json.loads(r[7]) if r[7] else None,
        }
        for r in deduped
    ]


# ── Job tracking ──────────────────────────────────────────────────────────────

def _row_to_job(row: tuple) -> dict:
    return {
        "id": row[0],
        "playlist_url": row[1],
        "status": row[2],
        "started_at": row[3],
        "finished_at": row[4],
        "error": row[5],
        "processed": row[6],
        "total": row[7],
        "callback_url": row[8] if len(row) > 8 else None,
    }


def _check_dead(conn: sqlite3.Connection, job: dict) -> dict:
    if job["status"] == "running" and job["started_at"] and (time.time() - job["started_at"]) > _DEAD_THRESHOLD:
        conn.execute("UPDATE jobs SET status = 'dead' WHERE id = ?", (job["id"],))
        conn.commit()
        job["status"] = "dead"
    return job


def create_job(playlist_url: str, callback_url: str | None = None, total: int = 0) -> str:
    job_id = str(uuid.uuid4())
    conn = get_conn()
    conn.execute(
        "INSERT INTO jobs (id, playlist_url, status, started_at, total, callback_url) VALUES (?, ?, 'running', ?, ?, ?)",
        (job_id, playlist_url, time.time(), total, callback_url),
    )
    conn.commit()
    return job_id


def increment_job_processed(job_id: str) -> int:
    conn = get_conn()
    conn.execute("UPDATE jobs SET processed = processed + 1 WHERE id = ?", (job_id,))
    conn.commit()
    row = conn.execute("SELECT processed FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return row[0] if row else 0


def _fire_webhook(job: dict) -> None:
    url = job.get("callback_url")
    if not url:
        return
    import json, urllib.request
    payload = json.dumps({
        "jobId": job["id"],
        "status": job["status"],
        "playlist_url": job["playlist_url"],
        "processed": job["processed"],
        "total": job["total"],
        "error": job.get("error"),
    }).encode()
    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        logger.info("webhook fired for job %s → %s", job["id"], url)
    except Exception as exc:
        logger.warning("webhook failed for job %s: %s", job["id"], exc)


def update_job_progress(job_id: str, processed: int, total: int) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE jobs SET processed = ?, total = ? WHERE id = ?",
        (processed, total, job_id),
    )
    conn.commit()


def finish_job(job_id: str) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE jobs SET status = 'done', finished_at = ? WHERE id = ?",
        (time.time(), job_id),
    )
    conn.commit()
    job = get_job(job_id)
    if job:
        _fire_webhook(job)


def fail_job(job_id: str, error: str) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE jobs SET status = 'failed', finished_at = ?, error = ? WHERE id = ?",
        (time.time(), error, job_id),
    )
    conn.commit()
    job = get_job(job_id)
    if job:
        _fire_webhook(job)


def get_job(job_id: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT id, playlist_url, status, started_at, finished_at, error, processed, total, callback_url FROM jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    if not row:
        return None
    return _check_dead(conn, _row_to_job(row))


def list_jobs() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, playlist_url, status, started_at, finished_at, error, processed, total, callback_url FROM jobs ORDER BY started_at DESC"
    ).fetchall()
    jobs = [_check_dead(conn, _row_to_job(r)) for r in rows]
    return jobs


def mark_stale_jobs_dead() -> int:
    """Mark any jobs left in 'running' state from a previous server instance as dead."""
    conn = get_conn()
    cur = conn.execute("UPDATE jobs SET status = 'dead' WHERE status = 'running'")
    conn.commit()
    return cur.rowcount


# ── Search history ────────────────────────────────────────────────────────────

def save_search(image_data: str, description: str, results: list[dict]) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO searches (image_data, description, created_at) VALUES (?, ?, ?)",
        (image_data, description, time.time()),
    )
    search_id: int = cur.lastrowid
    conn.executemany(
        "INSERT INTO search_results (search_id, track_id, rank, reason, distance) VALUES (?, ?, ?, ?, ?)",
        [
            (search_id, r["id"], r["rank"], r.get("reason"), r.get("distance"))
            for r in results
        ],
    )
    conn.commit()
    return search_id


# ── API usage / quota ─────────────────────────────────────────────────────────

def log_usage(client_ip: str, operation: str, model: str = "", tokens_in: int = 0, tokens_out: int = 0) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO api_usage (client_ip, operation, model, tokens_in, tokens_out) VALUES (?, ?, ?, ?, ?)",
        (client_ip, operation, model, tokens_in, tokens_out),
    )
    conn.commit()


def get_daily_usage(client_ip: str) -> dict:
    conn = get_conn()
    row = conn.execute(
        """
        SELECT
          COALESCE(SUM(CASE WHEN operation = 'image_search' THEN 1 ELSE 0 END), 0),
          COALESCE(SUM(CASE WHEN operation = 'track_ingest' THEN 1 ELSE 0 END), 0),
          COALESCE(SUM(tokens_in + tokens_out), 0)
        FROM api_usage
        WHERE client_ip = ? AND date(created_at) = date('now')
        """,
        (client_ip,),
    ).fetchone()
    rpm = get_rpm(client_ip)
    return {"image_searches": row[0], "tracks_ingested": row[1], "tokens_used": row[2], "rpm": rpm}


def get_rpm(client_ip: str | None = None) -> int:
    """Count Gemini API calls made in the last 60 seconds (excludes marker operations)."""
    conn = get_conn()
    query = """
        SELECT COUNT(*) FROM api_usage
        WHERE model != ''
          AND created_at >= datetime('now', '-1 minute')
    """
    params: tuple = ()
    if client_ip:
        query += " AND client_ip = ?"
        params = (client_ip,)
    row = conn.execute(query, params).fetchone()
    return row[0]


def get_global_daily_usage() -> dict:
    conn = get_conn()
    row = conn.execute(
        """
        SELECT
          COALESCE(SUM(CASE WHEN operation = 'image_search' THEN 1 ELSE 0 END), 0),
          COALESCE(SUM(CASE WHEN operation = 'track_ingest' THEN 1 ELSE 0 END), 0),
          COALESCE(SUM(tokens_in + tokens_out), 0),
          COUNT(DISTINCT client_ip)
        FROM api_usage
        WHERE date(created_at) = date('now')
        """
    ).fetchone()
    return {
        "image_searches": row[0],
        "tracks_ingested": row[1],
        "tokens_used": row[2],
        "unique_ips": row[3],
        "rpm": get_rpm(),
    }


def get_ops_breakdown() -> list[dict]:
    """Per-operation token usage today, grouped by operation + model."""
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT operation, model,
               COUNT(*) as calls,
               COALESCE(SUM(tokens_in), 0)  as tokens_in,
               COALESCE(SUM(tokens_out), 0) as tokens_out
        FROM api_usage
        WHERE date(created_at) = date('now')
        GROUP BY operation, model
        ORDER BY (tokens_in + tokens_out) DESC
        """
    ).fetchall()
    return [
        {"operation": r[0], "model": r[1], "calls": r[2], "tokens_in": r[3], "tokens_out": r[4]}
        for r in rows
    ]


def get_hourly_usage(hours: int = 24) -> list[dict]:
    """Token totals and call count per hour for the last N hours."""
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT strftime('%Y-%m-%dT%H:00', created_at) as hour,
               COALESCE(SUM(tokens_in + tokens_out), 0) as tokens,
               COUNT(*) as calls
        FROM api_usage
        WHERE created_at >= datetime('now', ?)
        GROUP BY hour
        ORDER BY hour
        """,
        (f"-{hours} hours",),
    ).fetchall()
    return [{"hour": r[0], "tokens": r[1], "calls": r[2]} for r in rows]


def get_global_rpd() -> int:
    """Count of real Gemini API calls made globally today (RPD)."""
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) FROM api_usage WHERE model != '' AND date(created_at) = date('now')"
    ).fetchone()
    return row[0]


def get_global_tpm() -> int:
    """Total tokens consumed globally in the last 60 seconds (TPM)."""
    conn = get_conn()
    row = conn.execute(
        """
        SELECT COALESCE(SUM(tokens_in + tokens_out), 0)
        FROM api_usage
        WHERE model != '' AND created_at >= datetime('now', '-1 minute')
        """
    ).fetchone()
    return row[0]


def get_searches(limit: int = 20) -> list[dict]:
    conn = get_conn()
    searches = conn.execute(
        "SELECT id, description, image_data, created_at FROM searches ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()

    out = []
    for s in searches:
        rows = conn.execute(
            """
            SELECT sr.rank, sr.reason, sr.distance, t.id, t.name, t.author, t.url
            FROM search_results sr
            JOIN tracks t ON t.id = sr.track_id
            WHERE sr.search_id = ?
            ORDER BY sr.rank
            """,
            (s[0],),
        ).fetchall()
        out.append({
            "id": s[0],
            "description": s[1],
            "image_data": s[2],
            "created_at": s[3],
            "results": [
                {"rank": r[0], "reason": r[1], "distance": r[2], "id": r[3], "name": r[4], "author": r[5], "url": r[6]}
                for r in rows
            ],
        })
    return out
