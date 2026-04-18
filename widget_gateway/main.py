import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from routers import ask, demo_questions

app = FastAPI(title="Widget Gateway", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(ask.router)
app.include_router(demo_questions.router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/widget.js", include_in_schema=False)
async def serve_widget():
    path = os.path.join(os.path.dirname(__file__), "static", "widget.js")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=3600"},
    )
