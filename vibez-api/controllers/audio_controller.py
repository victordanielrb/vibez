import json
from collections.abc import Iterator

import services.audio_extractor as audio_extractor
import services.db_service as db_service
import services.gemini_service as gemini_service


def iter_descriptions_playlist(playlist_id: str) -> Iterator[dict]:
    # Fetch playlist outside any except block — yield must never happen
    # while an exception is active or Starlette's middleware intercepts it.
    fetch_error: str | None = None
    video_ids: list[str] = []
    try:
        video_ids = audio_extractor.get_urls_from_playlist(playlist_id)
    except Exception as exc:
        fetch_error = str(exc)

    if fetch_error is not None:
        yield {"type": "error", "error": f"Could not fetch playlist: {fetch_error}"}
        return

    if not video_ids:
        yield {"type": "error", "error": "No videos found in playlist"}
        return

    total = len(video_ids)
    for index, video_id in enumerate(video_ids, start=1):
        track_error: str | None = None
        features: dict = {}
        try:
            features = audio_extractor.process_video(video_id)
            embedding = gemini_service.embed_text(features["description"])
            db_service.insert_track(
                name=features.get("title", video_id),
                author=features.get("author", "unknown"),
                url=features["input_url"],
                embedding=embedding,
            )
        except Exception as exc:
            track_error = str(exc)

        if track_error is not None:
            yield {"type": "error", "index": index, "total": total, "videoId": video_id, "error": track_error}
        else:
            yield {"type": "progress", "index": index, "total": total, "videoId": video_id, "result": {"videoId": video_id, **features}}

    yield {"type": "done", "total": total}


def iter_descriptions_playlist_sse(playlist_id: str) -> Iterator[str]:
    for event in iter_descriptions_playlist(playlist_id):
        event_type = event.get("type", "message")
        payload = json.dumps(event, ensure_ascii=False)
        yield f"event: {event_type}\ndata: {payload}\n\n"


def process_descriptions_playlist(playlist_id: str) -> dict:
    results = []
    for event in iter_descriptions_playlist(playlist_id):
        if event.get("type") == "progress":
            results.append(event["result"])
        elif event.get("type") == "error":
            results.append({"videoId": event["videoId"], "error": event["error"]})

    return {"results": results}
