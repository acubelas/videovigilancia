from fastapi import FastAPI
from src.server.storage import init_db
from src.server.pairing import router as pairing_router

app = FastAPI(title="Videovigilancia Server API", version="0.1.0")

@app.on_event("startup")
def _startup():
    init_db()

@app.get("/api/health")
def health():
    return {"ok": True, "service": "videovigilancia-server", "version": "0.1.0"}

app.include_router(pairing_router)