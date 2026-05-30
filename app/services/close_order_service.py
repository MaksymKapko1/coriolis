import logging

from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status
from starlette.exceptions import HTTPException

from app.core.config import settings
from app.models.close_market_order import CloseMarketOrder
from app.nado_client import NadoClient
from app.services.match_user_with_linksigner import get_subaccount_and_signer

logger = logging.getLogger(__name__)


async def execute_close_order(
    payload: CloseMarketOrder, main_wallet: str, session: AsyncSession
):
    linked_signer_address, private_key = await get_subaccount_and_signer(
        main_wallet, session
    )
    client = NadoClient(network=settings.nado_network, private_key=private_key)
    result = client.close_position(
        product_id=payload.product_id, sender_address=main_wallet
    )

    if result.status != "success":
        logger.error("Nado rejected order | error=%s", result.error)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Order rejected by exchange: {result.error}",
        )

    return {"status": result.status, "data": result.data}
