# vibez_api

Serviço FastAPI que executa o pipeline de IA do vibez — ingere playlists do YouTube, extrai features de áudio, gera embeddings com Gemini e faz o match de tracks com uma imagem por vibe.

---

## Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/health` | Liveness check |
| POST | `/extract` | Ingere uma playlist do YouTube (assíncrono, retorna jobId) |
| GET | `/jobs` | Lista todos os jobs de ingestão |
| GET | `/jobs/{jobId}` | Status de um job específico |
| POST | `/image-embedding` | Faz o match de uma imagem com tracks (pipeline completo) |
| GET | `/searches` | Histórico de buscas recentes |

---

## Pipelines

### Ingestão (`POST /extract`)

```
playlistUrl
  └── yt-dlp → IDs dos vídeos
        └── para cada vídeo (thread em background):
              ├── ffmpeg → 3 chunks WAV de 15s em 0:30 / 1:30 / 2:30
              ├── Essentia DSP → BPM, Key, Loudness
              ├── EffNet-Discogs (TF, carregado uma vez no startup) → mood, gênero, dançabilidade
              ├── monta string descritiva semântica
              └── Gemini embed_text → vetor 768d → upsert no sqlite-vec
```

Vídeos indisponíveis são pulados com entrada de erro; o restante da playlist continua.

### Busca por imagem (`POST /image-embedding`)

```
imageBase64 + topN
  ├── ADK image_describer  → texto de humor/atmosfera (gemini-3.1-flash-lite)
  ├── ADK genre_extractor  → 1-3 gêneros (output estruturado)
  ├── Gemini embed_image   → vetor da imagem 768d
  ├── Gemini embed_text    → vetor da descrição+gêneros 768d
  ├── sqlite-vec busca cosseno → top-10 candidatos
  └── ADK track_reranker  → top-N rankeados com raciocínio por track (PT-BR)
```

---

## Camada de IA — Google ADK

As chamadas de geração usam **Google ADK 2.1** `LlmAgent` singletons, todos rodando com `gemini-3.1-flash-lite`:

| Agente | Saída | Observação |
|--------|-------|-----------|
| `image_describer` | texto livre | humor, atmosfera, cores, energia |
| `genre_extractor` | `{"genres": [...]}` | output estruturado via `output_schema` |
| `track_reranker` | `{"rankings": [...]}` | estruturado, prioridade: gênero > energia > mood > textura |

Os embeddings usam o SDK `google-genai` diretamente (`gemini-embedding-2-preview`, 768d) — o ADK não tem equivalente de `embed_content`.

---

## Modelo de dados (SQLite)

| Tabela | Colunas principais |
|--------|--------------------|
| `tracks` | id, name, author, url (unique), description |
| `track_vectors` | tabela virtual vec0 — `embedding FLOAT[768]` cosseno |
| `jobs` | id, playlist_url, status, processed, total |
| `searches` | id, image_data, description, created_at |
| `search_results` | search_id, track_id, rank, reason, distance |

---

## Setup

### Pré-requisitos

- Python 3.10+
- `ffmpeg` no PATH
- Chave da API do Gemini
- Arquivo de modelo EffNet-Discogs (`.pb`) — [Essentia models](https://essentia.upf.edu/models/)

### Instalação

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### `.env`

```env
GEMINI_API_KEY=sua_chave
MODELS_PATH=/caminho/absoluto/para/effnet_discogs.pb
FRONTEND_URL=http://localhost:5173
DB_PATH=vibez.db
```

### Iniciar

```bash
uvicorn app:app --reload --port 8010
```

---

## Troubleshooting

| Erro | Solução |
|------|---------|
| `Could not resolve audio stream` | Rode `pip install -U yt-dlp` |
| `MODELS_PATH not set` | Defina o caminho para o `.pb` no `.env` |
| `ffmpeg not found` | Instale o pacote `ffmpeg` do sistema |
| Erros de CORS no front-end | Defina `FRONTEND_URL` no `.env` |
