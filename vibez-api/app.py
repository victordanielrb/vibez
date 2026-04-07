import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import router

app = FastAPI(title="vibez-api")

_origins = os.getenv("FRONTEND_URL", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_origins] if _origins != "*" else ["*"],
    allow_credentials=_origins != "*",
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router=router.router)


@app.get("/health")
def health():
    return {"status": "ok"}
