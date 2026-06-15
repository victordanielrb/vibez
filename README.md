# vibez

Cruza o **vibe visual** de uma imagem com o **vibe sonoro** de uma playlist do YouTube. Usa embeddings do Gemini + busca vetorial por cosseno + reranker multimodal ADK para encontrar as músicas que mais combinam com a foto.

---

## Arquitetura

```
vibez/
├── vibez-front/     — Vite + React (porta 5173 / :80 via Docker)
├── vibez_api/       — FastAPI + ADK + Essentia/TF (porta 8010)
└── docker-compose.yml
```

### Fluxo de ingestão (assíncrono)

```
POST /extract {playlistUrl}
  └── yt-dlp → [(video_id, title, uploader), ...]
        └── BullMQ queue → worker Python (mesmo processo, asyncio)
              para cada track:
              ├── ffmpeg → 3 chunks WAV de 30s
              │     offsets: início+30s / meio / fim-30s
              ├── Essentia DSP → BPM, Key, Loudness por chunk
              ├── EffNet-Discogs (TF) → gênero, mood, energia, dançabilidade por chunk
              ├── features estruturados → track_chunks.features (JSON)
              └── Gemini embed_text → vetor 768d → sqlite-vec por chunk

Redis pub/sub (job:{id}) → SSE → browser (progresso em tempo real)
```

### Fluxo de busca por imagem

```
POST /image-embedding {imageBase64}
  ├── ADK image_describer  → descrição em texto (mood, atmosfera, cores)
  ├── ADK genre_extractor  → 1-3 gêneros musicais
  ├── Gemini embed_text    → vetor 768d (descrição + gêneros)
  ├── sqlite-vec cosine    → top candidatos (máx 2 chunks por track)
  └── ADK track_reranker
        ├── recebe a imagem (multimodal)
        ├── recebe features estruturados por chunk
        ├── tool disponível: AgentTool(image_describer)
        └── output: rank + reason + genre_fit + mood_fit + pace_fit
```

---

## Evolução da arquitetura

### v1 — Embedding imagem × áudio (cruzamento direto)

Embeds de imagem e de texto descritivo de áudio comparados por cosseno. O modelo Gemini não garante que vetores de modalidades diferentes ocupem o mesmo espaço — similaridade matematicamente inválida.

### v2 — Ponte textual: descrição imagem × descrição áudio

Ambas as modalidades passam por texto antes de virar embedding. A similaridade de cosseno passa a ser válida, mas ainda limitada à proximidade lexical — não entende coerência semântica entre vibe visual e sonora.

### v3 — Busca vetorial + reranker multimodal ADK

Dois estágios: cosseno para recall rápido, LLM multimodal para ranking preciso. O reranker vê a imagem e as descrições dos candidatos. Saída: razão em PT-BR por track.

### v4 — Features estruturados + AgentTool + dimensões de fit *(atual)*

- **Features por chunk:** BPM, key, loudness, energy, valence, danceability, texture, vocals, genres — estruturados em JSON por chunk, não como string raw
- **AgentTool:** `image_describer` vira tool disponível ao `track_reranker` para análise adicional da imagem sob demanda
- **Fit explícito:** output inclui `genre_fit`, `mood_fit`, `pace_fit` (`"alto" | "médio" | "baixo"`) por track
- **Zod no front:** `SearchResultSchema` valida o shape da resposta em runtime; badges coloridos exibem os 3 critérios de fit
- **Títulos reais:** `get_urls_from_playlist` extrai `title` e `uploader` do yt-dlp (não só o video_id)

---

## Como rodar

```bash
# 1. Redis (requerido para a fila BullMQ)
docker run -d --name vibez-redis -p 6379:6379 redis:7-alpine

# 2. Frontend
cd vibez-front && bun install && bun run dev   # http://localhost:5173

# 3. API
# veja vibez_api/README.md para setup completo (Python, modelos, .env)
```

> Setup completo da API: [`vibez_api/README.md`](./vibez_api/README.md).
