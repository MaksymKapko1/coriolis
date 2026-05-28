import logging

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status
from starlette.exceptions import HTTPException

from app.core.security import crypto_manager
from app.crud.user_crud import get_user_by_address
from app.models.user import User

logger = logging.getLogger(__name__)


async def get_subaccount_and_signer(
    main_wallet: str, session: AsyncSession
) -> tuple[str, str]:
    user = await get_user_by_address(session, main_wallet)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with {main_wallet} hasn't been linked yet.",
        )

    if not user.is_approved:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access restricted, user is not approved.",
        )

    if not user.encrypted_linked_signer_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User does not have linked signer key",
        )

    try:
        decrypted_private_key = crypto_manager.decrypt_key(
            user.encrypted_linked_signer_key
        )
    except ValueError:
        logger.error("Failed to decrypt linked signer key for wallet %s", main_wallet)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error while decrypting linked signer key",
        )
    return user.linked_signer_address, decrypted_private_key
