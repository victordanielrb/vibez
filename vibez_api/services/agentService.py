import base64
import json
import logging
import re
from typing import Any, Literal

from google.genai import types
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import AgentTool
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


def _tempo_label(bpm: float) -> str:
    for threshold, label in [(60, "muito lento"), (80, "lento"), (100, "moderado"),
                             (120, "animado"), (140, "rápido"), (160, "muito rápido"),
                             (float("inf"), "extremamente rápido")]:
        if bpm < threshold:
            return label
    return "rápido"

def _score_label(v: float) -> str:
    if v < 0.35: return "baixa"
    if v < 0.55: return "moderada"
    if v < 0.80: return "alta"
    return "muito alta"

def _valence_label(v: float) -> str:
    if v < 0.25: return "muito melancólico"
    if v < 0.45: return "melancólico"
    if v < 0.55: return "neutro"
    if v < 0.75: return "positivo"
    return "muito alegre"


def _build_tracks_payload(candidates: list[dict]) -> str:
    items = []
    for c in candidates:
        f = c.get("features") or {}
        item: dict = {"id": c["id"], "name": c["name"], "author": c["author"]}
        if genres := f.get("genres"):
            item["genres"] = genres
        if (bpm := f.get("bpm")) is not None:
            item["bpm"] = round(bpm)
            item["tempo"] = _tempo_label(bpm)
        if (energy := f.get("energy")) is not None:
            item["energy"] = _score_label(energy)
        if (valence := f.get("valence")) is not None:
            item["mood"] = _valence_label(valence)
        if (dance := f.get("danceability")) is not None:
            item["danceability"] = _score_label(dance)
        if (acoustic := f.get("acoustic")) is not None:
            item["texture"] = "acústico" if acoustic > 0.6 else "eletrônico" if acoustic < 0.4 else "semi-acústico"
        if (voice := f.get("voice")) is not None:
            item["vocals"] = "com vocais" if voice > 0.5 else "instrumental"
        if not f:
            item["description"] = c.get("description") or f"{c['name']} by {c['author']}"
        items.append(item)
    return json.dumps(items, ensure_ascii=False, indent=2)


# ── Pydantic schemas for structured output ────────────────────────────────────

class _ImageGenres(BaseModel):
    genres: list[str]


FitLevel = Literal["alto", "médio", "baixo"]

class _RankItem(BaseModel):
    id: int
    rank: int
    reason: str
    genre_fit: FitLevel
    mood_fit: FitLevel
    pace_fit: FitLevel


class _Rankings(BaseModel):
    rankings: list[_RankItem]


# ── Agent instructions ────────────────────────────────────────────────────────

_DESCRIBE_INSTRUCTION = (
    "Descreva o mood, atmosfera, cores e vibe geral desta imagem em 2-3 frases em português. "
    "Foque nas emoções e energia que ela transmite."
)

_GENRE_INSTRUCTION = (
    "Quais gêneros musicais (1-3) melhor combinam com a vibe desta imagem? "
    "Use nomes de gêneros comuns como Rock, Metal, Pop, Electronic, Hip-Hop, Jazz, Classical, R&B."
)

