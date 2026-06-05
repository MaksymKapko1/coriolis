import asyncio
import json
import logging
from typing import Any

import requests
import websockets
from sqlmodel import select

from app.core.config import settings
from app.core.db_helper import db_helper
from app.models.limit_orders_models import LimitOrder
from app.models.user import User
from app.nado_client.client import NETWORK_CONFIGS
from app.nado_client.utils import subaccount_to_hex

logger = logging.getLogger(__name__)

WS_URLS = {
    "testnet": "wss://gateway.test.nado.xyz/v1/subscribe",
    "mainnet": "wss://gateway.prod.nado.xyz/v1/subscribe",
}

SUBSCRIBE_REFRESH_SECONDS = 20
SYNC_ORDERS_INTERVAL_SECONDS = 30


def _normalize_digest(digest: str | None) -> str | None:
    if not digest:
        return None
    return digest.lower() if digest.startswith("0x") else f"0x{digest.lower()}"


def _gateway_query(query_type: str, params: dict[str, Any]) -> dict[str, Any]:
    gateway_url = NETWORK_CONFIGS[settings.nado_network]["gateway_url"]
    payload = {"type": query_type, **params}
    resp = requests.post(f"{gateway_url}/query", json=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "success":
        raise RuntimeError(data.get("error") or "query failed")
    return data["data"]


def fetch_open_digests_on_exchange(sender_address: str, product_id: int) -> set[str]:
    """Digests of orders still open on Nado for this subaccount + product."""
    sender_hex = subaccount_to_hex(sender_address, "default")
    try:
        data = _gateway_query(
            "orders",
            {"sender": sender_hex, "product_ids": [product_id]},
        )
    except Exception as e:
        logger.warning(
            "Failed to query open orders | product=%s | error=%s",
            product_id,
            e,
        )
        return set()

    open_digests: set[str] = set()
    for product_block in data.get("product_orders", []):
        if product_block.get("product_id") != product_id:
            continue
        for order in product_block.get("orders", []):
            digest = _normalize_digest(order.get("digest"))
            unfilled = int(order.get("unfilled_amount", "0"))
            if digest and unfilled > 0:
                open_digests.add(digest)
    return open_digests


def fetch_open_perp_product_ids(sender_address: str) -> set[int]:
    """Product IDs with a non-zero perp position on Nado."""
    sender_hex = subaccount_to_hex(sender_address, "default")
    try:
        data = _gateway_query("subaccount_info", {"subaccount": sender_hex})
    except Exception as e:
        logger.warning(
            "Failed to query subaccount for positions | error=%s",
            e,
        )
        return set()

    open_products: set[int] = set()
    for balance in data.get("perp_balances", []):
        product_id = balance.get("product_id")
        if product_id is None:
            continue
        amount = int(balance.get("balance", {}).get("amount", "0"))
        if amount != 0:
            open_products.add(int(product_id))
    return open_products


async def get_subaccounts_to_watch() -> list[str]:
    """Subaccounts that have open or partially filled limit orders in our DB."""
    async with db_helper.session_context() as session:
        stmt = select(LimitOrder).where(
            LimitOrder.status.in_(["open", "partially_filled"])
        )
        result = await session.exec(stmt)
        orders = list(result.all())

        user_ids = list({o.user_id for o in orders})
        subaccounts: list[str] = []
        for user_id in user_ids:
            user = await session.get(User, user_id)
            if user:
                subaccounts.append(subaccount_to_hex(user.address, "default"))
        return list(dict.fromkeys(subaccounts))


async def subscribe_fill_streams(ws: Any, subaccounts: list[str], base_id: int = 1) -> None:
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
                    "id": base_id + i,
                }
            )
        )
        logger.info("Subscribed to fill stream | subaccount=%s", subaccount[:18])


async def handle_fill_event(event: dict) -> None:
    order_digest = _normalize_digest(
        event.get("order_digest") or event.get("digest")
    )
    if not order_digest:
        return

    remaining_qty = abs(int(event.get("remaining_qty", "0")))

    async with db_helper.session_context() as session:
        stmt = select(LimitOrder).where(
            LimitOrder.status.in_(["open", "partially_filled", "filled"])
        )
        result = await session.exec(stmt)
        order = next(
            (
                o
                for o in result.all()
                if _normalize_digest(o.digest) == order_digest
            ),
            None,
        )
        if not order:
            return

        filled_qty = abs(int(event.get("filled_qty", "0")))
        price_x18 = int(event.get("price", "0"))
        fill_price = price_x18 / 1e18

        if filled_qty > 0 and fill_price > 0:
            order.filled_notional += (filled_qty / 1e18) * fill_price
            order.avg_fill_price = fill_price

        if remaining_qty == 0:
            order.status = "filled"
        else:
            order.status = "partially_filled"

        session.add(order)
        await session.commit()

        logger.info(
            "Fill event | digest=%s | status=%s | remaining=%s",
            order_digest,
            order.status,
            remaining_qty,
        )


