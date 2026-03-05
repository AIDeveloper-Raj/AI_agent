import json
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from backend.orchestrator import handle_message

app = FastAPI(title="FiAi Backend API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

// BASE_DIR = Path(__file__).resolve().parent.parent

app.mount("/static", StaticFiles(directory=BASE_DIR / "frontend"), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    file_path = BASE_DIR / "frontend" / "index.html"
    if file_path.exists():
        return file_path.read_text(encoding="utf-8")
    return "<h1>Error: index.html not found</h1>"

@app.get("/finance", response_class=HTMLResponse)
async def serve_finance():
    file_path = BASE_DIR / "frontend" / "finance.html"
    if file_path.exists():
        return file_path.read_text(encoding="utf-8")
    return "<h1>Error: finance.html not found</h1>"

# --- DB VIEWER ROUTES ---
@app.get("/data", response_class=HTMLResponse)
async def serve_data():
    file_path = BASE_DIR / "frontend" / "data.html"
    if file_path.exists():
        return file_path.read_text(encoding="utf-8")
    return "<h1>Error: data.html not found</h1>"

@app.get("/api/db-viewer")
async def api_db_viewer():
    """Reads all JSON files in the data directory and returns them."""
    data_dir = BASE_DIR / "data"
    db_data = {}
    if data_dir.exists():
        for file in data_dir.glob("*.json"):
            try:
                with open(file, "r") as f:
                    db_data[file.stem] = json.load(f)
            except Exception as e:
                print(f"Error loading {file.name}: {e}")
    return db_data
# ------------------------

@app.post("/api/orchestrate")
async def orchestrate(request: Request):
    data = await request.json()
    user_message = data.get("message", "")
    
    # Return a StreamingResponse using NDJSON (Newline Delimited JSON)
    return StreamingResponse(handle_message(user_message), media_type="application/x-ndjson")