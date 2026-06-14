import os
import logging
import yt_dlp
import subprocess
from urllib.parse import parse_qs, urlparse
from yt_dlp.utils import DownloadError

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

logger = logging.getLogger(__name__)

_models: dict = {}


def _normalize_video_id(video_ref: str) -> str:
    value = (video_ref or "").strip()
    if not value:
        raise RuntimeError("Invalid video identifier.")

    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlparse(value)
        host = parsed.netloc.lower()

        if host.endswith("youtu.be"):
            candidate = parsed.path.strip("/").split("/")[0]
            if candidate:
                return candidate

        if "youtube.com" in host:
            query_id = parse_qs(parsed.query).get("v", [""])[0].strip()
            if query_id:
                return query_id
            if parsed.path.startswith("/shorts/"):
                candidate = parsed.path.split("/shorts/", 1)[1].split("/")[0]
                if candidate:
                    return candidate

    return value


_MODELS_DIR = os.path.expanduser("~/models")
_DEFAULT_MODELS = {
    "MODELS_PATH":                os.path.join(_MODELS_DIR, "effnet-discogs/discogs-effnet-bs64-1.pb"),
    "DANCEABILITY_MODEL_PATH":    os.path.join(_MODELS_DIR, "classifiers/danceability-discogs-effnet-1.pb"),
    "MOOD_HAPPY_MODEL_PATH":      os.path.join(_MODELS_DIR, "classifiers/mood_happy-discogs-effnet-1.pb"),
    "MOOD_SAD_MODEL_PATH":        os.path.join(_MODELS_DIR, "classifiers/mood_sad-discogs-effnet-1.pb"),
    "MOOD_AGGRESSIVE_MODEL_PATH": os.path.join(_MODELS_DIR, "classifiers/mood_aggressive-discogs-effnet-1.pb"),
    "MOOD_RELAXED_MODEL_PATH":    os.path.join(_MODELS_DIR, "classifiers/mood_relaxed-discogs-effnet-1.pb"),
    "MOOD_ACOUSTIC_MODEL_PATH":   os.path.join(_MODELS_DIR, "classifiers/mood_acoustic-discogs-effnet-1.pb"),
    "VOICE_INSTRUMENTAL_MODEL_PATH": os.path.join(_MODELS_DIR, "classifiers/voice_instrumental-discogs-effnet-1.pb"),
    "GENRE_MODEL_PATH":           os.path.join(_MODELS_DIR, "classifiers/genre_discogs400-discogs-effnet-1.pb"),
}


def _resolve_pb(env_var: str) -> str | None:
    """Returns model path from env var if set, otherwise falls back to _DEFAULT_MODELS."""
    path = os.path.expanduser(os.getenv(env_var, "")).strip() or _DEFAULT_MODELS.get(env_var, "")
    return path if os.path.isfile(path) else None


def _load_predict2d(es, path: str):
    for input_node, output_node in [
        ("model/Placeholder", "model/Softmax"),
        ("serving_default_model_Placeholder", "PartitionedCall"),
    ]:
        try:
            return es.TensorflowPredict2D(graphFilename=path, input=input_node, output=output_node)
        except Exception:
            continue
    raise RuntimeError(f"Could not load classifier model (unknown graph format): {path}")


def _load_models() -> dict:
    global _models
    if _models:
        return _models

    import essentia.standard as es

    effnet_path = _resolve_pb("MODELS_PATH")
    if not effnet_path:
        raise RuntimeError("EffNet-Discogs model not found. Set MODELS_PATH or place model at ~/models/effnet-discogs/discogs-effnet-bs64-1.pb")
    logger.debug("loading effnet from %s", effnet_path)
    _models["effnet"] = es.TensorflowPredictEffnetDiscogs(
        graphFilename=effnet_path,
        output="PartitionedCall:1",
    )

    for key, env_var in [
        ("danceability",       "DANCEABILITY_MODEL_PATH"),
        ("mood_happy",         "MOOD_HAPPY_MODEL_PATH"),
        ("mood_sad",           "MOOD_SAD_MODEL_PATH"),
        ("mood_aggressive",    "MOOD_AGGRESSIVE_MODEL_PATH"),
        ("mood_relaxed",       "MOOD_RELAXED_MODEL_PATH"),
        ("mood_acoustic",      "MOOD_ACOUSTIC_MODEL_PATH"),
        ("voice_instrumental", "VOICE_INSTRUMENTAL_MODEL_PATH"),
    ]:
        path = _resolve_pb(env_var)
        if path:
            logger.debug("loading %s from %s", key, path)
            _models[key] = _load_predict2d(es, path)
        else:
            logger.warning("model MISSING: %s (%s not set) — falling back to heuristic", key, env_var)

    genre_path = _resolve_pb("GENRE_MODEL_PATH")
    if genre_path:
        logger.debug("loading genre from %s", genre_path)
        _models["genre"] = _load_predict2d(es, genre_path)
        labels_path = os.path.splitext(genre_path)[0] + ".json"
        if os.path.isfile(labels_path):
            import json
            with open(labels_path) as f:
                data = json.load(f)
            # Essentia JSON format: {"classes": [...], ...} or bare list
            _models["genre_labels"] = data["classes"] if isinstance(data, dict) and "classes" in data else data
            logger.debug("genre labels loaded (%d classes)", len(_models["genre_labels"]))
    else:
        logger.warning("genre model MISSING — genre will be omitted from description")

    # DSP algorithms — instantiated once, reused via .configure()
    _models["loader"]     = es.MonoLoader(sampleRate=16000)
    _models["rhythm"]     = es.RhythmExtractor2013(method="multifeature")
    _models["key"]        = es.KeyExtractor()
    _models["stereo"]     = es.StereoMuxer()
    _models["loudness"]   = es.LoudnessEBUR128()

    loaded = [k for k in _models if k != "genre_labels"]
    logger.info("models loaded: %s", loaded)
    return _models


