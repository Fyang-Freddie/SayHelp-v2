from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import auth, chat, conversations

app = FastAPI(title="SayHelp", version="0.1.0")

app.include_router(auth.router)
app.include_router(conversations.router)
app.include_router(chat.router)

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
