from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.market_order_create import MarketOrderCreate
from app.services.match_user_with_linksigner import get_subaccount_and_signer
from nado_protocol.client import create_nado_client

logger = logging.getLogger(__name__)


async def place_market_order(
    payload: MarketOrderCreate,
    main_wallet: str,
    session: AsyncSession,
) -> dict:
    linked_signer_address, private_key = await get_subaccount_and_signer(
        main_wallet, session
    )
    client = create_nado_client(
        settings.nado_network,
        private_key,
    )
