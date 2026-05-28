import logging

from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status
from starlette.exceptions import HTTPException

from app.models.market_order_create import MarketOrderCreate
from app.services.match_user_with_linksigner import get_subaccount_and_signer
from app.nado_client import NadoClient

logger = logging.getLogger(__name__)


async def place_market_order(
    payload: MarketOrderCreate,
    main_wallet: str,
    session: AsyncSession,
) -> dict:
    linked_signer_address, private_key = await get_subaccount_and_signer(
        main_wallet, session
    )
    client = NadoClient(
        network=settings.nado_network, private_key=private_key, amount=to
    )

    amount = to_x18(payload.amount) if payload.is_buy else -to_x18(payload.amount)
    logger.info(
        "Placing market order | wallet=%s | signer=%s | product=%s | side=%s | amount=%s",
        main_wallet,
        linked_signer_address,
        payload.product_id,
        "buy" if payload.is_buy else "sell",
        amount,
    )

    result = client.place_market_order(
        product_id=payload.product_id,
        amount=amount,
        sender_address=linked_signer_address,
    )

    if result.status != "success":
        logger.error("Nado rejected order | error=%s", result.error)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Order rejected by exchange: {result.error}",
        )

    return {"status": result.status, "data": result.data}
