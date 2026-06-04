import asyncio
import json
import logging

import websockets
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db_helper import db_helper
from app.core.config import settings
from app.models.limit_orders_models import LimitOrder
from app.nado_client.utils import subaccount_to_hex

logger = logging.getLogger(__name__)

WS_URLS = {
    "testnet": "wss://subscriptions.test.nado.xyz/ws",
    "mainnet": "wss://subscriptions.prod.nado.xyz/ws",
}


async def handle_fill_event(event: dict) -> None:
    """Update order status in DB when fill event arrives."""
    order_digest = event.get("order_digest")
    if not order_digest:
        return

    filled_qty = abs(int(event.get("filled_qty", "0")))
    remaining_qty = abs(int(event.get("remaining_qty", "0")))
    original_qty = abs(int(event.get("original_qty", "1")))
    price_x18 = int(event.get("price", "0"))
    fill_price = price_x18 / 1e18

    async with db_helper.session_context() as session:
        stmt = select(LimitOrder).where(LimitOrder.digest == order_digest)
        result = await session.exec(stmt)
        order = result.one_or_none()

        if not order:
            return

        order.filled_notional += (filled_qty / 1e18) * fill_price
        order.avg_fill_price = fill_price  # упрощённо, можно VWAP

        if remaining_qty == 0:
            order.status = "filled"
        else:
            order.status = "partially_filled"

        session.add(order)
        await session.commit()

        logger.info(
            "Order updated | digest=%s | status=%s | fill_price=%s",
            order_digest,
            order.status,
            fill_price,
        )


async def handle_order_update_event(event: dict) -> None:
    """Handle order_update: placed/filled/cancelled."""
    digest = event.get("digest")
    reason = event.get("reason")

    if not digest or not reason:
        return

    async with db_helper.session_context() as session:
        stmt = select(LimitOrder).where(LimitOrder.digest == digest)
        result = await session.exec(stmt)
        order = result.one_or_none()

        if not order:
            return

        if reason == "cancelled":
            order.status = "cancelled"
        elif reason == "filled":
            amount_remaining = abs(int(event.get("amount", "0")))
            order.status = "filled" if amount_remaining == 0 else "partially_filled"

            filled_price_x18 = int(event.get("filled_price", "0"))
            if filled_price_x18 > 0:
                order.avg_fill_price = filled_price_x18 / 1e18

        session.add(order)
        await session.commit()

        logger.info(
            "Order update | digest=%s | reason=%s | status=%s",
            digest,
            reason,
            order.status,
        )


async def get_active_subaccounts() -> list[str]:
    """Get all subaccounts that have open orders."""
    async with db_helper.session_context() as session:
        stmt = select(LimitOrder).where(LimitOrder.status == "open")
        result = await session.exec(stmt)
        orders = result.all()

    from app.models.user import User

    async with db_helper.session_context() as session:
        user_ids = list({o.user_id for o in orders})
        subaccounts = []
        for user_id in user_ids:
            user_result = await session.get(User, user_id)
            if user_result:
                subaccounts.append(subaccount_to_hex(user_result.address, "default"))
    return subaccounts


async def nado_ws_listener() -> None:
    """
    Main WebSocket listener loop.
    Subscribes to fill + order_update streams for all active subaccounts.
    Reconnects automatically on disconnect.
    """
    ws_url = WS_URLS.get(settings.nado_network)
    if not ws_url:
        logger.error("Unknown network: %s", settings.nado_network)
        return

    while True:
        try:
            async with websockets.connect(ws_url, ping_interval=30) as ws:
                logger.info("Connected to Nado WebSocket | url=%s", ws_url)

                subaccounts = await get_active_subaccounts()

                for i, subaccount in enumerate(subaccounts):
                    await ws.send(
                        json.dumps(
                            {
                                "method": "subscribe",
                                "stream": {
                                    "type": "fill",
                                    "product_id": None,
                                    "subaccount": subaccount,
                                },
                                "id": i + 1,
                            }
                        )
                    )
                    logger.info("Subscribed to fill | subaccount=%s", subaccount)

                async for message in ws:
                    event = json.loads(message)
                    event_type = event.get("type")

                    if event_type == "fill":
                        await handle_fill_event(event)
                    elif event_type == "order_update":
                        await handle_order_update_event(event)

        except websockets.exceptions.ConnectionClosed as e:
            logger.warning("WebSocket closed | reason=%s | reconnecting in 5s...", e)
            await asyncio.sleep(5)
        except Exception as e:
            logger.exception("WebSocket error: %s | reconnecting in 10s...", e)
            await asyncio.sleep(10)
