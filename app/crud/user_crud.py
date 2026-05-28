import logging

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.user import User

logger = logging.getLogger(__name__)


async def get_user_by_address(session: AsyncSession, main_wallet: str) -> User:
    stmt = select(User).where(User.address == main_wallet)
    result = await session.exec(stmt)
    return result.one_or_none()


async def create_user(session: AsyncSession, main_wallet: str) -> User:
    user = User(main_wallet=main_wallet, is_approved=True)
    session.add(user)
    return user