_RERANK_INSTRUCTION = """\
Você é um juiz de correspondência de vibe entre imagem e música.

Sua tarefa: dada uma imagem e uma lista de faixas musicais, rankeie quão bem \
cada faixa funcionaria como trilha sonora natural para essa imagem.

Você tem acesso à tool "image_describer" — use-a se precisar de uma descrição \
mais detalhada da imagem antes de rankear.

CRITÉRIOS DE RANKING (em ordem de prioridade):

1. ADEQUAÇÃO DE GÊNERO (peso máximo — sinal dominante):
   - Se GÊNEROS DA IMAGEM forem fornecidos, faixas que combinam ou são subgêneros próximos devem rankear mais alto.
   - Faixas com gêneros completamente incompatíveis devem rankear mais baixo mesmo que outros atributos pareçam certos.
   - Nem sempre haverá combinação perfeita — escolha o gênero mais próximo e reconheça a diferença.

2. RITMO E PACE (pace_fit):
   - Analise a velocidade visual e energia da cena:
     → Imagem agitada, futurista, urbana, de ação → BPM alto + energia alta + eletrônico = pace_fit "alto"
     → Imagem calma, íntima, natural, contemplativa → BPM baixo + acústico + energia baixa = pace_fit "alto"
     → Contradição entre energia visual e musical = pace_fit "baixo"

3. ATMOSFERA EMOCIONAL (mood_fit):
   - O mood da faixa (valence: melancólico ↔ alegre) combina com o tom emocional da imagem?
   - Caráter tonal: claro vs escuro, quente vs frio.

4. TEXTURA ACÚSTICA:
   - Denso/esparso, eletrônico/orgânico, vocal/instrumental.

CAMPOS DE AVALIAÇÃO (preencha para cada faixa):
- genre_fit: "alto" se gênero compatível | "médio" se subgênero próximo | "baixo" se incompatível
- mood_fit:  "alto" se valence/atmosfera alinha com o mood da imagem | "médio" se parcial | "baixo" se oposto
- pace_fit:  "alto" se BPM/energia/textura casa com a velocidade visual da cena | "médio" se parcial | "baixo" se contradiz

Quando NENHUM candidato combina com o gênero da imagem, rankeie mesmo assim — escolha o mais \
próximo em subgênero ou perfil de energia, e note explicitamente a incompatibilidade no motivo.

O número exato de faixas a rankear está especificado na mensagem do usuário.
Retorne APENAS JSON válido com um array "rankings" ordenado rank 1 = melhor.
Cada item: {"id": int, "rank": int, "reason": "1 frase PT", \
"genre_fit": "alto"|"médio"|"baixo", "mood_fit": "alto"|"médio"|"baixo", "pace_fit": "alto"|"médio"|"baixo"}.\
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

_describer_tool = AgentTool(agent=_describer_agent)

_reranker_agent = LlmAgent(
    name="track_reranker",
    model=VISION_MODEL,
    instruction=_RERANK_INSTRUCTION,
    tools=[_describer_tool],
    output_schema=_Rankings,
    output_key="rank_result",
)

_describer_runner = Runner(agent=_describer_agent, session_service=_session_service, app_name="vibez")
_genre_runner     = Runner(agent=_genre_agent,     session_service=_session_service, app_name="vibez")
_reranker_runner  = Runner(agent=_reranker_agent,  session_service=_session_service, app_name="vibez")


# ── Core invoke helper ────────────────────────────────────────────────────────

async def _invoke(
    runner: Runner,
    content: types.Content,
    client_ip: str,
    operation: str,
    output_key: str | None = None,
) -> Any:
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

    if output_key and state_result is not None:
        return state_result
    return final_text


# ── Public async API ──────────────────────────────────────────────────────────

async def describe_image(data_uri: str, client_ip: str = "system") -> str:
    mime_type, image_bytes = _parse_data_uri(data_uri)
    content = types.Content(parts=[
        types.Part(inline_data=types.Blob(mime_type=mime_type, data=image_bytes)),
        types.Part(text="Descreva esta imagem."),
    ])
    result = await _invoke(_describer_runner, content, client_ip, "describe_image", output_key="description")
    text = result if isinstance(result, str) else str(result)
    logger.info("[image_describer] %s", text)
    return text


async def extract_image_genres(data_uri: str, client_ip: str = "system") -> list[str]:
    mime_type, image_bytes = _parse_data_uri(data_uri)
    content = types.Content(parts=[
        types.Part(inline_data=types.Blob(mime_type=mime_type, data=image_bytes)),
        types.Part(text="Extraia 1-3 gêneros musicais desta imagem."),
    ])
    result = await _invoke(_genre_runner, content, client_ip, "extract_genres", output_key="genre_result")
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
    image_description: str | None = None,
    client_ip: str = "system",
) -> list[dict]:
    if not candidates:
        return []

    mime_type, image_bytes = _parse_data_uri(data_uri)
    tracks_payload = _build_tracks_payload(candidates)
    desc_hint  = f"DESCRIÇÃO DA IMAGEM: {image_description}\n\n" if image_description else ""
    genre_hint = f"GÊNEROS DA IMAGEM: {', '.join(image_genres)}\n\n" if image_genres else ""

    logger.info(
        "[track_reranker] genres=%s | candidates (%d):\n%s",
        image_genres or [],
        len(candidates),
        "\n".join(f"  id={c['id']} | {c['name']} — {c.get('description', '')}" for c in candidates),
    )

    user_text = f"{desc_hint}{genre_hint}FAIXAS CANDIDATAS:\n{tracks_payload}\n\nRankeie as top {top_n} faixas."
    content = types.Content(parts=[
        types.Part(inline_data=types.Blob(mime_type=mime_type, data=image_bytes)),
        types.Part(text=user_text),
    ])

    result = await _invoke(_reranker_runner, content, client_ip, "rerank_tracks", output_key="rank_result")

    if isinstance(result, dict):
        raw_rankings = result.get("rankings", [])
    else:
        logger.warning("[track_reranker] unexpected result type: %s", type(result))
        return []

    logger.info(
        "[track_reranker] rankings:\n%s",
        "\n".join(
            f"  #{r.get('rank')} id={r.get('id')} genre={r.get('genre_fit')} mood={r.get('mood_fit')} pace={r.get('pace_fit')} — {r.get('reason','')}"
            for r in raw_rankings
        ),
    )

    candidates_by_id = {c["id"]: c for c in candidates}
    output = []
    for r in raw_rankings:
        cid = r.get("id")
        if cid in candidates_by_id:
            output.append({
                **candidates_by_id[cid],
                "rank":       r.get("rank"),
                "reason":     r.get("reason"),
                "genre_fit":  r.get("genre_fit"),
                "mood_fit":   r.get("mood_fit"),
                "pace_fit":   r.get("pace_fit"),
            })
    return output[:top_n]
