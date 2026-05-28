import uuid
from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class UserBase(SQLModel):
    address: str = Field(unique=True, index=True)
    linked_signer_address: str | None = Field(default=None)
    is_approved: bool = Field(default=False)

class User(UserBase, table=True):
    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    encrypted_linked_signer_key: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))

class UserResponse(UserBase):
    id: uuid.UUID
    created_at: datetime