def get_audio_url(video_id: str) -> tuple[str, int]:
    video_id = _normalize_video_id(video_id)
    url = f"https://www.youtube.com/watch?v={video_id}"
    last_error = None
    option_variants = [
        {
            "js_runtimes": {"node": {}},
            "remote_components": "ejs:github",
            "cookiesfrombrowser": ("firefox",),
        },
        {
            "js_runtimes": {"node": {}},
            "remote_components": "ejs:github",
        },
        {},
    ]

    for fmt in ("bestaudio/best", "best"):
        for variant in option_variants:
            try:
                opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "format": fmt,
                    **variant,
                }
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    audio_url = info.get("url")
                    duration = info.get("duration")
                    if audio_url and duration:
                        return audio_url, duration
            except DownloadError as exc:
                last_error = exc
    raise RuntimeError("Could not resolve audio stream for this video.") from last_error

# Processa uma playlist pegando as URLs dos vídeos e extraindo os recursos de áudio de cada um, retornando uma lista de dicionários com as características de cada música.
# Definitivamente não é eficiente O(n), mas é simples e funciona para proof of concept.
def _normalize_playlist_url(url: str) -> str:
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url.lstrip("/")
    return url


def get_urls_from_playlist(playlist_url: str) -> list[str]:
    playlist_url = _normalize_playlist_url(playlist_url)
    videoUrlList = []
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "extractor_args": {"youtubetab": {"skip": ["authcheck"]}},
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(playlist_url, download=False)
        if "entries" in info:
            for entry in info["entries"]:
                if "url" in entry:
                    videoUrlList.append(_normalize_video_id(entry["url"]))
    return videoUrlList

