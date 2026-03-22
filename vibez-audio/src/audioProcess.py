import subprocess
import os
import tempfile
import yt_dlp
import numpy as np
import essentia.standard as es
import tensorflow as tf

# EffNet-Discogs loads once at module level — ~150MB, kept in memory
_effnet_model: tf.saved_model | None = None

def load_effnet_model(models_path: str) -> tf.saved_model:
    global _effnet_model
    if _effnet_model is None:
        _effnet_model = tf.saved_model.load(models_path)
    return _effnet_model


CHUNK_OFFSETS = [30, 90, 150]  # seconds: 0:30, 1:30, 2:30
CHUNK_DURATION = 15            # seconds per chunk


def download_chunks(video_id: str, offsets: list[int], duration: int) -> list[str]:
    """Download 3 audio chunks from a YouTube video using yt-dlp + ffmpeg.
    Returns list of temp WAV file paths."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    chunk_paths = []

    with tempfile.TemporaryDirectory() as tmpdir:
        # Download best audio to a single file first
        raw_path = os.path.join(tmpdir, "raw.%(ext)s")
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": raw_path,
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            downloaded = ydl.prepare_filename(info)

        for offset in offsets:
            out_path = os.path.join(tmpdir, f"chunk_{offset}.wav")
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", str(offset),
                    "-t", str(duration),
                    "-i", downloaded,
                    "-ac", "1",          # mono
                    "-ar", "16000",      # 16kHz
                    out_path,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            chunk_paths.append(out_path)

    return chunk_paths


def extract_dsp_features(wav_path: str) -> dict:
    """Extract BPM, Key, and Loudness from a WAV file using Essentia."""
    loader = es.MonoLoader(filename=wav_path, sampleRate=16000)
    audio = loader()

    # BPM
    rhythm_extractor = es.RhythmExtractor2013(method="multifeature")
    bpm, _, _, _, _ = rhythm_extractor(audio)

    # Key
    key_extractor = es.KeyExtractor()
    key, scale, _ = key_extractor(audio)

    # Loudness (integrated LUFS-like)
    loudness_extractor = es.LoudnessEBUR128()
    _, _, integrated_loudness, _ = loudness_extractor(
        es.StereoMuxer()(audio, audio)  # fake stereo — extractor requires stereo
    )

    return {
        "bpm": round(float(bpm)),
        "key": key,
        "scale": scale,
        "loudness_db": round(float(integrated_loudness), 1),
    }


def extract_effnet_features(wav_path: str, models_path: str) -> dict:
    """Run EffNet-Discogs to get mood, genre, and danceability predictions."""
    model = load_effnet_model(models_path)

    loader = es.MonoLoader(filename=wav_path, sampleRate=16000)
    audio = loader()

    # EffNet expects mel-spectrogram patches — use Essentia's TensorflowInputMusiCNN
    # as pre-processing (same patch size used by Discogs models)
    tensorflowInputMusiCNN = es.TensorflowInputMusiCNN()
    patches = tensorflowInputMusiCNN(audio)
    patches = patches[np.newaxis, ...]  # add batch dim

    predictions = model(patches)
    # predictions shape: (1, num_classes) — take mean across patches if needed
    probs = np.mean(predictions.numpy(), axis=0)

    return {"effnet_embeddings": probs.tolist()}


def build_description(dsp: dict, effnet: dict, title: str) -> str:
    """Combine DSP and EffNet features into a semantic string for Gemini embedding."""
    bpm = dsp["bpm"]
    key = f"{dsp['key']} {dsp['scale']}"
    loudness = dsp["loudness_db"]

    # Use raw embedding mean as a rough energy proxy until label mappings are added
    energy = "alta" if float(np.mean(effnet["effnet_embeddings"])) > 0.5 else "moderada"

    return (
        f"Música: {title}, BPM {bpm}, tom {key}, "
        f"loudness {loudness}db, energia {energy}"
    )


def process_video(video_id: str, title: str, models_path: str) -> str:
    """Full pipeline: download → DSP → EffNet → description string."""
    chunk_paths = download_chunks(video_id, CHUNK_OFFSETS, CHUNK_DURATION)

    dsp_results = [extract_dsp_features(p) for p in chunk_paths]
    effnet_results = [extract_effnet_features(p, models_path) for p in chunk_paths]

    # Average DSP features across chunks
    avg_dsp = {
        "bpm": round(sum(d["bpm"] for d in dsp_results) / len(dsp_results)),
        "key": dsp_results[1]["key"],    # use middle chunk as representative
        "scale": dsp_results[1]["scale"],
        "loudness_db": round(
            sum(d["loudness_db"] for d in dsp_results) / len(dsp_results), 1
        ),
    }

    # Average EffNet embeddings across chunks
    avg_effnet = {
        "effnet_embeddings": np.mean(
            [e["effnet_embeddings"] for e in effnet_results], axis=0
        ).tolist()
    }

    return build_description(avg_dsp, avg_effnet, title)
