from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db_helper import db_helper
from app.models.user import UserResponse
from app.schemas.user import LinkSignerRequest
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["Users"])

@router.post("/link-signer", response_model=UserResponse)
async def setup_linked_signer(payload: LinkSignerRequest, session: AsyncSession = Depends(db_helper.session_dependency)):
    user = await UserService.process_linked_signer(
        session=session,
        main_wallet=payload.main_wallet_address,
        private_key=payload.linked_signer_private_key,
    )

    return user
