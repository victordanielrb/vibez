# vibez_api

Serviço FastAPI que executa o pipeline de IA do vibez — ingere playlists do YouTube, extrai features de áudio por chunk, gera embeddings com Gemini e faz o match de tracks com uma imagem por vibe.

---

## Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/health` | Liveness check |
| POST | `/extract` | Ingere uma playlist (assíncrono, retorna jobId) |
| GET | `/jobs` | Lista todos os jobs de ingestão |
| GET | `/jobs/{jobId}` | Status de um job específico |
| GET | `/jobs/{jobId}/stream` | SSE — progresso em tempo real |
| POST | `/image-embedding` | Match imagem × tracks (global ou filtrado por playlist) |
| GET | `/searches` | Histórico de buscas recentes |
| GET | `/quota` | Uso diário por IP |
| GET | `/quota/global` | Uso global da API Gemini |
| GET | `/metrics/ops` | Breakdown de operações e tokens |
| GET | `/otel-metrics` | Métricas Prometheus (formato text) |

---

## Pipelines

### Ingestão (`POST /extract`)

```
playlistUrl
  └── yt-dlp → [(video_id, title, uploader), ...]
        └── BullMQ worker (asyncio, mesmo processo):
              para cada track:
              ├── rate limit check (TRACK_INGEST_LIMIT por IP/dia)
              ├── ffmpeg → 3 chunks WAV de 30s
              │     offsets: início+30s / meio / fim-30s
              ├── Essentia DSP → BPM, Key, Loudness por chunk
              ├── EffNet-Discogs (TF) → mood, gênero, dançabilidade, energy por chunk
              ├── track_chunks.features ← JSON estruturado por chunk
              └── Gemini embed_text → vetor 768d → sqlite-vec (por chunk)
```

### Busca por imagem (`POST /image-embedding`)

```
imageBase64 + topN + playlistScopeJobId?
  ├── ADK image_describer  → texto de humor/atmosfera (PT-BR)
  ├── ADK genre_extractor  → 1-3 gêneros
  ├── Gemini embed_text    → vetor 768d (descrição + gêneros)
  ├── sqlite-vec cosine    → top candidatos (máx 2 chunks por track)
  └── ADK track_reranker
        ├── vê a imagem (multimodal)
        ├── recebe features estruturados por chunk (bpm, key, energy, mood, genres…)
        ├── tool: AgentTool(image_describer) — análise adicional sob demanda
        └── output por track: {rank, reason, genre_fit, mood_fit, pace_fit}
```

Quando `playlistScopeJobId` é enviado, a busca vetorial é filtrada para tracks ingeridas naquele `jobId`. Sem esse campo, a busca continua global.

---

## Camada de IA — Google ADK

Agentes `LlmAgent` singleton com `gemini-3.1-flash-lite`, todos com output em PT-BR:

| Agente | Tipo de saída | Observação |
|--------|--------------|------------|
| `image_describer` | texto livre | mood, atmosfera, cores, energia — também usado como `AgentTool` |
| `genre_extractor` | `{"genres": [...]}` | output estruturado via `output_schema` |
| `track_reranker` | `{"rankings": [...]}` | recebe imagem + features; output inclui `genre_fit/mood_fit/pace_fit` |

### Output do reranker por track

```json
{
  "id": 1,
  "rank": 1,
  "reason": "O BPM animado e a textura eletrônica combinam com a agitação urbana da imagem.",
  "genre_fit": "alto",
  "mood_fit": "médio",
  "pace_fit": "alto"
}
```

`"alto" | "médio" | "baixo"` — validados com `Literal` no Pydantic e `z.enum` no frontend.

### AgentTool

`image_describer` é encapsulado como `AgentTool` e injetado em `track_reranker.tools`. O reranker pode invocá-lo durante o raciocínio para obter análise adicional da imagem. A `description` já computada no pipeline é passada no `user_text` para evitar chamada dupla na maioria dos casos.

---

## Jobs — ingestão assíncrona

```
POST /extract {playlistUrl}  →  {jobId, status: "queued"}
                                      │
                          BullMQ (Python Worker + Redis)
                           publica em canal job:{jobId}
                                      │
GET /jobs/{jobId}/stream  ←──── SSE (FastAPI, redis pub/sub)
```

### Eventos SSE

| `type` | campos extras | descrição |
|--------|--------------|-----------|
| `start` | `total` | job iniciou |
| `progress` | `processed`, `total`, `track` | track salva com sucesso |
| `track_error` | `processed`, `total`, `error` | track pulada |
| `done` | `processed`, `total` | concluído |
| `error` | `error` | falha geral |

### Webhook opcional

`POST /extract` aceita `callbackUrl`. Ao terminar, o servidor faz POST para essa URL:

```json
{"jobId": "...", "status": "done", "processed": 12, "total": 12, "error": null}
```

---

## Modelo de dados (SQLite + sqlite-vec)

