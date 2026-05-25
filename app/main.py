from fastapi import FastAPI, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db_helper import db_helper

app = FastAPI(
    title="Coriolis Trading Terminal",
    version="0.1.0"
)

@app.get("/")
async def root():
    return {"status": "Coriolis API is running successfully"}


# Эндпоинт для проверки связи с базой данных
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