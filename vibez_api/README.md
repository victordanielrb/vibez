# vibez_api

FastAPI service that powers the vibez AI pipeline — ingests YouTube playlists, extracts audio features, generates Gemini embeddings, and matches tracks to an uploaded image by vibe.

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness check |
| POST | `/extract` | Ingest a YouTube playlist (async, returns jobId) |
| GET | `/jobs` | List all ingest jobs |
| GET | `/jobs/{jobId}` | Status of a specific job |
| POST | `/image-embedding` | Match an image to tracks (full AI pipeline) |
| GET | `/searches` | Recent search history |

---

## Pipelines

### Ingest (`POST /extract`)

```
playlistUrl
  └── yt-dlp → video IDs
        └── for each video (background thread):
              ├── ffmpeg → 3 × 15s WAV chunks at 0:30 / 1:30 / 2:30
              ├── Essentia DSP → BPM, Key, Loudness
              ├── EffNet-Discogs (TF, loaded once at startup) → mood, genre, danceability
              ├── build semantic description string
              └── Gemini embed_text → 768d vector → upsert into sqlite-vec
```

Unavailable videos are skipped with an error entry; the rest of the playlist continues.

### Image search (`POST /image-embedding`)

```
imageBase64 + topN
  ├── ADK image_describer  → mood/atmosphere text (gemini-3.1-flash-lite)
  ├── ADK genre_extractor  → 1-3 genre labels (structured output)
  ├── Gemini embed_image   → image vector 768d
  ├── Gemini embed_text    → description+genres vector 768d
  ├── sqlite-vec cosine search → top-10 candidates
  └── ADK track_reranker  → ranked top-N with per-track reasoning (PT-BR)
```

---

## AI layer — Google ADK

Generation calls use **Google ADK 2.1** `LlmAgent` singletons, all backed by `gemini-3.1-flash-lite`:

| Agent | Output | Notes |
|-------|--------|-------|
| `image_describer` | free text | mood, atmosphere, colors, energy |
| `genre_extractor` | `{"genres": [...]}` | structured via `output_schema` |
| `track_reranker` | `{"rankings": [...]}` | structured, genre-first priority |

Embeddings use the raw `google-genai` SDK (`gemini-embedding-2-preview`, 768d) — ADK has no `embed_content` equivalent.

---

## Data model (SQLite)

| Table | Key columns |
|-------|-------------|
| `tracks` | id, name, author, url (unique), description |
| `track_vectors` | vec0 virtual table — `embedding FLOAT[768]` cosine |
| `jobs` | id, playlist_url, status, processed, total |
| `searches` | id, image_data, description, created_at |
| `search_results` | search_id, track_id, rank, reason, distance |

---

## Setup

### Prerequisites

- Python 3.10+
- `ffmpeg` in PATH
- Gemini API key
- EffNet-Discogs model file (`.pb`) from [Essentia models](https://essentia.upf.edu/models/)

### Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### `.env`

```env
GEMINI_API_KEY=your_key
MODELS_PATH=/absolute/path/to/effnet_discogs.pb
FRONTEND_URL=http://localhost:5173
DB_PATH=vibez.db
```

### Start

```bash
uvicorn app:app --reload --port 8010
```

---

## Troubleshooting

| Error | Fix |
|-------|-----|
| `Could not resolve audio stream` | Run `pip install -U yt-dlp` |
| `MODELS_PATH not set` | Set path to `.pb` file in `.env` |
| `ffmpeg not found` | Install system `ffmpeg` package |
| CORS errors from front-end | Set `FRONTEND_URL` in `.env` |
