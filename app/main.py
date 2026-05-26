from fastapi import FastAPI, Depends, APIRouter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.cors import CORSMiddleware



from app.core.db_helper import db_helper

app = FastAPI(
    title="Coriolis Trading Terminal",
    version="0.1.0"
)

app.include_router(users.router, prefix=settings.api_v1_prefix)

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


