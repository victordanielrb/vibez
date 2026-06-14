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

## Instalação completa

### 1. Pré-requisitos de sistema

```bash
# Ubuntu / Debian
sudo apt update
sudo apt install -y ffmpeg python3.10 python3.10-venv python3-pip

# macOS (Homebrew)
brew install ffmpeg python@3.10

# Verificar
ffmpeg -version
python3.10 --version
```

> **yt-dlp** é instalado via `pip` junto com as dependências. Se começar a falhar na extração de áudio (quebra com frequência por mudanças no YouTube), atualize com `pip install -U yt-dlp`.

---

### 2. Ambiente Python + dependências

```bash
cd vibez_api
python3.10 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

O `requirements.txt` instala, entre outros:
- `essentia==2.1b6.dev1389` — biblioteca de análise de áudio (bindings Python do C++)
- `tensorflow==2.16.1` — runtime para inferência dos modelos `.pb`
- `google-adk>=2.1.0` — agentes LLM
- `sqlite-vec` — busca vetorial

> **Nota sobre Essentia:** em algumas distros Linux pode ser necessário instalar `libsoundfile1` e `libavcodec-dev` antes do pip install.
> ```bash
> sudo apt install -y libsndfile1 libavcodec-dev libavformat-dev
> ```

---

### 3. Modelos Essentia + TensorFlow

O pipeline usa **9 modelos** pré-treinados da biblioteca [Essentia Models](https://essentia.upf.edu/models/). Todos são arquivos `.pb` (TensorFlow SavedModel/frozen graph).

#### Estrutura esperada de diretórios

```
~/models/
├── effnet-discogs/
│   └── discogs-effnet-bs64-1.pb          ← backbone obrigatório
└── classifiers/
    ├── danceability-discogs-effnet-1.pb
    ├── mood_happy-discogs-effnet-1.pb
    ├── mood_sad-discogs-effnet-1.pb
    ├── mood_aggressive-discogs-effnet-1.pb
    ├── mood_relaxed-discogs-effnet-1.pb
    ├── mood_acoustic-discogs-effnet-1.pb
    ├── voice_instrumental-discogs-effnet-1.pb
    ├── genre_discogs400-discogs-effnet-1.pb
    └── genre_discogs400-discogs-effnet-1.json  ← labels do gênero
```

#### Script de download (todos de uma vez)

```bash
mkdir -p ~/models/effnet-discogs ~/models/classifiers

BASE="https://essentia.upf.edu/models"

# Backbone — obrigatório
curl -L "$BASE/feature-extractors/discogs-effnet/discogs-effnet-bs64-1.pb" \
  -o ~/models/effnet-discogs/discogs-effnet-bs64-1.pb

# Classifiers — opcionais (fallback heurístico se ausentes)
for MODEL in \
  danceability-discogs-effnet-1 \
  mood_happy-discogs-effnet-1 \
  mood_sad-discogs-effnet-1 \
  mood_aggressive-discogs-effnet-1 \
  mood_relaxed-discogs-effnet-1 \
  mood_acoustic-discogs-effnet-1 \
  voice_instrumental-discogs-effnet-1; do
  curl -L "$BASE/classifiers/$MODEL/$MODEL.pb" \
    -o ~/models/classifiers/$MODEL.pb
done

# Gênero + arquivo de labels JSON
curl -L "$BASE/classifiers/genre_discogs400-discogs-effnet-1/genre_discogs400-discogs-effnet-1.pb" \
  -o ~/models/classifiers/genre_discogs400-discogs-effnet-1.pb
curl -L "$BASE/classifiers/genre_discogs400-discogs-effnet-1/genre_discogs400-discogs-effnet-1.json" \
  -o ~/models/classifiers/genre_discogs400-discogs-effnet-1.json