#Download de trechos , um no começo, um no meio e um no final do áudio, para que um trecho defina a mood inteira da música
def download_audio_chunks(url: str, duration: int) -> list[tuple[int, bytes]]:
    offsets = [30, duration // 2, max(30, duration - 30)]
    chunks = []
    for offset in offsets:
        result = subprocess.run(
            ["ffmpeg", "-y", "-ss", str(offset), "-t", "30", "-i", url,
             "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        chunks.append((offset, result.stdout))
    return chunks


def _write_tmp_wav(chunk: bytes) -> str:
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(chunk)
        return f.name

#Utiliza os modelos prontos da biblioteca Essentia para extrair características de áudio como BPM, key, loudness, danceability, valence e energy.
#O Embedding desses modelos é utilizado pra pegar outros dados extras como gênero, acústico/eletrônico e vocal/instrumental, utilizando os modelos extras.
def extract_audio_features(audio_chunks: list[tuple[int, bytes]]) -> list[dict]:
    import numpy as np

    models = _load_models()
    results = []

    for offset, chunk_bytes in audio_chunks:
        wav_path = _write_tmp_wav(chunk_bytes)
        try:
            models["loader"].configure(filename=wav_path)
            audio = models["loader"]()
            bpm, *_ = models["rhythm"](audio)
            key, scale, _ = models["key"](audio)
            stereo = models["stereo"](audio, audio)
            _, _, loudness, _ = models["loudness"](stereo)

            embedding = models["effnet"](audio)

            bpm_f = float(bpm)
            loudness_f = float(loudness)

            if "danceability" in models:
                danceability = float(np.mean(models["danceability"](embedding)[:, 1]))
            else:
                danceability = max(0.0, min(1.0,
                    ((bpm_f - 70.0) / 90.0) * 0.65 + ((loudness_f + 30.0) / 25.0) * 0.35))

            mood_keys = {"mood_happy", "mood_sad", "mood_aggressive", "mood_relaxed"}
            if mood_keys.issubset(models):
                p_happy      = float(np.mean(models["mood_happy"](embedding)[:, 1]))
                p_sad        = float(np.mean(models["mood_sad"](embedding)[:, 1]))
                p_aggressive = float(np.mean(models["mood_aggressive"](embedding)[:, 1]))
                p_relaxed    = float(np.mean(models["mood_relaxed"](embedding)[:, 1]))
                valence = max(0.0, min(1.0, (p_happy - p_sad + 1) / 2))
                energy  = max(0.0, min(1.0, (p_aggressive - p_relaxed + 1) / 2))
            else:
                energy  = max(0.0, min(1.0, ((bpm_f - 70.0) / 90.0) * 0.7 + ((loudness_f + 30.0) / 25.0) * 0.3))
                valence = max(0.0, min(1.0, 0.5 + (energy - 0.5) * 0.4))

            chunk_result: dict = {
                "offset": offset,
                "bpm": round(bpm_f),
                "key": key,
                "scale": scale,
                "loudness_db": round(loudness_f, 1),
                "danceability": round(danceability, 3),
                "valence": round(valence, 3),
                "energy": round(energy, 3),
            }

            if "mood_acoustic" in models:
                chunk_result["acoustic"] = round(float(np.mean(models["mood_acoustic"](embedding)[:, 1])), 3)
            if "voice_instrumental" in models:
                chunk_result["voice"] = round(float(np.mean(models["voice_instrumental"](embedding)[:, 1])), 3)
            if "genre" in models and "genre_labels" in models:
                labels = models["genre_labels"]
                probs = np.mean(models["genre"](embedding), axis=0)
                top3 = probs.argsort()[-3:][::-1]
                logger.info(
                    "[genre] offset=%ds top-3 raw: %s",
                    offset,
                    [(labels[i] if isinstance(labels, list) else labels.get(str(i)), round(float(probs[i]), 4)) for i in top3],
                )
                genres = []
                for i in top3:
                    if probs[i] <= 0.05:
                        continue
                    label = labels[i] if i < len(labels) else None
                    if label:
                        parts = [p.strip() for p in label.split("---")]
                        formatted = f"{parts[-1]} ({parts[0]})" if len(parts) > 1 else parts[0]
                        genres.append(formatted)
                chunk_result["genres"] = list(dict.fromkeys(genres))
                logger.info("[genre] offset=%ds → %s", offset, chunk_result["genres"])
            else:
                logger.warning("[genre] model not loaded — skipping genre extraction")

            results.append(chunk_result)
        finally:
            os.unlink(wav_path)

    return results

#Labeling que é utilizado nas categorizações pelos modelos 
_TEMPO_LABELS = [(60, "muito lento"), (80, "lento"), (100, "moderado"),
                 (120, "animado"), (140, "rápido"), (160, "muito rápido"), (float("inf"), "extremamente rápido")]

def _tempo_label(bpm: int) -> str:
    return next(label for threshold, label in _TEMPO_LABELS if bpm < threshold)

def _score_label(v: float, low="baixo", mid="moderado", high="alto", very_high="muito alto") -> str:
    if v < 0.35: return low
    if v < 0.55: return mid
    if v < 0.80: return high
    return very_high

def _loudness_label(db: float) -> str:
    if db < -23: return "muito silencioso"
    if db < -16: return "silencioso"
    if db < -9:  return "moderado"
    if db < -6:  return "alto"
    return "muito alto"

def _valence_label(v: float) -> str:
    if v < 0.25: return "muito melancólico"
    if v < 0.45: return "melancólico"
    if v < 0.55: return "neutro"
    if v < 0.75: return "positivo"
    return "muito alegre"

#Descrição completa da música qual será realizado o embedding
def build_description(features: dict, title: str = "") -> str:
    parts = []
    if title:
        parts.append(title)
    if genres := features.get("genres"):
        parts.append(", ".join(genres))
    if (acoustic := features.get("acoustic")) is not None:
        parts.append("acústico" if acoustic > 0.6 else "eletrônico" if acoustic < 0.4 else "semi-acústico")
    if (voice := features.get("voice")) is not None:
        parts.append("com vocais" if voice > 0.5 else "instrumental")

    bpm = features["bpm"]
    parts += [
        f"BPM {bpm} ({_tempo_label(bpm)})",
        f"tom {features['key']} {features['scale']}",
        f"loudness {features['loudness_db']} dB ({_loudness_label(features['loudness_db'])})",
        f"energia {_score_label(features['energy'], 'baixa', 'moderada', 'alta', 'muito alta')}",
        f"mood {_valence_label(features['valence'])}",
        f"dançabilidade {_score_label(features['danceability'], 'baixa', 'moderada', 'alta', 'muito alta')}",
    ]
    return ", ".join(parts)


def process_video(video_id: str, title: str = "") -> list[dict]:
    input_url = f"https://www.youtube.com/watch?v={video_id}"
    audio_url, duration = get_audio_url(video_id)
    chunks = download_audio_chunks(audio_url, duration)
    per_chunk = extract_audio_features(chunks)
    for chunk_feat in per_chunk:
        chunk_feat["input_url"] = input_url
        chunk_feat["description"] = build_description(chunk_feat, title)
    logger.debug("process_video video_id=%s chunks=%d", video_id, len(per_chunk))
    return per_chunk
