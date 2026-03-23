from audioExtractor import getAudioUrl, downloadAudioChunks

VIDEO_URL = "https://www.youtube.com/watch?v=yGixTYmRjXw"

print(f"Testing audio extraction for video: {VIDEO_URL}\n")

print("Step 1 — resolving stream URL via yt-dlp...")
audio_url, duration = getAudioUrl(VIDEO_URL)
print(f"  Duration: {duration}s")
print(f"  Stream URL: {audio_url[:80]}...")

print("\nStep 2 — downloading 3 chunks via ffmpeg...")
chunks = downloadAudioChunks(audio_url, duration)
for i, chunk in enumerate(chunks):
    print(f"  Chunk {i}: {len(chunk):,} bytes")

print("\nDownload test passed. (essentia features require Linux/WSL to run)")

