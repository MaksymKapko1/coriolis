import asyncio
import logging
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.crud.limit_orders_crud import get_user_bracket_orders
from app.models.limit_orders_models import ProductBracketsResponse
from app.services.nado_ws_service import (
    _normalize_digest,
    fetch_open_digests_on_exchange,
    fetch_open_perp_product_ids,
)

logger = logging.getLogger(__name__)


async def get_active_position_brackets(
    session: AsyncSession,
    user_id: UUID,
    main_wallet: str,
) -> list[ProductBracketsResponse]:
    """
    TP/SL only for open perp positions, and only if trigger digests are still on Nado.
    """
    orders = await get_user_bracket_orders(session, user_id)
    open_products = await asyncio.to_thread(fetch_open_perp_product_ids, main_wallet)

    by_product: dict[int, ProductBracketsResponse] = {}
    for order in orders:
        if order.product_id not in open_products:
            continue
        if order.product_id in by_product:
            continue

        open_digests = await asyncio.to_thread(
            fetch_open_digests_on_exchange,
            main_wallet,
            order.product_id,
        )

        tp_digest = _normalize_digest(order.tp_digest)
        sl_digest = _normalize_digest(order.sl_digest)

        tp_live = tp_digest is not None and tp_digest in open_digests
        sl_live = sl_digest is not None and sl_digest in open_digests

        if not tp_live and not sl_live:
            continue

        by_product[order.product_id] = ProductBracketsResponse(
            product_id=order.product_id,
            take_profit_price=order.take_profit_price if tp_live else None,
            stop_loss_price=order.stop_loss_price if sl_live else None,
            tp_digest=order.tp_digest if tp_live else None,
            sl_digest=order.sl_digest if sl_live else None,
            order_status=order.status,
            limit_price_usd=order.price_usd,
        )

    return list(by_product.values())
