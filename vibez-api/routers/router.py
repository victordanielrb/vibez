from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import controllers.audio_controller as audio_controller
import controllers.ai_controller as ai_controller
import services.db_service as db_service
router = APIRouter()


class ExtractRequest(BaseModel):
    playlistUrl: str


@router.post("/extract")
def extract(body: ExtractRequest) -> dict:
    return audio_controller.process_descriptions_playlist(body.playlistUrl)


@router.post("/extract-stream")
def extract_stream(body: ExtractRequest) -> StreamingResponse:
    return StreamingResponse(
        audio_controller.iter_descriptions_playlist_sse(body.playlistUrl),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )

@router.post("/image-embedding")
def image_processing(body: dict) -> dict:
    image_base64 = body.get("imageBase64", "")
    img_embedding, txt_embedding, description = ai_controller.process_image(image_base64)
    search_results = db_service.search_by_embedding(txt_embedding)  # TODO: switch to search_by_both for hybrid
    return {"description": description, "searchResults": search_results}

