import logging

from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status
from starlette.exceptions import HTTPException

from app.core.config import settings
from app.crud.limit_orders_crud import mark_orders_cancelled
from app.models.limit_orders_models import LimitOrderCancel
from app.nado_client import NadoClient
from app.services.match_user_with_linksigner import get_subaccount_and_signer

logger = logging.getLogger(__name__)


async def cancel_limit_orders_service(
    payload: LimitOrderCancel, main_wallet: str, session: AsyncSession
) -> dict:
    linked_signer_address, private_key = await get_subaccount_and_signer(
        main_wallet, session
    )
    client = NadoClient(network=settings.nado_network, private_key=private_key)

    result = client.cancel_orders(
        product_ids=payload.product_ids,
        digests=payload.digests,
        sender_address=main_wallet,
    )

    if result.status != "success":
        logger.error("Nado rejected limit order | error=%s", result.error)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Order rejected by exchange: {result.error}",
        )

    await mark_orders_cancelled(session, payload.digests)

    return {"status": result.status, "data": result.data}
