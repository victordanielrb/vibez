import os
import re
import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

EMBEDDING_MODEL = "gemini-embedding-2-preview"
EMBEDDING_DIMENSIONS = 768
VISION_MODEL = "gemini-2.0-flash"

#Embedding do texto, que no caso é a descrição da música
def embed_text(text: str) -> list[float]:
    response = genai.embed_content(
        model=EMBEDDING_MODEL,
        content=text,
        output_dimensionality=EMBEDDING_DIMENSIONS,
    )
    return response["embedding"]

#Faz embedding de uma imagem a partir de base64, e como o modelo é multimodal ele consegue entender a imagem e extrair características dela..
def embed_image(data_uri: str) -> list[float]:
    mime_type_match = re.match(r"^data:([^;]+);base64,", data_uri)
    mime_type = mime_type_match.group(1) if mime_type_match else "image/jpeg"
    raw_base64 = re.sub(r"^data:[^;]+;base64,", "", data_uri)

    content = {
        "parts": [
            {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": raw_base64,
                }
            }
        ]
    }
    response = genai.embed_content(
        model=EMBEDDING_MODEL,
        content=content,
        output_dimensionality=EMBEDDING_DIMENSIONS,
    )
    return response["embedding"]


def embed_image_and_description(data_uri: str) -> tuple[list[float], list[float], str]:
    """Returns (image_embedding, description_embedding, description_text)."""
    description = describe_image(data_uri)
    img_vec = embed_image(data_uri)
    txt_vec = embed_text(description)
    return img_vec, txt_vec, description


def describe_image(data_uri: str) -> str:
    mime_type_match = re.match(r"^data:([^;]+);base64,", data_uri)
    mime_type = mime_type_match.group(1) if mime_type_match else "image/jpeg"
    raw_base64 = re.sub(r"^data:[^;]+;base64,", "", data_uri)

    model = genai.GenerativeModel(VISION_MODEL)
    response = model.generate_content([
        {
            "mime_type": mime_type,
            "data": raw_base64,
        },
        "Describe the mood, atmosphere, colors, and overall vibe of this image in 2-3 sentences. Focus on what emotions and energy it evokes.",
    ])
    return response.text