```

> Os modelos têm entre 3 MB e 150 MB cada. O backbone `discogs-effnet-bs64-1.pb` pesa ~150 MB e é o único obrigatório.

#### O que cada modelo faz

| Modelo | Tipo | Saída | Obrigatório |
|--------|------|-------|-------------|
| `discogs-effnet-bs64-1` | Backbone embedder | Embedding 512d por chunk de áudio | **Sim** |
| `danceability-discogs-effnet-1` | Classifier 2 classes | Probabilidade de dançabilidade | Não |
| `mood_happy-discogs-effnet-1` | Classifier 2 classes | P(happy) | Não |
| `mood_sad-discogs-effnet-1` | Classifier 2 classes | P(sad) | Não |
| `mood_aggressive-discogs-effnet-1` | Classifier 2 classes | P(aggressive) | Não |
| `mood_relaxed-discogs-effnet-1` | Classifier 2 classes | P(relaxed) | Não |
| `mood_acoustic-discogs-effnet-1` | Classifier 2 classes | P(acústico vs eletrônico) | Não |
| `voice_instrumental-discogs-effnet-1` | Classifier 2 classes | P(vocal vs instrumental) | Não |
| `genre_discogs400-discogs-effnet-1` | Classifier 400 classes | Top-3 gêneros Discogs | Não |

> Os classifiers opcionais recebem o embedding do backbone como entrada (`TensorflowPredict2D`). Se ausentes, o pipeline usa heurísticas baseadas em BPM e loudness para estimar danceability, energy e valence.

#### Como o pipeline usa os modelos em cadeia

```
Chunk WAV (16kHz mono)
  └── Essentia DSP:
        ├── MonoLoader     → array de floats
        ├── RhythmExtractor2013 → BPM
        ├── KeyExtractor   → Tom + escala
        └── LoudnessEBUR128 → dB LUFS

  └── EffNet-Discogs backbone:
        └── TensorflowPredictEffnetDiscogs → embedding 512d por chunk

  └── Classifiers (recebem o embedding 512d como entrada):
        ├── danceability    → P(dançável)
        ├── mood_happy/sad/aggressive/relaxed → valence + energy
        ├── mood_acoustic   → acústico vs eletrônico
        ├── voice_instrumental → vocal vs instrumental
        └── genre_discogs400 → top-3 de 400 gêneros Discogs
```

---

### 4. Variáveis de ambiente

Crie o arquivo `vibez_api/.env`:

```env
# Obrigatório
GEMINI_API_KEY=sua_chave_gemini

# Caminho do backbone — obrigatório
# Padrão: ~/models/effnet-discogs/discogs-effnet-bs64-1.pb
MODELS_PATH=~/models/effnet-discogs/discogs-effnet-bs64-1.pb

# Classifiers — opcional (padrão: ~/models/classifiers/<nome>.pb)
DANCEABILITY_MODEL_PATH=~/models/classifiers/danceability-discogs-effnet-1.pb
MOOD_HAPPY_MODEL_PATH=~/models/classifiers/mood_happy-discogs-effnet-1.pb
MOOD_SAD_MODEL_PATH=~/models/classifiers/mood_sad-discogs-effnet-1.pb
MOOD_AGGRESSIVE_MODEL_PATH=~/models/classifiers/mood_aggressive-discogs-effnet-1.pb
MOOD_RELAXED_MODEL_PATH=~/models/classifiers/mood_relaxed-discogs-effnet-1.pb
MOOD_ACOUSTIC_MODEL_PATH=~/models/classifiers/mood_acoustic-discogs-effnet-1.pb
VOICE_INSTRUMENTAL_MODEL_PATH=~/models/classifiers/voice_instrumental-discogs-effnet-1.pb
GENRE_MODEL_PATH=~/models/classifiers/genre_discogs400-discogs-effnet-1.pb

# Servidor
FRONTEND_URL=http://localhost:5173
DB_PATH=vibez.db
```

> Se os classifiers opcionais estiverem na estrutura padrão `~/models/classifiers/`, **não precisa definir as variáveis** — o código resolve automaticamente.

---

### 5. Iniciar o servidor

```bash
source .venv/bin/activate
uvicorn app:app --reload --port 8010
```

Na inicialização, o log deve mostrar algo como:

```
INFO  models loaded: ['effnet', 'danceability', 'mood_happy', 'mood_sad',
      'mood_aggressive', 'mood_relaxed', 'mood_acoustic', 'voice_instrumental',
      'genre', 'loader', 'rhythm', 'key', 'stereo', 'loudness']
```

Se algum classifier estiver faltando, aparece `WARNING model MISSING: <nome> — falling back to heuristic`.

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

## Troubleshooting

| Erro | Solução |
|------|---------|
| `EffNet-Discogs model not found` | Rode o script de download da seção 3 |
| `Could not resolve audio stream` | Rode `pip install -U yt-dlp` |
| `ffmpeg not found` | Instale o pacote `ffmpeg` do sistema |
| Erros de CORS no front-end | Defina `FRONTEND_URL` no `.env` |
| `TF_CPP_MIN_LOG_LEVEL` spam no terminal | Já suprimido no código; se persistir, exporte `TF_CPP_MIN_LOG_LEVEL=3` no shell |
| Crash na carga do modelo TF | Confirme `tensorflow==2.16.1` — versões diferentes têm grafos incompatíveis com o Essentia |
