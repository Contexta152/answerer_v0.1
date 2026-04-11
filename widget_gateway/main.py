from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import ask

app = FastAPI(title="Widget Gateway", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST"],
    allow_headers=["*"],
)

app.include_router(ask.router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
