import numpy as np
import essentia.standard as es
import tensorflow as tf

from AudioExtract import download_chunks, CHUNK_DURATION

# EffNet-Discogs loads once at module level — ~150MB, kept in memory
_effnet_model: tf.saved_model | None = None


def load_effnet_model(models_path: str) -> tf.saved_model:
    global _effnet_model
    if _effnet_model is None:
        _effnet_model = tf.saved_model.load(models_path)
    return _effnet_model


def extract_dsp_features(wav_path: str) -> dict:
    """Extract BPM, Key, and Loudness from a WAV file using Essentia."""
    loader = es.MonoLoader(filename=wav_path, sampleRate=16000)
    audio = loader()

    bpm, _, _, _, _ = es.RhythmExtractor2013(method="multifeature")(audio)
    key, scale, _ = es.KeyExtractor()(audio)

    # LoudnessEBUR128 requires stereo input
    _, _, integrated_loudness, _ = es.LoudnessEBUR128()(
        es.StereoMuxer()(audio, audio)
    )

    return {
        "bpm": round(float(bpm)),
        "key": key,
        "scale": scale,
        "loudness_db": round(float(integrated_loudness), 1),
    }


def extract_effnet_features(wav_path: str, models_path: str) -> dict:
    """Run EffNet-Discogs to get mood/genre/danceability predictions."""
    model = load_effnet_model(models_path)

    audio = es.MonoLoader(filename=wav_path, sampleRate=16000)()
    patches = es.TensorflowInputMusiCNN()(audio)
    patches = patches[np.newaxis, ...]  # add batch dim

    probs = np.mean(model(patches).numpy(), axis=0)
    return {"effnet_embeddings": probs.tolist()}


def build_description(dsp: dict, effnet: dict, title: str) -> str:
    """Combine DSP and EffNet features into a semantic string for Gemini embedding."""
    bpm = dsp["bpm"]
    key = f"{dsp['key']} {dsp['scale']}"
    loudness = dsp["loudness_db"]

    # Energy derived from DSP: high BPM + loud = energetic
    energy = "alta" if (bpm >= 120 and loudness >= -14) else "moderada" if bpm >= 100 else "baixa"

    return (
        f"Música: {title}, BPM {bpm}, tom {key}, "
        f"loudness {loudness}db, energia {energy}"
    )


def process_video(video_id: str, title: str, models_path: str) -> str:
    """Full pipeline: download -> DSP -> EffNet -> description string."""
    chunk_paths = download_chunks(video_id, CHUNK_DURATION)

    dsp_results = [extract_dsp_features(p) for p in chunk_paths]
    effnet_results = [extract_effnet_features(p, models_path) for p in chunk_paths]

    avg_dsp = {
        "bpm": round(sum(d["bpm"] for d in dsp_results) / len(dsp_results)),
        "key": dsp_results[1]["key"],
        "scale": dsp_results[1]["scale"],
        "loudness_db": round(
            sum(d["loudness_db"] for d in dsp_results) / len(dsp_results), 1
        ),
    }

    avg_effnet = {
        "effnet_embeddings": np.mean(
            [e["effnet_embeddings"] for e in effnet_results], axis=0
        ).tolist()
    }

    return build_description(avg_dsp, avg_effnet, title)