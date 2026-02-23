from fastapi import FastAPI

app = FastAPI(title="Videovigilancia Server API", version="0.1.0")

@app.get("/api/health")
def health():
    return {"ok": True, "service": "videovigilancia-server", "version": "0.1.0"}