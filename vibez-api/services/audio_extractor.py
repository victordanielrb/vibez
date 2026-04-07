import os
import yt_dlp
import subprocess
from urllib.parse import parse_qs, urlparse
from yt_dlp.utils import DownloadError

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


def _require_pb(env_var: str) -> str:
    path = os.path.expanduser(os.getenv(env_var, "")).strip()
    if not path:
        raise RuntimeError(f"{env_var} environment variable is not set.")
    if os.path.isdir(path):
        candidates = [os.path.join(path, f) for f in os.listdir(path) if f.endswith(".pb")]
        if len(candidates) == 1:
            return candidates[0]
        raise RuntimeError(f"{env_var} points to a directory with {len(candidates)} .pb files — be explicit.")
    if not path.endswith(".pb"):
        raise RuntimeError(f"{env_var} must point to a .pb frozen graph file.")
    if not os.path.isfile(path):
        raise RuntimeError(f"Model file not found: {path}")
    return path


def _optional_pb(env_var: str) -> str | None:
    raw = os.path.expanduser(os.getenv(env_var, "")).strip()
    if not raw:
        return None
    return raw if os.path.isfile(raw) else None


def _load_models() -> dict:
    global _models
    if _models:
        return _models

    import essentia.standard as es

    effnet_path = _require_pb("MODELS_PATH")
    _models["effnet"] = es.TensorflowPredictEffnetDiscogs(
        graphFilename=effnet_path,
        output="PartitionedCall:1",
    )

    for key, env_var in [
        ("danceability",    "DANCEABILITY_MODEL_PATH"),
        ("mood_happy",      "MOOD_HAPPY_MODEL_PATH"),
        ("mood_sad",        "MOOD_SAD_MODEL_PATH"),
        ("mood_aggressive", "MOOD_AGGRESSIVE_MODEL_PATH"),
        ("mood_relaxed",    "MOOD_RELAXED_MODEL_PATH"),
        ("mood_acoustic",   "MOOD_ACOUSTIC_MODEL_PATH"),
        ("voice_instrumental", "VOICE_INSTRUMENTAL_MODEL_PATH"),
    ]:
        path = _optional_pb(env_var)
        if path:
            _models[key] = es.TensorflowPredict2D(graphFilename=path, output="model/Softmax")

    genre_path = _optional_pb("GENRE_MODEL_PATH")
    if genre_path:
        _models["genre"] = es.TensorflowPredict2D(graphFilename=genre_path, output="model/Softmax")
        labels_path = os.path.splitext(genre_path)[0] + ".json"
        if os.path.isfile(labels_path):
            import json
            with open(labels_path) as f:
                _models["genre_labels"] = json.load(f)

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
        "cookiesfrombrowser": ("firefox",),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(playlist_url, download=False)
        if "entries" in info:
            #Checka se existe a chave "url" em cada entrada
            for entry in info["entries"]:
                if "url" in entry:
                    videoUrlList.append(_normalize_video_id(entry["url"]))
    return videoUrlList

#Download de trechos , um no começo, um no meio e um no final do áudio, para que um trecho defina a mood inteira da música
def download_audio_chunks(url: str, duration: int) -> list[bytes]:
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
        chunks.append(result.stdout)
    return chunks


def _write_tmp_wav(chunk: bytes) -> str:
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(chunk)
        return f.name

#Utiliza os modelos prontos da biblioteca Essentia para extrair características de áudio como BPM, key, loudness, danceability, valence e energy.
#O Embedding desses modelos é utilizado pra pegar outros dados extras como gênero, acústico/eletrônico e vocal/instrumental, utilizando os modelos extras.
def extract_audio_features(audio_chunks: list[bytes]) -> dict:
    import numpy as np
    import essentia.standard as es

    models = _load_models()
    bpms, keys, loudnesses, all_embeddings = [], [], [], []

    for chunk in audio_chunks:
        wav_path = _write_tmp_wav(chunk)
        try:
            audio = es.MonoLoader(filename=wav_path, sampleRate=16000)()
            bpm, *_ = es.RhythmExtractor2013(method="multifeature")(audio)
            key, scale, strength = es.KeyExtractor()(audio)
            _, _, loudness, _ = es.LoudnessEBUR128()(es.StereoMuxer()(audio, audio))

            bpms.append(float(bpm))
            keys.append((key, scale, float(strength)))
            loudnesses.append(float(loudness))
            all_embeddings.append(models["effnet"](audio))
        finally:
            os.unlink(wav_path)

    avg_bpm = float(np.mean(bpms))
    avg_loudness = float(np.mean(loudnesses))
    best_key, best_scale, _ = max(keys, key=lambda x: x[2])
    combined = np.concatenate(all_embeddings, axis=0)

    if "danceability" in models:
        danceability = float(np.mean(models["danceability"](combined)[:, 1]))
    else:
        danceability = max(0.0, min(1.0,
            ((avg_bpm - 70.0) / 90.0) * 0.65 + ((avg_loudness + 30.0) / 25.0) * 0.35))

    mood_keys = {"mood_happy", "mood_sad", "mood_aggressive", "mood_relaxed"}
    if mood_keys.issubset(models):
        p_happy      = float(np.mean(models["mood_happy"](combined)[:, 1]))
        p_sad        = float(np.mean(models["mood_sad"](combined)[:, 1]))
        p_aggressive = float(np.mean(models["mood_aggressive"](combined)[:, 1]))
        p_relaxed    = float(np.mean(models["mood_relaxed"](combined)[:, 1]))
        valence = max(0.0, min(1.0, (p_happy - p_sad + 1) / 2))
        energy  = max(0.0, min(1.0, (p_aggressive - p_relaxed + 1) / 2))
    else:
        energy  = max(0.0, min(1.0, ((avg_bpm - 70.0) / 90.0) * 0.7 + ((avg_loudness + 30.0) / 25.0) * 0.3))
        valence = max(0.0, min(1.0, 0.5 + (energy - 0.5) * 0.4))

    result: dict = {
        "bpm": round(avg_bpm),
        "key": best_key,
        "scale": best_scale,
        "loudness_db": round(avg_loudness, 1),
        "danceability": round(danceability, 3),
        "valence": round(valence, 3),
        "energy": round(energy, 3),
    }

    if "mood_acoustic" in models:
        result["acoustic"] = round(float(np.mean(models["mood_acoustic"](combined)[:, 1])), 3)
    if "voice_instrumental" in models:
        result["voice"] = round(float(np.mean(models["voice_instrumental"](combined)[:, 1])), 3)
    if "genre" in models and "genre_labels" in models:
        import numpy as np
        probs = np.mean(models["genre"](combined), axis=0)
        top3 = probs.argsort()[-3:][::-1]
        result["genres"] = [models["genre_labels"][i] for i in top3 if probs[i] > 0.05]

    return result

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


def process_video(video_id: str, title: str = "") -> dict:
    input_url = f"https://www.youtube.com/watch?v={video_id}"
    audio_url, duration = get_audio_url(video_id)
    chunks = download_audio_chunks(audio_url, duration)
    features = extract_audio_features(chunks)
    features["input_url"] = input_url
    features["description"] = build_description(features, title)
    return features
