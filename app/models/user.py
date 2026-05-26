from datetime import datetime, UTC
import uuid
from typing import Optional

from sqlmodel import Field, SQLModel


class UserBase(SQLModel):
    address: str = Field(unique=True, index=True)
    linked_signer_address: Optional[str] = Field(default=None)
    is_approved: bool = Field(default=False)

class User(UserBase):
    __tablename__ = "user"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    encrypted_linked_signer_key: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(datetime.UTC))

class UserResponse(UserBase):
    id: uuid.UUID
    created_at: datetime