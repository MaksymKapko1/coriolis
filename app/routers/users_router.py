from fastapi import APIRouter, Depends
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth import get_current_wallet
from app.core.db_helper import db_helper
from app.crud.user_crud import get_user_by_address
from app.models.user import User, UserResponse
from app.schemas.user import LinkSignerRequest
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=UserResponse)
async def get_users_info(
    main_wallet: str = Depends(get_current_wallet),
    session: AsyncSession = Depends(db_helper.session_dependency),
):
    user = await get_user_by_address(session, main_wallet)
    return user or User(address=main_wallet, is_approved=False)


@router.post("/link-signer", response_model=UserResponse)
async def setup_linked_signer(
    payload: LinkSignerRequest,
    main_wallet_address: str = Depends(get_current_wallet),
    session: AsyncSession = Depends(db_helper.session_dependency),
):
    user = await UserService.process_linked_signer(
        session=session,
        main_wallet=main_wallet_address,
        private_key=payload.linked_signer_private_key,
    )

    return user
