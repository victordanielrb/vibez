import base64
import json
import logging
import re
from typing import Any

from google.genai import types
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from pydantic import BaseModel

import services.dbService as db_service

logger = logging.getLogger(__name__)

VISION_MODEL = "gemini-3.1-flash-lite"


# ── Shared helpers ────────────────────────────────────────────────────────────

def _parse_data_uri(data_uri: str) -> tuple[str, bytes]:
    mime_type_match = re.match(r"^data:([^;]+);base64,", data_uri)
    mime_type = mime_type_match.group(1) if mime_type_match else "image/jpeg"
    raw_base64 = re.sub(r"^data:[^;]+;base64,", "", data_uri)
    return mime_type, base64.b64decode(raw_base64)


def _build_tracks_payload(candidates: list[dict]) -> str:
    return json.dumps(
        [
            {
                "id": c["id"],
                "name": c["name"],
                "author": c["author"],
                "description": c.get("description") or f"{c['name']} by {c['author']}",
            }
            for c in candidates
        ],
        ensure_ascii=False,
        indent=2,
    )


# ── Pydantic schemas for structured output ────────────────────────────────────

class _ImageGenres(BaseModel):
    genres: list[str]


class _RankItem(BaseModel):
    id: int
    rank: int
    reason: str


class _Rankings(BaseModel):
    rankings: list[_RankItem]


# ── Agent instructions ────────────────────────────────────────────────────────

_DESCRIBE_INSTRUCTION = (
    "Describe the mood, atmosphere, colors, and overall vibe of this image in 2-3 sentences. "
    "Focus on what emotions and energy it evokes."
)

_GENRE_INSTRUCTION = (
    "What music genres (1-3) best fit the vibe of this image? "
    "Use common genre names like Rock, Metal, Pop, Electronic, Hip-Hop, Jazz, Classical, R&B."
)

_RERANK_INSTRUCTION = """\
You are a music-image vibe matching judge.

Your task: given an image and a list of music tracks, rank how well \
each track would feel as a natural soundtrack for that image.

RANKING CRITERIA (ordered by priority):

1. GENRE FIT (highest weight — this is the dominant signal):
   - If IMAGE GENRES are provided, tracks that match or are close sub-genres must rank higher.
   - Tracks with entirely mismatched genres must rank lower even if other attributes seem right.
   - No candidate will always perfectly match — pick the closest genre fit and acknowledge the gap.

2. ENERGY & PACE:
   - High-energy scenes (clubs, action, sport) → prefer high BPM and high energy tracks.
   - Calm/intimate scenes → prefer lower BPM and quieter tracks.

3. EMOTIONAL ATMOSPHERE:
   - Tonal character: bright vs dark, warm vs cold.
   - Mood: does the track's mood (melancholic, euphoric, aggressive) match the image's mood?

4. ACOUSTIC TEXTURE:
   - Dense/sparse, loud/quiet, electronic/organic.

When NO candidate matches the image genre, still rank them — pick the one closest in subgenre \
or energy profile, and explicitly note the genre mismatch in the reason.

The exact number of tracks to rank is specified in the user message.
Return ONLY valid JSON with a "rankings" array sorted rank 1 = best.
Each item: {"id": int, "rank": int, "reason": string (1 sentence, in Portuguese)}.\
"""


# ── ADK infrastructure ────────────────────────────────────────────────────────

_session_service = InMemorySessionService()

_describer_agent = LlmAgent(
    name="image_describer",
    model=VISION_MODEL,
    instruction=_DESCRIBE_INSTRUCTION,
    output_key="description",
)

_genre_agent = LlmAgent(
    name="genre_extractor",
    model=VISION_MODEL,
    instruction=_GENRE_INSTRUCTION,
    output_schema=_ImageGenres,
    output_key="genre_result",
)

_reranker_agent = LlmAgent(
    name="track_reranker",
    model=VISION_MODEL,
    instruction=_RERANK_INSTRUCTION,
    output_schema=_Rankings,
    output_key="rank_result",
)

_describer_runner = Runner(agent=_describer_agent, session_service=_session_service, app_name="vibez")
_genre_runner = Runner(agent=_genre_agent, session_service=_session_service, app_name="vibez")
_reranker_runner = Runner(agent=_reranker_agent, session_service=_session_service, app_name="vibez")


# ── Core invoke helper ────────────────────────────────────────────────────────

