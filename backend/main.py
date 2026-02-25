from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

# Import your new hardcoded logic
from backend.orchestrator import handle_message

app = FastAPI(title="FiAi Backend API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent

# 1. Mount the frontend directory so CSS and JS load properly
app.mount("/static", StaticFiles(directory=BASE_DIR / "frontend"), name="static")

# 2. Add a route for the root page (index.html)
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    file_path = BASE_DIR / "frontend" / "index.html"
    if file_path.exists():
        return file_path.read_text(encoding="utf-8")
    return "<h1>Error: index.html not found</h1>"

# 3. Add the missing route for the /finance page
@app.get("/finance", response_class=HTMLResponse)
async def serve_finance():
    file_path = BASE_DIR / "frontend" / "finance.html"
    if file_path.exists():
        return file_path.read_text(encoding="utf-8")
    return "<h1>Error: finance.html not found</h1>"

# 4. Your API endpoint for the chat
@app.post("/api/orchestrate")
async def orchestrate(request: Request):
    data = await request.json()
    user_message = data.get("message", "")
    
    # Send to your new Python logic tree
    agent_response = handle_message(user_message)
    return agent_response