from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.trading_indexes import TradingIndexes, TradingIndexesAsset, TradingIndexesCreate


def _with_assets():
    return selectinload(TradingIndexes.assets)


async def get_user_indexes(session: AsyncSession, user_id) -> list[TradingIndexes]:
    stmt = select(TradingIndexes).where(
        TradingIndexes.user_id == user_id
    ).options(_with_assets())
    result = await session.exec(stmt)
    return result.all()


async def get_default_indexes(session: AsyncSession) -> list[TradingIndexes]:
    stmt = select(TradingIndexes).where(
        TradingIndexes.is_system == True
    ).options(_with_assets())
    result = await session.exec(stmt)
    return result.all()


async def get_index_by_id(session: AsyncSession, index_id: int) -> TradingIndexes | None:
    stmt = select(TradingIndexes).where(
        TradingIndexes.id == index_id
    ).options(_with_assets())
    result = await session.exec(stmt)
    return result.one_or_none()


async def create_index(
    session: AsyncSession,
    payload: TradingIndexesCreate,
    user_id,
) -> TradingIndexes:
    db_index = TradingIndexes(name=payload.name, user_id=user_id)
    session.add(db_index)
    await session.flush()

    for asset in payload.assets:
        db_asset = TradingIndexesAsset(
            index_id=db_index.id,
            product_id=asset.product_id,
            symbol=asset.symbol,
            weight=asset.weight,
        )
        session.add(db_asset)

    await session.commit()

    stmt = select(TradingIndexes).where(
        TradingIndexes.id == db_index.id
    ).options(_with_assets())
    result = await session.exec(stmt)
    return result.one()


async def update_index(
    session: AsyncSession,
    db_index: TradingIndexes,
    payload: TradingIndexesCreate,
) -> TradingIndexes:
    db_index.name = payload.name

    old_assets = await session.exec(
        select(TradingIndexesAsset).where(TradingIndexesAsset.index_id == db_index.id)
    )
    for asset in old_assets.all():
        await session.delete(asset)

    for asset in payload.assets:
        db_asset = TradingIndexesAsset(
            index_id=db_index.id,
            product_id=asset.product_id,
            symbol=asset.symbol,
            weight=asset.weight,
        )
        session.add(db_asset)

    await session.commit()

    stmt = select(TradingIndexes).where(
        TradingIndexes.id == db_index.id
    ).options(_with_assets())
    result = await session.exec(stmt)
    return result.one()


async def delete_index(session: AsyncSession, db_index: TradingIndexes) -> None:
    await session.delete(db_index)
    await session.commit()