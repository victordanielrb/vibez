import os
import sqlite3
import struct
import sqlite_vec

DB_PATH = os.getenv("DB_PATH", "vibez.db")

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
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tracks (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            name    TEXT NOT NULL,
            author  TEXT NOT NULL,
            url     TEXT NOT NULL UNIQUE
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS track_vectors USING vec0(
            embedding FLOAT[768] distance_metric=cosine
        );
        CREATE TABLE IF NOT EXISTS image_embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_embedding FLOAT[768]
        );

    """)
    conn.commit()


def _serialize(embedding: list[float]) -> bytes:
    return struct.pack(f"{len(embedding)}f", *embedding)


def insert_track(name: str, author: str, url: str, embedding: list[float]) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT OR IGNORE INTO tracks (name, author, url) VALUES (?, ?, ?)",
        (name, author, url),
    )
    conn.commit()

    track_id: int = cur.lastrowid or conn.execute(
        "SELECT id FROM tracks WHERE url = ?", (url,)
    ).fetchone()[0]

    conn.execute("DELETE FROM track_vectors WHERE rowid = ?", (track_id,))
    conn.execute(
        "INSERT INTO track_vectors (rowid, embedding) VALUES (?, ?)",
        (track_id, _serialize(embedding)),
    )
    conn.commit()
    return track_id

def insert_image_embedding(image_embedding: list[float]) -> int:
    conn = get_conn()
    conn.execute(
        "INSERT INTO image_embeddings (image_embedding) VALUES (?)",
        (_serialize(image_embedding),)
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def search_by_embeddings(img_embedding: list[float], txt_embedding: list[float], limit: int = 10) -> list[dict]:
    """Search with both image and description embeddings, merge by best distance per track."""
    img_results = {r["id"]: r for r in search_by_embedding(img_embedding, limit)}
    txt_results = {r["id"]: r for r in search_by_embedding(txt_embedding, limit)}

    merged: dict[int, dict] = {}
    for track_id, r in {**img_results, **txt_results}.items():
        if track_id in img_results and track_id in txt_results:
            merged[track_id] = {**r, "distance": min(img_results[track_id]["distance"], txt_results[track_id]["distance"])}
        else:
            merged[track_id] = r

    return sorted(merged.values(), key=lambda r: r["distance"])[:limit]


def search_by_embedding(embedding: list[float], limit: int = 10) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT t.id, t.name, t.author, t.url, v.distance
        FROM track_vectors v
        JOIN tracks t ON t.id = v.rowid
        WHERE v.embedding MATCH ?
          AND k = ?
        ORDER BY v.distance
        """,
        (_serialize(embedding), limit),
    ).fetchall()

    return [
        {"id": r[0], "name": r[1], "author": r[2], "url": r[3], "distance": r[4]}
        for r in rows
    ]
