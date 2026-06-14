# vibez

Cruza o **vibe visual** de uma imagem com o **vibe sonoro** de uma playlist do YouTube. Usa embeddings do Gemini + similaridade de cosseno para encontrar a música que mais combina com a foto.

---

## Arquitetura

Monorepo Bun com três workspaces:

```
vibez-back/      — Express API (auth, usuário, tracks — MongoDB Atlas, porta 3001)
vibez-front/     — Vite + React (porta 5173)
vibez_api/       — FastAPI Python (extrator de áudio + pipeline de IA, porta 8010)
```

### Fluxo geral

```
Browser
  ├── upload de imagem
  │     └── POST /image-embedding (vibez_api)
  │           ├── ADK: image_describer   → texto de humor/atmosfera
  │           ├── ADK: genre_extractor   → 1-3 gêneros musicais
  │           ├── Gemini embed_image     → vetor da imagem (768d)
  │           ├── Gemini embed_text      → vetor do texto de busca (768d)
  │           ├── sqlite-vec busca cosseno → top-10 candidatos
  │           └── ADK: track_reranker   → top-N rankeados com raciocínio
  │
  └── URL de playlist do YouTube
        └── POST /extract (vibez_api)
              ├── yt-dlp → IDs dos vídeos
              └── para cada track:
                    ├── ffmpeg → 3 chunks WAV de 15s (0:30 / 1:30 / 2:30)
                    ├── Essentia DSP → BPM, Key, Loudness
                    ├── EffNet-Discogs (TF) → mood, gênero, dançabilidade
                    └── Gemini embed_text → vetor (768d) → sqlite-vec
```

---

## Evolução da arquitetura de busca

O matching imagem × música passou por três abordagens antes de chegar na atual.

---

### v1 — Embedding direto: imagem × áudio

**Ideia:** embedar a imagem e embedar as features de áudio (BPM, key, loudness, mood) como texto, depois calcular similaridade de cosseno entre os dois vetores.

```
Imagem  ──► embed_image()  ──► vetor_img  [768d]
                                               │
                                          cosine_sim  ──► ranking
                                               │
Áudio   ──► features DSP
         → "BPM 128, Cm, loud -8db..."
         ──► embed_text()  ──► vetor_audio [768d]
```

**Problema:** o modelo gemini-embedding-2-preview não garante que embeddings
de imagem e de texto descritivo de áudio ocupem o mesmo espaço vetorial.
A similaridade de cosseno entre modalidades diferentes não tem significado
matemático consistente — os vetores simplesmente não são comparáveis.

---

### v2 — Ponte textual: descrição da imagem × descrição do áudio

**Ideia:** forçar as duas modalidades para o mesmo espaço passando tudo por
texto. O Gemini descreve a imagem em linguagem natural; o pipeline de áudio
monta uma descrição semântica do som. Ambos viram embeddings de texto e aí
sim a similaridade de cosseno é válida.

```
Imagem  ──► Gemini descreve ──► "atmosfera melancólica, azul, urbano..."
                                          │
                                     embed_text()  ──► vetor_img_desc [768d]
                                          │
                                     cosine_sim  ──► ranking
                                          │
Áudio   ──► Essentia + EffNet
         → "Eletrônico, BPM 128, Cm, energia alta, mood melancólico"
         ──► embed_text()  ──► vetor_audio_desc [768d]
```

**Melhoria:** os vetores agora vivem no mesmo espaço semântico — a comparação
é matematicamente válida.

**Problema:** a busca por cosseno ainda é limitada. O modelo de embedding não
entende que "fotografia de cidade neon" e "Dark Ambient eletrônico" são
compatíveis — mede só proximidade lexical no texto. Músicas com BPM parecido
rankeavam acima de músicas com o gênero correto.

---

### v3 — Arquitetura atual: busca vetorial + reranker multimodal (ADK)

**Ideia:** separar a busca em dois estágios. O primeiro usa cosseno para
recuperar candidatos plausíveis (recall). O segundo usa um LLM multimodal
que vê a imagem e lê as descrições dos candidatos para rankear por vibe
real (precision).

```
Imagem
  ├── ADK image_describer  ──► descrição em texto
  ├── ADK genre_extractor  ──► ["Electronic", "Hip-Hop"]
  ├── embed_image()        ──► vetor_img [768d]  ─┐
  └── embed_text(desc+genres)  ──► vetor_txt [768d]─┘
                                                    │
                              sqlite-vec cosine search
                                                    │
                                        top-10 candidatos
                                                    │
                              ADK track_reranker
                               ├── vê a imagem (multimodal)
                               ├── lê descrição de cada candidato
                               └── rankeia: gênero > energia > mood > textura
                                                    │
                                        top-N resultado final
                                        + razão por track (PT-BR)
```

**Por que funciona melhor:**
- A busca vetorial garante que os candidatos têm alguma relação semântica (recall rápido e barato)
- O reranker ADK usa o LLM com visão — ele olha para a foto e para a descrição de cada música antes de rankear
- Os critérios de prioridade são explícitos no prompt: gênero primeiro, depois energia, mood e textura

---

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Front-end | Vite + React + TypeScript |
| API | FastAPI + Python 3.10 |
| Agentes de IA | Google ADK 2.1 (LlmAgent) |
| LLM | gemini-3.1-flash-lite (descrever, gêneros, rerankear) |
| Embeddings | gemini-embedding-2-preview (imagem + texto, 768d) |
| Features de áudio | Essentia + EffNet-Discogs (TensorFlow) |
| Extração de áudio | yt-dlp + ffmpeg |
| Armazenamento vetorial | SQLite + sqlite-vec (cosseno, 768d) |

---

## Como rodar localmente

```bash
bun install   # da raiz do repo

# API Python
cd vibez_api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8010

# Front-end
cd vibez-front
bun run dev   # http://localhost:5173
```

### vibez_api/.env

```env
GEMINI_API_KEY=...
MODELS_PATH=/caminho/para/effnet_discogs.pb
FRONTEND_URL=http://localhost:5173
```

> **Setup completo dos modelos Essentia + TensorFlow:** download dos 9 `.pb`, estrutura de diretórios e variáveis de ambiente documentados em [`vibez_api/README.md`](./vibez_api/README.md).
