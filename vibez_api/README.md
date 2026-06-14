# vibez-api

FastAPI service for Vibez. It ingests YouTube playlist tracks, extracts audio vibe features, creates Gemini embeddings, stores vectors in SQLite (`sqlite-vec`), and matches songs to an uploaded image vibe.

## What this API does

- Extracts track IDs from a YouTube playlist
- Resolves each video audio stream with `yt-dlp`
- Samples 3 audio chunks with `ffmpeg`
- Extracts audio features with Essentia + TensorFlow models
- Builds a semantic text description of each track vibe
- Embeds descriptions and image vibes using Gemini
- Stores track vectors in SQLite + `sqlite-vec`
- Searches nearest tracks by cosine distance and reranks by vibe

## Endpoints

- `GET /health`
  - Returns `{ "status": "ok" }`0,

    

- `POST /extract`
  - Body: `{ "playlistUrl": "https://www.youtube.com/playlist?list=..." }`
  - Runs ingestion pipeline for all playlist tracks
  - Saves/updates tracks and embeddings in DB

- `POST /image-embedding`
  - Body: `{ "imageBase64": "data:image/jpeg;base64,...", "topN": 5 }`
  - Creates image + text embeddings from image vibe
  - Searches similar tracks from DB
  - Reranks top candidates using Gemini reasoning
  - Returns image description + ranked `searchResults`

## How to run

### 1) Prerequisites

- Python 3.10+
- `ffmpeg` installed and available in PATH
- Gemini API key
- Essentia/TensorFlow model files (`.pb`)

### 2) Install dependencies

From `vibez-api` folder:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3) Configure environment

Create `vibez-api/.env`:

```env
# Required
GEMINI_API_KEY=your_gemini_key
MODELS_PATH=/absolute/path/to/effnet_discogs.pb

# Optional (defaults shown)
FRONTEND_URL=http://localhost:3000
DB_PATH=vibez.db

# Optional extra Essentia classifiers (.pb)
DANCEABILITY_MODEL_PATH=
MOOD_HAPPY_MODEL_PATH=
MOOD_SAD_MODEL_PATH=
MOOD_AGGRESSIVE_MODEL_PATH=
MOOD_RELAXED_MODEL_PATH=
MOOD_ACOUSTIC_MODEL_PATH=
VOICE_INSTRUMENTAL_MODEL_PATH=
GENRE_MODEL_PATH=
```

Notes:
- `MODELS_PATH` must point to a single `.pb` file (or a directory containing exactly one `.pb`).
- If optional classifier paths are not set, the API uses heuristic fallbacks for some labels.

### 4) Start server

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8010
```

Health check:

```bash
curl http://localhost:8000/health
```

## How it works (pipeline)

### Ingestion (`POST /extract`)

1. API receives a YouTube playlist URL.
2. `yt-dlp` reads playlist entries and extracts video IDs.
3. For each video:
   - Resolve playable audio URL with fallback extractor options.
   - Download 3 short WAV chunks at different offsets using `ffmpeg`.
   - Extract features: BPM, key, loudness, mood/energy-like signals.
   - Build a semantic natural-language vibe description.
   - Generate text embedding with Gemini (`768` dimensions).
   - Upsert track metadata + vector into SQLite (`tracks` + `track_vectors`).
4. API returns per-track results (or per-track errors without stopping the whole batch).

### Search (`POST /image-embedding`)

1. API receives base64 image data URI and optional `topN`.
2. Gemini describes image mood in text.
3. API generates two embeddings:
   - Image embedding from raw image
   - Text embedding from generated image description
4. DB performs vector search for both embeddings and merges candidates by best distance.
5. Gemini reranks candidates by holistic vibe match (image mood vs track description).
6. API returns final ranked `searchResults` with reasoning.

## Data model (SQLite)

- `tracks`
  - `id`, `name`, `author`, `url` (unique), `description`
- `track_vectors` (`vec0` virtual table)
  - `embedding FLOAT[768]` with cosine distance
- `image_embeddings`
  - Stores image vectors (auxiliary)

## Troubleshooting

- `Could not resolve audio stream for this video`
  - Update `yt-dlp` and retry.

- `MODELS_PATH environment variable is not set` or model not found
  - Verify `.env` path and `.pb` file existence.

- `ffmpeg` command not found
  - Install `ffmpeg` system package and retry.

- CORS issues in front-end
  - Set `FRONTEND_URL` in `.env` to your front URL.
