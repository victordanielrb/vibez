import yt_dlp
import subprocess

def getAudioUrl(url: str) -> tuple:
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
    }

    #With é utilizado pois fecha todas conexões e libera memória após o código terminar de executar
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        audio_url = info.get("url")
        duration = info.get("duration")
    return audio_url, duration


def downloadAudioChunks(url: str, duration: int) -> list[bytes]:
    chunk_paths = []
    result = []
    #Define os trechos a serem baixados, nesse caso 3: início, meio e fim
    chunk_paths.append(30)
    chunk_paths.append(duration//2)
    chunk_paths.append(duration-30)
    #Roda o ffmpeg para baixar os trechos definidos, usando um processo (similar a um terminal) para executar o comando
    for trechos in chunk_paths:
        #Retorna os resultados em bytes puros, pra passarem pelo embbedding do Gemini
        result.append(subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", str(trechos),
                "-t", "30",
                "-i", url,
                "-ac", "1",          # mono
                "-ar", "16000",      # 16kHz
                "-f", "wav",
                "pipe:1"             # output to stdout
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ).stdout)
   
    return result

def extract_audio_features(audio_chunks: list[bytes]) -> dict:
    """Extract all audio features ( BPM, Key, Scale, Loudness and also other audio data)."""
    import tempfile
    import numpy as np
    import essentia.standard as es
    #Essentia não suporta leitura direta de bytes, então é necessário salvar temporariamente
    result = {}
    #Todas essas extrações são utilizadas ML, e utiliza o poder de processamento do computador do host

    with tempfile.NamedTemporaryFile(suffix=".wav") as tmpfile:
        tmpfile.write(audio_chunks[0])  # Escreve o primeiro chunk para análise
        tmpfile.flush()  # Garante que os dados sejam escritos no disco

        loader = es.MonoLoader(filename=tmpfile.name, sampleRate=16000)
        audio = loader()

        #Executa a extração dos dados usando a lib da Essentia
        bpm, _, _, _, _ = es.RhythmExtractor2013(method="multifeature")(audio)
        key, scale, _ = es.KeyExtractor()(audio)

        # LoudnessEBUR128 requires stereo input
        _, _, integrated_loudness, _ = es.LoudnessEBUR128()(
            es.StereoMuxer()(audio, audio)
        )

        model = load_effnet_model(models_path)

        audio = es.MonoLoader(filename=tmpfile.name, sampleRate=16000)()
        patches = es.TensorflowInputMusiCNN()(audio)
        patches = patches[np.newaxis, ...]  # add batch dim

        probs = np.mean(model(patches).numpy(), axis=0)
        result = {
            "bpm": round(float(bpm)),
            "key": key,
            "scale": scale,
            "loudness_db": round(float(integrated_loudness), 1),
            "effnet_embeddings": probs.tolist()
        }
    return result

def process_video(video_url: str):
    audio_url, duration = getAudioUrl(video_url)
    audio_chunks = downloadAudioChunks(audio_url, duration)
    features = extract_audio_features(audio_chunks)
    return features