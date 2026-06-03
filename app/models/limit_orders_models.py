from sqlmodel import Field, SQLModel


class LimitOrderCreate(SQLModel):
    product_id: int = Field(..., description="Product ID")
    price_usd: float = Field(..., description="Price in USD")
    notional_usd: float = Field(..., description="notional_usd amount")
    is_buy: bool = Field(default=True, description="Is Buy?")


class LimitOrderCancel(SQLModel):
    product_ids: list[int] = Field(..., description="Product ID")
    digests: list[str] = Field(..., description="Digests")
