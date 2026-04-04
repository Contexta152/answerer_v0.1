from contextlib import asynccontextmanager

from fastapi import FastAPI

from routers import analytics, ask, crawl, curated, guardrails, index, qlog, tenants
from storage.postgres import create_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    yield


app = FastAPI(title="Answerer Service", version="1.0.0", lifespan=lifespan)

app.include_router(tenants.router)
app.include_router(crawl.router)
app.include_router(index.router)
app.include_router(guardrails.router)
app.include_router(curated.router)
app.include_router(qlog.router)
app.include_router(analytics.router)
app.include_router(ask.router)
