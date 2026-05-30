from typing import List

from sqlmodel import SQLModel, Field


class MarketOrderCreate(SQLModel):
    product_id: int = Field(
        ..., description="ID of the product this order is for matching with NADO"
    )
    amount: float = Field(..., description="Amount in tokens")
    is_buy: bool = Field(
        ..., description="True stands for Long/Buy, False stands for Short/Sell"
    )
    is_market: bool = Field(default=True, description="True -> IoC(Market Like Order)")


class BatchOrderCreate(SQLModel):
    orders: List[MarketOrderCreate] = Field(
        ..., description="List of orders to place atomically"
    )
    stop_on_failure: bool = Field(default=False)
