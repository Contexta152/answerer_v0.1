import logging
from contextlib import asynccontextmanager
from pathlib import Path

logging.basicConfig(level=logging.INFO)

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from routers import auth, checkout, payments, quota, tenants, webhook
from storage.postgres import create_tables

_STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    yield


app = FastAPI(title="Vendor Console API", version="1.0.0", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(tenants.router)
app.include_router(quota.router)
app.include_router(payments.router)
app.include_router(webhook.router)
app.include_router(checkout.router)

app.mount("/static", StaticFiles(directory=_STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(_STATIC / "index.html")


@app.get("/checkout")
async def checkout_page():
    return FileResponse(_STATIC / "checkout.html")
