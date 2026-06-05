import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import SQLModel
from starlette.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.db_helper import db_helper
from app.routers import orders, users_router
from app.routers.indexes_router import router as indexes_router
from app.services.nado_ws_service import nado_ws_listener, sync_orders_loop

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Checking database tables...")
    from app.models.trading_indexes import TradingIndexes, TradingIndexesAsset  # noqa

    async with db_helper.engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    logger.info("Database setup complete.")

    async with db_helper.session_factory() as session:
        from app.seed.system_indexes import seed_system_indexes

        await seed_system_indexes(session)
    logger.info("System indexes seeded.")
    ws_task = asyncio.create_task(nado_ws_listener())
    sync_task = asyncio.create_task(sync_orders_loop())
    yield
    ws_task.cancel()
    sync_task.cancel()
    for task in (ws_task, sync_task):
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Coriolis Trading Terminal",
    version="0.1.0",
    lifespan=lifespan,
)


app.include_router(users_router.router, prefix=settings.api_v1_prefix)
app.include_router(orders.router, prefix=settings.api_v1_prefix)
app.include_router(indexes_router, prefix="/api/v1")

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
