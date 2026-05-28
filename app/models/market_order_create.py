from sqlmodel import SQLModel, Field


class MarketOrderCreate(SQLModel):
    product_id: int = Field(
        ..., description="ID of the product this order is for matching with NADO"
    )
    amount: int = Field(..., description="Amount in tokens")
    is_buy: int = Field(
        ..., description="True stands for Long/Buy, False stands for Short/Sell"
    )
    is_market: int = Field(default=True, description="True -> IoC(Market Like Order)")
