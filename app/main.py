import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.api.webapp import router as webapp_router
from app.api.webhook import router as webhook_router
from app.database.session import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(
    title="Лига Помощников API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
@app.get("/webapp")
async def serve_webapp():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return HTMLResponse("<html><head><title>Лига Помощников</title></head><body><div id='app'><h1>Лига Помощников Mini App</h1></div></body></html>")

@app.get("/health")
async def health_check():
    return JSONResponse({"status": "ok"})

app.include_router(webhook_router, prefix="/api/v1")
app.include_router(webapp_router, prefix="/api/v1")
