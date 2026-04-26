from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import (
    analytics, ask, costs, crawl, curated, demo_questions,
    gaplist, guardrails, index, insights, prompt, qlog, recommendations,
    search, system_health, tenants,
)
from storage.postgres import create_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    yield


app = FastAPI(title="Answerer Service", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://admin-console-848760828618.us-central1.run.app"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Widget-Key", "X-Service-Key"],
)

app.include_router(tenants.router)
app.include_router(demo_questions.router)
app.include_router(crawl.router)
app.include_router(index.router)
app.include_router(guardrails.router)
app.include_router(curated.router)
app.include_router(qlog.router)
app.include_router(analytics.router)
app.include_router(insights.router)
app.include_router(costs.router)
app.include_router(recommendations.router)
app.include_router(gaplist.router)
app.include_router(prompt.router)
app.include_router(ask.router)
app.include_router(search.router)
app.include_router(system_health.router)
