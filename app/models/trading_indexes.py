import uuid
from datetime import datetime, UTC
from typing import Optional, List
from uuid import UUID

from sqlmodel import SQLModel, Field, Relationship


# --- INDEX ASSET MODELS ---
class TradingIndexesAssetBase(SQLModel):
    product_id: int = Field(...)
    symbol: str = Field(..., min_length=1)


class TradingIndexesAssetCreate(TradingIndexesAssetBase):
    pass


class TradingIndexesAssetResponse(TradingIndexesAssetBase):
    id: int
    index_id: int
    created_at: datetime


class TradingIndexesAsset(TradingIndexesAssetBase, table=True):
    __tablename__ = "trading_index_assets"

    id: Optional[int] = Field(default=None, primary_key=True)
    index_id: int = Field(foreign_key="trading_indexes.id", ondelete="CASCADE")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    index: "TradingIndexes" = Relationship(back_populates="assets")


# --- TRADING INDEX MODELS ---
class TradingIndexesBase(SQLModel):
    name: str = Field(..., min_length=1, max_length=100)


class TradingIndexesCreate(TradingIndexesBase):
    assets: List[TradingIndexesAssetCreate]


class TradingIndexesResponse(TradingIndexesBase):
    id: int
    user_id: Optional[uuid.UUID]
    is_system: bool
    created_at: datetime
    updated_at: datetime

    assets: List[TradingIndexesAssetResponse]


class TradingIndexes(TradingIndexesBase, table=True):
    __tablename__ = "trading_indexes"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[UUID] = Field(default=None, foreign_key="users.id", nullable=True)
    is_system: bool = Field(default=False, nullable=False)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC).replace(tzinfo=None)
    )

    assets: List[TradingIndexesAsset] = Relationship(
        back_populates="index", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
