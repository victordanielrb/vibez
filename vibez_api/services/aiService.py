import base64
import logging
import os
import re

from google import genai
from google.genai import types

import services.dbService as db_service

logger = logging.getLogger(__name__)

_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _parse_data_uri(data_uri: str) -> tuple[str, bytes]:
    mime_type_match = re.match(r"^data:([^;]+);base64,", data_uri)
    mime_type = mime_type_match.group(1) if mime_type_match else "image/jpeg"
    raw_base64 = re.sub(r"^data:[^;]+;base64,", "", data_uri)
    return mime_type, base64.b64decode(raw_base64)

EMBEDDING_MODEL = "gemini-embedding-2-preview"
EMBEDDING_DIMENSIONS = 768


def _tokens_from_embed(response, fallback_chars: int = 0) -> int:
    usage = getattr(response, "usage_metadata", None)
    return (
        getattr(usage, "total_token_count", None)
        or getattr(usage, "prompt_token_count", None)
        or max(fallback_chars // 4, 1)
    )



def embed_text(text: str, client_ip: str = "system") -> list[float]:
    response = _client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
        config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIMENSIONS),
    )
    tokens_in = _tokens_from_embed(response, len(text))
    db_service.log_usage(client_ip, "embed_text", EMBEDDING_MODEL, tokens_in, 0)
    return list(response.embeddings[0].values)


def embed_image(data_uri: str, client_ip: str = "system") -> list[float]:
    mime_type, image_bytes = _parse_data_uri(data_uri)
    response = _client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=types.Content(
            parts=[
                types.Part(
                    inline_data=types.Blob(mime_type=mime_type, data=image_bytes)
                )
            ]
        ),
        config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIMENSIONS),
    )
    tokens_in = _tokens_from_embed(response, 258 * 4)  # ~258 tokens for image embed
    db_service.log_usage(client_ip, "embed_image", EMBEDDING_MODEL, tokens_in, 0)
    return list(response.embeddings[0].values)


