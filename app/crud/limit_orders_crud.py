from uuid import UUID

from sqlalchemy import or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.limit_orders_models import LimitOrder


async def save_limit_order(
    session: AsyncSession,
    user_id: UUID,
    product_id: int,
    symbol: str,
    digest: str,
    price_usd: float,
    notional_usd: float,
    is_buy: bool,
    take_profit_price: float | None = None,
    stop_loss_price: float | None = None,
) -> LimitOrder:
    order = LimitOrder(
        user_id=user_id,
        product_id=product_id,
        symbol=symbol,
        digest=digest,
        price_usd=price_usd,
        notional_usd=notional_usd,
        is_buy=is_buy,
        take_profit_price=take_profit_price,
        stop_loss_price=stop_loss_price,
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)
    return order


async def get_user_open_orders(
    session: AsyncSession, user_id: UUID
) -> list[LimitOrder]:
    stmt = select(LimitOrder).where(
        LimitOrder.user_id == user_id,
        LimitOrder.status == "open",
    )
    result = await session.exec(stmt)
    return list(result.all())


async def get_user_bracket_orders(
    session: AsyncSession, user_id: UUID
) -> list[LimitOrder]:
    """Orders with TP/SL that may still be active (incl. filled limits with triggers)."""
    stmt = (
        select(LimitOrder)
        .where(
            LimitOrder.user_id == user_id,
            LimitOrder.status.in_(["open", "partially_filled", "filled"]),
            or_(
                LimitOrder.take_profit_price.isnot(None),
                LimitOrder.stop_loss_price.isnot(None),
            ),
        )
        .order_by(LimitOrder.created_at.desc())
    )
    result = await session.exec(stmt)
    return list(result.all())


async def get_order_by_digest(session: AsyncSession, digest: str) -> LimitOrder | None:
    stmt = select(LimitOrder).where(LimitOrder.digest == digest)
    result = await session.exec(stmt)
    return result.one_or_none()


async def mark_orders_cancelled(session: AsyncSession, digests: list[str]) -> None:
    for digest in digests:
        order = await get_order_by_digest(session, digest)
        if order:
            order.status = "cancelled"
            session.add(order)
    await session.commit()
