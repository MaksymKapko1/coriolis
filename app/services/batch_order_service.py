import logging

from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.market_order_create import BatchOrderCreate
from app.nado_client import NadoClient
from app.services.match_user_with_linksigner import get_subaccount_and_signer

logger = logging.getLogger(__name__)


async def place_batch_order(
    payload: BatchOrderCreate,
    main_wallet: str,
    session: AsyncSession,
) -> dict:
    linked_signer_address, private_key = await get_subaccount_and_signer(
        main_wallet, session
    )

    client = NadoClient(network=settings.nado_network, private_key=private_key)

    orders = [
        {
            "product_id": item.product_id,
            "notional_usd": item.notional_usd,
            "is_buy": item.is_buy,
        }
        for item in payload.orders
    ]

    result = client.place_batch_orders(
        orders=orders,
        sender_address=main_wallet,
        stop_on_failure=payload.stop_on_failure,
    )

    if result.status != "success":
        logger.error("Batch order rejected | error=%s", result.error)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Batch rejected: {result.error}",
        )

    return {"status": result.status, "data": result.data}
