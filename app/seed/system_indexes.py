"""Predefined system trading indexes (is_system=True)."""

from dataclasses import dataclass

from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.trading_indexes import TradingIndexes, TradingIndexesAsset


@dataclass(frozen=True)
class SystemIndexAssetSeed:
    product_id: int
    symbol: str
    weight: float
    is_buy: bool


@dataclass(frozen=True)
class SystemIndexSeed:
    name: str
    assets: tuple[SystemIndexAssetSeed, ...]


SYSTEM_INDEXES: tuple[SystemIndexSeed, ...] = (
    SystemIndexSeed(
        name="BE",
        assets=(
            SystemIndexAssetSeed(2, "BTC-PERP", 0.5, True),
            SystemIndexAssetSeed(4, "ETH-PERP", 0.5, False),
        ),
    ),
    SystemIndexSeed(
        name="L1",
        assets=(
            SystemIndexAssetSeed(78, "NEAR-PERP", 0.125, True),
            SystemIndexAssetSeed(122, "TON-PERP", 0.125, True),
            SystemIndexAssetSeed(20, "MON-PERP", 0.125, True),
            SystemIndexAssetSeed(24, "SUI-PERP", 0.125, True),
            SystemIndexAssetSeed(2, "BTC-PERP", 0.5, False),
        ),
    ),
    SystemIndexSeed(
        name="Bear Market",
        assets=(
            SystemIndexAssetSeed(90, "WTI-PERP", 0.5, True),
            SystemIndexAssetSeed(2, "BTC-PERP", 0.5, False),
        ),
    ),
    SystemIndexSeed(
        name="Perps",
        assets=(
            SystemIndexAssetSeed(36, "LIT-PERP", 0.125, True),
            SystemIndexAssetSeed(16, "HYPE-PERP", 0.125, True),
            SystemIndexAssetSeed(80, "ONDO-PERP", 0.125, True),
            SystemIndexAssetSeed(48, "ASTER-PERP", 0.125, True),
            SystemIndexAssetSeed(4, "ETH-PERP", 0.5, False),
        ),
    ),
    SystemIndexSeed(
        name="ETH Max",
        assets=(
            SystemIndexAssetSeed(4, "ETH-PERP", 0.5, True),
            SystemIndexAssetSeed(8, "SOL-PERP", 0.1667, False),
            SystemIndexAssetSeed(86, "JUP-PERP", 0.1667, False),
            SystemIndexAssetSeed(30, "PUMP-PERP", 0.1666, False),
        ),
    ),
)


async def _replace_index_assets(
    session: AsyncSession, index: TradingIndexes, seed: SystemIndexSeed
) -> None:
    old_assets = await session.exec(
        select(TradingIndexesAsset).where(TradingIndexesAsset.index_id == index.id)
    )
    for asset in old_assets.all():
        await session.delete(asset)

    for asset in seed.assets:
        session.add(
            TradingIndexesAsset(
                index_id=index.id,
                product_id=asset.product_id,
                symbol=asset.symbol,
                weight=asset.weight,
                is_buy=asset.is_buy,
            )
        )


async def seed_system_indexes(session: AsyncSession) -> None:
    """Upsert predefined system indexes by name."""
    for seed in SYSTEM_INDEXES:
        stmt = (
            select(TradingIndexes)
            .where(TradingIndexes.is_system == True, TradingIndexes.name == seed.name)
            .options(selectinload(TradingIndexes.assets))
        )
        result = await session.exec(stmt)
        existing = result.one_or_none()

        if existing:
            await _replace_index_assets(session, existing, seed)
            continue

        index = TradingIndexes(name=seed.name, user_id=None, is_system=True)
        session.add(index)
        await session.flush()

        for asset in seed.assets:
            session.add(
                TradingIndexesAsset(
                    index_id=index.id,
                    product_id=asset.product_id,
                    symbol=asset.symbol,
                    weight=asset.weight,
                    is_buy=asset.is_buy,
                )
            )

    await session.commit()