| Tabela | Colunas principais |
|--------|--------------------|
| `tracks` | id, name, author, url (unique), description, source_job_id |
| `track_chunks` | id, track_id, offset (s), description, features (JSON) |
| `track_vectors` | virtual vec0 — `embedding FLOAT[768]` cosseno; rowid = track_chunks.id |
| `jobs` | id, playlist_url, status, processed, total, callback_url |
| `searches` | id, image_data, description, created_at |
| `search_results` | search_id, track_id, rank, reason, distance |
| `usage_log` | client_ip, operation, model, tokens_in, tokens_out, created_at |

`track_chunks.features` — JSON por chunk:

```json
{
  "bpm": 117, "key": "F#", "scale": "minor", "loudness_db": -19.1,
  "energy": 0.43, "valence": 0.75, "danceability": 0.52,
  "acoustic": 0.64, "voice": 0.04,
  "genres": ["Ambient (Electronic)", "Dark Ambient (Electronic)"]
}
```

---

## Instalação local

### 1. Pré-requisitos de sistema

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y ffmpeg python3.10 python3.10-venv libsndfile1

# macOS
brew install ffmpeg python@3.10
```

### 2. Redis (requerido para BullMQ)

```bash
docker run -d --name vibez-redis -p 6379:6379 redis:7-alpine
```

### 3. Ambiente Python

```bash
cd vibez_api
python3.10 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Modelos Essentia + TensorFlow

9 modelos pré-treinados da [Essentia Models Library](https://essentia.upf.edu/models/):

```
~/models/
├── effnet-discogs/
│   └── discogs-effnet-bs64-1.pb          ← backbone obrigatório (~150 MB)
└── classifiers/
    ├── danceability-discogs-effnet-1.pb
    ├── mood_happy-discogs-effnet-1.pb
    ├── mood_sad-discogs-effnet-1.pb
    ├── mood_aggressive-discogs-effnet-1.pb
    ├── mood_relaxed-discogs-effnet-1.pb
    ├── mood_acoustic-discogs-effnet-1.pb
    ├── voice_instrumental-discogs-effnet-1.pb
    ├── genre_discogs400-discogs-effnet-1.pb
    └── genre_discogs400-discogs-effnet-1.json
```

Script de download:

```bash
mkdir -p ~/models/effnet-discogs ~/models/classifiers
BASE="https://essentia.upf.edu/models"

curl -L "$BASE/feature-extractors/discogs-effnet/discogs-effnet-bs64-1.pb" \
  -o ~/models/effnet-discogs/discogs-effnet-bs64-1.pb

for M in danceability mood_happy mood_sad mood_aggressive mood_relaxed mood_acoustic voice_instrumental; do
  curl -L "$BASE/classifiers/${M}-discogs-effnet-1/${M}-discogs-effnet-1.pb" \
    -o ~/models/classifiers/${M}-discogs-effnet-1.pb
done

curl -L "$BASE/classifiers/genre_discogs400-discogs-effnet-1/genre_discogs400-discogs-effnet-1.pb" \
  -o ~/models/classifiers/genre_discogs400-discogs-effnet-1.pb
curl -L "$BASE/classifiers/genre_discogs400-discogs-effnet-1/genre_discogs400-discogs-effnet-1.json" \
  -o ~/models/classifiers/genre_discogs400-discogs-effnet-1.json
```

| Modelo | Saída | Obrigatório |
|--------|-------|-------------|
| `discogs-effnet-bs64-1` | Embedding 512d | **Sim** |
| `danceability-discogs-effnet-1` | P(dançável) | Não |
| `mood_*-discogs-effnet-1` | valence + energy | Não |
| `mood_acoustic-discogs-effnet-1` | acústico vs eletrônico | Não |
| `voice_instrumental-discogs-effnet-1` | vocal vs instrumental | Não |
| `genre_discogs400-discogs-effnet-1` | top-3 de 400 gêneros | Não |

> Se os classifiers estiverem ausentes, o pipeline usa heurísticas (BPM + loudness). Log indicará `WARNING model MISSING: <nome> — falling back to heuristic`.

### 5. Variáveis de ambiente

Arquivo `vibez_api/.env`:

```env
# Obrigatório
GOOGLE_API_KEY=sua_chave_aqui

# Redis (padrão: localhost:6379)
REDIS_HOST=localhost
REDIS_PORT=6379
# REDIS_PASSWORD=

# Limites
TRACK_INGEST_LIMIT=1000
FRONTEND_URL=http://localhost:5173
```

### 6. Iniciar

```bash
source .venv/bin/activate
REDIS_PORT=6379 uvicorn app:app --reload --port 8010
```

Log esperado na inicialização:
```
INFO  models loaded: ['effnet', 'danceability', 'mood_happy', ...]
INFO  BullMQ worker started
```

---

## Troubleshooting

| Erro | Solução |
|------|---------|
| `EffNet-Discogs model not found` | Rode o script de download da seção 4 |
| `Could not resolve audio stream` | `pip install -U yt-dlp` |
| `ffmpeg not found` | Instale o pacote `ffmpeg` do sistema |
| Worker não processa jobs | Verificar Redis rodando; conferir `REDIS_HOST`/`REDIS_PORT` |
| Tracks com ID como nome | Executar migração via `get_urls_from_playlist` (já corrigido na v4.2) |
| Crash na carga do modelo TF | Confirmar `tensorflow==2.16.1` |
