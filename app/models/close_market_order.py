from sqlmodel import SQLModel, Field


class CloseMarketOrder(SQLModel):
    product_id: int = Field(...)
    sender_address: str = Field(...)
    subaccount_name: str = Field(default="default")
