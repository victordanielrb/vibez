from fastapi import HTTPException
from services.aiService import embed_image


def process_image(image_base64: str, client_ip: str = "system") -> tuple[list[float], str]:
    if not image_base64.strip():
        raise HTTPException(status_code=400, detail="imageBase64 must not be empty")
    img_vec = embed_image(image_base64, client_ip=client_ip)
    return img_vec, image_base64