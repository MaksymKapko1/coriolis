from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import Field, SQLModel


class LimitOrder(SQLModel, table=True):
    __tablename__ = "limit_orders"

    id: int | None = Field(default=None, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)

    product_id: int = Field(...)
    symbol: str = Field(...)
    digest: str = Field(..., unique=True, index=True)

    price_usd: float = Field(...)
    notional_usd: float = Field(...)
    is_buy: bool = Field(...)

    take_profit_price: float | None = Field(default=None)
    stop_loss_price: float | None = Field(default=None)

    tp_digest: str | None = Field(default=None)
    sl_digest: str | None = Field(default=None)

    status: str = Field(default="open")  # open | cancelled | filled
    filled_notional: float = Field(default=0.0)
    avg_fill_price: float = Field(default=0.0)

    realized_pnl: float | None = Field(default=None)

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
    take_profit_price: float | None = None
    stop_loss_price: float | None = None
    tp_digest: str | None = None
    sl_digest: str | None = None


class ProductBracketsResponse(SQLModel):
    """Latest TP/SL per product from our limit-order + trigger records."""

    product_id: int
    take_profit_price: float | None = None
    stop_loss_price: float | None = None
    tp_digest: str | None = None
    sl_digest: str | None = None
    order_status: str | None = None
    limit_price_usd: float | None = None


class LimitOrderCreate(SQLModel):
    product_id: int = Field(..., description="Product ID")
    symbol: str | None = Field(default=None, description="Display symbol e.g. ETH-PERP")
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
