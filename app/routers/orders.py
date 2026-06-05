import logging

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status
from starlette.exceptions import HTTPException

from app.core.auth import get_current_wallet
from app.core.db_helper import db_helper
from app.crud.limit_orders_crud import get_user_open_orders
from app.crud.user_crud import get_user_by_address
from app.models.close_market_order import CloseMarketOrder
from app.models.limit_orders_models import (
    LimitOrderCancel,
    LimitOrderCreate,
    LimitOrderResponse,
    ProductBracketsResponse,
)
from app.models.market_order_create import BatchOrderCreate, MarketOrderCreate
from app.services.batch_order_service import place_batch_order
from app.services.cancel_limit_orders_service import cancel_limit_orders_service
from app.services.close_order_service import execute_close_order
from app.services.place_limit_order_service import place_limit_order_service
from app.services.place_market_order import place_market_order
from app.services.position_brackets_service import get_active_position_brackets

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.get(
    "/limit-orders",
    response_model=list[LimitOrderResponse],
    status_code=status.HTTP_200_OK,
)
async def get_limits_orders(
    main_wallet: str = Depends(get_current_wallet),
    session: AsyncSession = Depends(db_helper.session_dependency),
):
    user = await get_user_by_address(session, main_wallet)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    orders = await get_user_open_orders(session, user.id)
    return orders


@router.get(
    "/position-brackets",
    response_model=list[ProductBracketsResponse],
    status_code=status.HTTP_200_OK,
)
async def get_position_brackets(
    main_wallet: str = Depends(get_current_wallet),
    session: AsyncSession = Depends(db_helper.session_dependency),
):
    user = await get_user_by_address(session, main_wallet)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return await get_active_position_brackets(
        session=session,
        user_id=user.id,
        main_wallet=main_wallet,
    )


@router.post("/limit-open", status_code=status.HTTP_201_CREATED)
async def limit_open_order(
    payload: LimitOrderCreate,
    main_wallet: str = Depends(get_current_wallet),
    session: AsyncSession = Depends(db_helper.session_dependency),
):
    user = await get_user_by_address(session, main_wallet)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        result = await place_limit_order_service(
            payload=payload, main_wallet=main_wallet, user_id=user.id, session=session
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "Unexpected error placing limit order for wallet %s", main_wallet
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Exchange gateway error: {str(e)}",
        )
    return {"status": "success", "data": result}


@router.post("/cancel-limit", status_code=status.HTTP_201_CREATED)
async def cancel_limit_order(
    payload: LimitOrderCancel,
    main_wallet: str = Depends(get_current_wallet),
    session: AsyncSession = Depends(db_helper.session_dependency),
):
    user = await get_user_by_address(session, main_wallet)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        result = await cancel_limit_orders_service(
            payload=payload, main_wallet=main_wallet, session=session
        )
    except Exception as e:
        logger.exception(
            "Unexpected error placing limit order for wallet %s", main_wallet
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Exchange gateway error: {str(e)}",
        )
    return {"status": "success", "data": result}


@router.post("/market", status_code=status.HTTP_201_CREATED)
async def create_market_order(
    payload: MarketOrderCreate,
    main_wallet: str = Depends(get_current_wallet),
    session: AsyncSession = Depends(db_helper.session_dependency),
):
    try:
        result = await place_market_order(
            payload=payload, main_wallet=main_wallet, session=session
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error placing order for wallet %s", main_wallet)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Exchange gateway error: {str(e)}",
        )
    return {"status": "success", "data": result}


@router.post("/batch", status_code=status.HTTP_201_CREATED)
async def create_batch_order(
    payload: BatchOrderCreate,
    main_wallet: str = Depends(get_current_wallet),
    session: AsyncSession = Depends(db_helper.session_dependency),
):
    """
    Place multiple market orders atomically.
    Splits account balance across selected assets.
    """
    try:
        result = await place_batch_order(
            payload=payload,
            main_wallet=main_wallet,
            session=session,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error in batch order for wallet %s", main_wallet)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

    return result


@router.post("/close", status_code=status.HTTP_201_CREATED)
async def close_order(
    payload: CloseMarketOrder,
    main_wallet: str = Depends(get_current_wallet),
    session: AsyncSession = Depends(db_helper.session_dependency),
):
    try:
        result = await execute_close_order(
            payload=payload, main_wallet=main_wallet, session=session
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error in close order for wallet %s", main_wallet)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

    return result
