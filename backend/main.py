from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent.parent

FRONTEND_DIR = BASE_DIR / "frontend"

# Serve CSS + JS
app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")


# --------------------
# UI Routes
# --------------------

@app.get("/")
def landing():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/finance")
def finance():
    return FileResponse(FRONTEND_DIR / "finance.html")


@app.get("/health")
def health():
    return {"status": "ok"}


# --------------------
# API Routes
# --------------------

from pydantic import BaseModel
from backend.orchestrator import handle_message


class ChatRequest(BaseModel):
    message: str


@app.post("/api/orchestrate")
async def orchestrate(req: ChatRequest):
    response = handle_message(req.message)
    return response