async def handle_order_update_event(event: dict) -> None:
    """Handle order_update if we add authenticated WS later."""
    digest = _normalize_digest(event.get("digest"))
    reason = event.get("reason")

    if not digest or not reason:
        return

    async with db_helper.session_context() as session:
        stmt = select(LimitOrder).where(
            LimitOrder.status.in_(["open", "partially_filled", "filled"])
        )
        result = await session.exec(stmt)
        order = next(
            (
                o
                for o in result.all()
                if _normalize_digest(o.digest) == digest
            ),
            None,
        )
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


async def sync_orders_with_exchange() -> None:
    """
    Poll Nado gateway: if our DB says open but digest is gone from the book → filled.
    Fallback when WS fill subscription was missed.
    """
    async with db_helper.session_context() as session:
        stmt = select(LimitOrder).where(
            LimitOrder.status.in_(["open", "partially_filled"])
        )
        result = await session.exec(stmt)
        orders = list(result.all())

        for order in orders:
            user = await session.get(User, order.user_id)
            if not user:
                continue

            try:
                open_digests = await asyncio.to_thread(
                    fetch_open_digests_on_exchange,
                    user.address,
                    order.product_id,
                )
            except Exception:
                continue

            db_digest = _normalize_digest(order.digest)
            if db_digest and db_digest not in open_digests:
                order.status = "filled"
                session.add(order)
                logger.info(
                    "Sync: order no longer on book → filled | digest=%s | product=%s",
                    db_digest,
                    order.product_id,
                )

        await session.commit()


async def sync_orders_loop() -> None:
    while True:
        try:
            await sync_orders_with_exchange()
        except Exception as e:
            logger.exception("Order sync loop error: %s", e)
        await asyncio.sleep(SYNC_ORDERS_INTERVAL_SECONDS)


async def nado_ws_listener() -> None:
    """
    WebSocket listener: fill stream (no auth).
    Re-subscribes periodically so new subaccounts get fill events.
    order_update requires WS auth — use sync_orders_loop as fallback.
    """
    ws_url = WS_URLS.get(settings.nado_network)
    if not ws_url:
        logger.error("Unknown network: %s", settings.nado_network)
        return

    subscribe_id = 1

    while True:
        try:
            async with websockets.connect(ws_url, ping_interval=30) as ws:
                logger.info("Connected to Nado WebSocket | url=%s", ws_url)

                subaccounts = await get_subaccounts_to_watch()
                if subaccounts:
                    await subscribe_fill_streams(ws, subaccounts, base_id=subscribe_id)
                    subscribe_id += len(subaccounts) + 100
                else:
                    logger.info("No subaccounts to watch yet (no open orders in DB)")

                loop = asyncio.get_running_loop()
                last_refresh = loop.time()

                while True:
                    timeout = max(
                        1.0,
                        SUBSCRIBE_REFRESH_SECONDS - (loop.time() - last_refresh),
                    )
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    except TimeoutError:
                        subaccounts = await get_subaccounts_to_watch()
                        if subaccounts:
                            await subscribe_fill_streams(
                                ws, subaccounts, base_id=subscribe_id
                            )
                            subscribe_id += len(subaccounts) + 100
                            logger.debug(
                                "Refreshed fill subscriptions | count=%s",
                                len(subaccounts),
                            )
                        last_refresh = loop.time()
                        continue

                    if isinstance(message, bytes):
                        continue
                    if not message or not str(message).strip():
                        continue

                    try:
                        event = json.loads(message)
                    except json.JSONDecodeError:
                        continue

                    event_type = event.get("type")
                    if event_type == "fill":
                        await handle_fill_event(event)
                    elif event_type == "order_update":
                        await handle_order_update_event(event)

        except websockets.exceptions.ConnectionClosed as e:
            logger.warning("WebSocket closed | %s | reconnecting in 5s", e)
            await asyncio.sleep(5)
        except Exception as e:
            logger.exception("WebSocket error | %s | reconnecting in 10s", e)
            await asyncio.sleep(10)
