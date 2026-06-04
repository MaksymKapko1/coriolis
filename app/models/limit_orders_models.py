from datetime import datetime, UTC
from typing import Optional
from uuid import UUID

from sqlmodel import Field, SQLModel


class LimitOrder(SQLModel, table=True):
    __tablename__ = "limit_orders"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)

    product_id: int = Field(...)
    symbol: str = Field(...)
    digest: str = Field(..., unique=True, index=True)

    price_usd: float = Field(...)
    notional_usd: float = Field(...)
    is_buy: bool = Field(...)

    status: str = Field(default="open")  # open | cancelled | filled
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


class LimitOrderResponse(SQLModel):
    id: int
    product_id: int
    symbol: str
    digest: str
    price_usd: float
    notional_usd: float
    is_buy: bool
    status: str
    created_at: datetime


class LimitOrderCreate(SQLModel):
    product_id: int = Field(..., description="Product ID")
    price_usd: float = Field(..., description="Price in USD")
    notional_usd: float = Field(..., description="notional_usd amount")
    is_buy: bool = Field(default=True, description="Is Buy?")
    take_profit_price: float | None = Field(
        default=None, description="Take Profit Price"
    )
    stop_loss_price: float | None = Field(default=None, description="Stop Loss Price")


class LimitOrderCancel(SQLModel):
    product_ids: list[int] = Field(..., description="Product ID")
    digests: list[str] = Field(..., description="Digests")
