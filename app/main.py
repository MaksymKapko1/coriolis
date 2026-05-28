import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import SQLModel
from starlette.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.db_helper import db_helper
from app.routers import users_router, orders

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Checking database tables...")
    async with db_helper.engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    logger.info("Database setup complete.")
    yield


app = FastAPI(
    title="Coriolis Trading Terminal",
    version="0.1.0",
    lifespan=lifespan,
)


app.include_router(users_router.router, prefix=settings.api_v1_prefix)
app.include_router(orders.router, prefix=settings.api_v1_prefix)

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"status": "Coriolis API is running successfully"}
