import logging

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status
from starlette.exceptions import HTTPException

from app.core.auth import get_current_wallet
from app.core.db_helper import db_helper
from app.crud.indexes_crud import (
    create_index as crud_create_index,
)
from app.crud.indexes_crud import (
    delete_index,
    get_default_indexes,
    get_index_by_id,
    get_user_indexes,
    update_index,
)
from app.crud.user_crud import get_user_by_address
from app.models.trading_indexes import TradingIndexesCreate, TradingIndexesResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/indexes", tags=["Indexes"])


@router.get("/default", response_model=list[TradingIndexesResponse])
async def get_system_indexes(
    session: AsyncSession = Depends(db_helper.session_dependency),
):
    """Get all system/default indexes available to everyone."""
    return await get_default_indexes(session)


@router.get("/my", response_model=list[TradingIndexesResponse])
async def get_my_indexes(
    session: AsyncSession = Depends(db_helper.session_dependency),
    main_wallet: str = Depends(get_current_wallet),
):
    """Get all indexes created by the current user."""

    user = await get_user_by_address(session, main_wallet)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return await get_user_indexes(session, user.id)


@router.post(
    "/create-index",
    response_model=TradingIndexesResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_my_index(
    payload: TradingIndexesCreate,
    session: AsyncSession = Depends(db_helper.session_dependency),
    main_wallet: str = Depends(get_current_wallet),
):
    """Create a new index for the current user."""
    user = await get_user_by_address(session, main_wallet)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return await crud_create_index(session, payload, user.id)


@router.put("/my/{index_id}", response_model=TradingIndexesResponse)
async def update_my_index(
    index_id: int,
    payload: TradingIndexesCreate,
    main_wallet: str = Depends(get_current_wallet),
    session: AsyncSession = Depends(db_helper.session_dependency),
):
    """Update an existing index (name + assets)."""
    user = await get_user_by_address(session, main_wallet)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    db_index = await get_index_by_id(session, index_id)
    if not db_index:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Index not found"
        )
    if db_index.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not your index"
        )

    return await update_index(session, db_index, payload)


@router.delete("/my/{index_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_index(
    index_id: int,
    main_wallet: str = Depends(get_current_wallet),
    session: AsyncSession = Depends(db_helper.session_dependency),
):
    """Delete an index owned by the current user."""
    user = await get_user_by_address(session, main_wallet)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    db_index = await get_index_by_id(session, index_id)
    if not db_index:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Index not found"
        )
    if db_index.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not your index"
        )

    await delete_index(session, db_index)