async def _invoke(
    runner: Runner,
    content: types.Content,
    client_ip: str,
    operation: str,
    output_key: str | None = None,
) -> Any:
    """Run an ADK agent, capture OTel-tracked tokens, and log to SQLite quota."""
    user_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", client_ip)
    session = await _session_service.create_session(app_name="vibez", user_id=user_id)

    tokens_in = tokens_out = 0
    final_text = ""
    state_result: Any = None

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=content,
    ):
        usage = getattr(event, "usage_metadata", None)
        if usage:
            tokens_in += getattr(usage, "prompt_token_count", 0) or 0
            tokens_out += getattr(usage, "candidates_token_count", 0) or 0

        if event.is_final_response():
            actions = getattr(event, "actions", None)
            state_delta = getattr(actions, "state_delta", None) if actions else None
            if output_key and state_delta:
                state_result = state_delta.get(output_key)
            if event.content and event.content.parts:
                final_text = "".join(
                    p.text for p in event.content.parts
                    if getattr(p, "text", None) and not getattr(p, "thought", False)
                )

    db_service.log_usage(client_ip, operation, VISION_MODEL, tokens_in, tokens_out)

    # Return structured state_delta result if available, else raw text
    if output_key and state_result is not None:
        return state_result
    return final_text


# ── Public async API ──────────────────────────────────────────────────────────

async def describe_image(data_uri: str, client_ip: str = "system") -> str:
    mime_type, image_bytes = _parse_data_uri(data_uri)
    content = types.Content(parts=[
        types.Part(inline_data=types.Blob(mime_type=mime_type, data=image_bytes)),
        types.Part(text="Describe this image."),
    ])
    result = await _invoke(_describer_runner, content, client_ip, "describe_image", output_key="description")
    text = result if isinstance(result, str) else str(result)
    logger.info("[image_describer] %s", text)
    return text


async def extract_image_genres(data_uri: str, client_ip: str = "system") -> list[str]:
    mime_type, image_bytes = _parse_data_uri(data_uri)
    content = types.Content(parts=[
        types.Part(inline_data=types.Blob(mime_type=mime_type, data=image_bytes)),
        types.Part(text="Extract 1-3 music genres from this image."),
    ])
    result = await _invoke(_genre_runner, content, client_ip, "extract_genres", output_key="genre_result")
    # result is {"genres": [...]} dict (from validate_schema + model_dump)
    if isinstance(result, dict):
        genres = result.get("genres", [])[:3]
    else:
        genres = []
    logger.info("[genre_extractor] → %s", genres)
    return genres


async def rerank_by_vibe_image(
    data_uri: str,
    candidates: list[dict],
    top_n: int = 5,
    image_genres: list[str] | None = None,
    client_ip: str = "system",
) -> list[dict]:
    if not candidates:
        return []

    mime_type, image_bytes = _parse_data_uri(data_uri)
    tracks_payload = _build_tracks_payload(candidates)
    genre_hint = f"IMAGE GENRES: {', '.join(image_genres)}\n\n" if image_genres else ""

    logger.info(
        "[track_reranker] genres=%s | candidates (%d):\n%s",
        image_genres or [],
        len(candidates),
        "\n".join(f"  id={c['id']} | {c['name']} — {c.get('description', 'no description')}" for c in candidates),
    )

    user_text = f"{genre_hint}CANDIDATE TRACKS:\n{tracks_payload}\n\nRank the top {top_n} tracks."
    content = types.Content(parts=[
        types.Part(inline_data=types.Blob(mime_type=mime_type, data=image_bytes)),
        types.Part(text=user_text),
    ])

    result = await _invoke(_reranker_runner, content, client_ip, "rerank_tracks", output_key="rank_result")

    # result is {"rankings": [{id, rank, reason}, ...]} dict
    if isinstance(result, dict):
        raw_rankings = result.get("rankings", [])
    else:
        logger.warning("[track_reranker] unexpected result type: %s", type(result))
        return []

    logger.info(
        "[track_reranker] rankings:\n%s",
        "\n".join(f"  #{r.get('rank')} id={r.get('id')} — {r.get('reason','')}" for r in raw_rankings),
    )

    candidates_by_id = {c["id"]: c for c in candidates}
    output = []
    for r in raw_rankings:
        cid = r.get("id")
        if cid in candidates_by_id:
            output.append({**candidates_by_id[cid], "rank": r.get("rank"), "reason": r.get("reason")})
    return output[:top_n]
