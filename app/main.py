from fastapi import FastAPI, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.cors import CORSMiddleware

from app.core.db_helper import db_helper

app = FastAPI(
    title="Coriolis Trading Terminal",
    version="0.1.0"
)

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


@app.get("/db-check")
async def check_db_connection(
    session: AsyncSession = Depends(db_helper.session_dependency)
):
    try:
        # Выполняем простейший сырой SQL-запрос для проверки коннекта
        result = await session.execute(text("SELECT 1"))
        scalar = result.scalar()
        return {
            "status": "healthy",
            "database": "connected successfully",
            "test_query_result": scalar
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "database": "connection failed",
            "error": str(e)
        }