from contextlib import asynccontextmanager

from fastapi import FastAPI

from routers import auth, payments, quota, tenants
from storage.postgres import create_tables


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    yield


app = FastAPI(title="Vendor Console API", version="1.0.0", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(tenants.router)
app.include_router(quota.router)
app.include_router(payments.router)
