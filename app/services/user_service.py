import logging

from eth_account import Account
from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import crypto_manager
from app.crud.user_crud import get_user_by_address, create_user
from app.models.user import User

logger = logging.getLogger(__name__)


class UserService:
    @staticmethod
    async def process_linked_signer(
        session: AsyncSession, main_wallet: str, private_key: str
    ) -> User:
        """
        Validates private key, encrypts it,
        and saves/updates user in database.
        """

        try:
            pk = private_key if private_key.startswith("0x") else f"0x{private_key}"
            account = Account.from_key(pk)
            linked_signer_address = account.address
        except Exception as e:
            logger.error("Invalid private key provided: %s", e)

            raise HTTPException(
                status_code=400, detail="Invalid linked signer private key"
            )
        # TODO:get main_wallet_address from JWT token (dependency get_current_user)
        user = await get_user_by_address(session, main_wallet)

        if not user:
            user = await create_user(session, main_wallet)

        user.linked_signer_address = linked_signer_address

        user.encrypted_linked_signer_key = crypto_manager.encrypt_key(pk)
        await session.commit()
        await session.refresh(user)

        logger.info(
            "Successfully linked signer %s for user %s",
            linked_signer_address,
            user.address,
        )

        return user
