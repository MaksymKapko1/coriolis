import logging
import time
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession
from starlette import status
from starlette.exceptions import HTTPException

from app.core.config import settings
from app.crud.limit_orders_crud import save_limit_order
from app.models.limit_orders_models import LimitOrderCreate
from app.nado_client import NadoClient
from app.services.match_user_with_linksigner import get_subaccount_and_signer

logger = logging.getLogger(__name__)


async def place_limit_order_service(
    payload: LimitOrderCreate,
    main_wallet: str,
    user_id: UUID,
    session: AsyncSession,
) -> dict:
    linked_signer_address, private_key = await get_subaccount_and_signer(
        main_wallet, session
    )
    client = NadoClient(network=settings.nado_network, private_key=private_key)

    logger.info(
        "Placing limit order | wallet=%s | signer=%s | product=%s | price=%s | "
        "notional=%s | side=%s | tp=%s | sl=%s",
        main_wallet,
        linked_signer_address,
        payload.product_id,
        payload.price_usd,
        payload.notional_usd,
        "buy" if payload.is_buy else "sell",
        payload.take_profit_price,
        payload.stop_loss_price,
    )

    result = client.place_limit_order(
        product_id=payload.product_id,
        price_usd=payload.price_usd,
        notional_usd=payload.notional_usd,
        is_buy=payload.is_buy,
        sender_address=main_wallet,
    )

    if result.status != "success":
        logger.error("Nado rejected order | error=%s", result.error)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Order rejected by exchange: {result.error}",
        )

    digest = result.data.get("digest") if result.data else None
    if not digest:
        logger.error(
            "Order accepted but digest missing | exchange response=%s",
            result.data,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Order accepted but no digest returned",
        )

    order = await save_limit_order(
        session=session,
        user_id=user_id,
        product_id=payload.product_id,
        symbol=payload.symbol or str(payload.product_id),
        digest=digest,
        price_usd=payload.price_usd,
        notional_usd=payload.notional_usd,
        is_buy=payload.is_buy,
        take_profit_price=payload.take_profit_price,
        stop_loss_price=payload.stop_loss_price,
    )

    response: dict = {"status": result.status, "data": result.data}

    if payload.take_profit_price:
        logger.info("Placing TP trigger | price=%s", payload.take_profit_price)
        time.sleep(0.5)
        tp_result = client.place_trigger_order(
            product_id=payload.product_id,
            price_usd=payload.take_profit_price,
            notional_usd=payload.notional_usd,
            is_buy=not payload.is_buy,
            trigger_price_usd=payload.take_profit_price,
            dependency_digest=digest,
            trigger_type=(
                "last_price_above" if payload.is_buy else "last_price_below"
            ),
            sender_address=main_wallet,
            reduce_only=True,
        )
        response["tp_status"] = tp_result.status
        response["tp_error"] = tp_result.error
        if tp_result.status != "success":
            logger.error("TP placement failed | error=%s", tp_result.error)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"TP placement failed: {tp_result.error}",
            )
        tp_digest = tp_result.data.get("digest") if tp_result.data else None
        logger.info("TP placed | digest=%s", tp_digest)
        response["tp_data"] = tp_result.data
        if tp_digest:
            order.tp_digest = tp_digest
            session.add(order)
            await session.commit()

    if payload.stop_loss_price:
        logger.info("Placing SL trigger | price=%s", payload.stop_loss_price)
        time.sleep(0.5)
        sl_result = client.place_trigger_order(
            product_id=payload.product_id,
            price_usd=payload.stop_loss_price,
            notional_usd=payload.notional_usd,
            is_buy=not payload.is_buy,
            trigger_price_usd=payload.stop_loss_price,
            dependency_digest=digest,
            trigger_type=(
                "last_price_below" if payload.is_buy else "last_price_above"
            ),
            sender_address=main_wallet,
            reduce_only=True,
        )
        response["sl_status"] = sl_result.status
        response["sl_error"] = sl_result.error
        if sl_result.status != "success":
            logger.warning("SL placement failed | error=%s", sl_result.error)
        else:
            sl_digest = sl_result.data.get("digest") if sl_result.data else None
            logger.info("SL placed | digest=%s", sl_digest)
            response["sl_data"] = sl_result.data
            if sl_digest:
                order.sl_digest = sl_digest
                session.add(order)
                await session.commit()

    return response
