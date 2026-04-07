from fastapi import HTTPException
from services.gemini_service import embed_text, embed_image_and_description
import services.db_service as db_service


def embed_text_handler(text: str) -> dict:
    if not text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")
    return {"embedding": embed_text(text)}


def process_image(image_base64: str) -> tuple[list[float], list[float], str]:
    if not image_base64.strip():
        raise HTTPException(status_code=400, detail="imageBase64 must not be empty")
    return embed_image_and_description(image_base64)


def search_by_both(img_embedding: list[float], txt_embedding: list[float]) -> list[dict]:
    return db_service.search_by_embeddings(img_embedding, txt_embedding)