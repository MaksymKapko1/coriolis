import logging

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status
from starlette.exceptions import HTTPException

from app.core.auth import get_current_wallet
from app.core.db_helper import db_helper
from app.models.market_order_create import MarketOrderCreate
from app.services.place_market_order import place_market_order

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orders", tags=["Orders"])


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
