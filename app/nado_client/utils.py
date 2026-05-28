"""
Pure Python utilities extracted from nado-protocol SDK.
No pydantic dependency — compatible with both v1 and v2.
"""

import binascii
import random
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import IntEnum
from typing import Optional

# ---------------------------------------------------------------------------
# OrderType
# ---------------------------------------------------------------------------


class OrderType(IntEnum):
    DEFAULT = 0
    IOC = 1
    FOK = 2
    POST_ONLY = 3


# ---------------------------------------------------------------------------
# Expiration / Nonce
# ---------------------------------------------------------------------------


def get_expiration_timestamp(seconds_from_now: int) -> int:
    return int(time.time()) + seconds_from_now


def gen_order_nonce(
    recv_time_ms: Optional[int] = None, random_int: Optional[int] = None
) -> int:
    if recv_time_ms is None:
        recv_time_ms = int(
            (datetime.now(tz=timezone.utc) + timedelta(seconds=90)).timestamp() * 1000
        )
    if random_int is None:
        random_int = random.randint(0, 999)
    return (recv_time_ms << 20) + random_int


# ---------------------------------------------------------------------------
# Math
# ---------------------------------------------------------------------------


def to_x18(x: float) -> int:
    return int(Decimal(str(x)) * Decimal(10**18))


def mul_x18(x, y) -> int:
    return int(Decimal(str(x)) * Decimal(str(y)) / Decimal(10**18))


def round_x18(x, y) -> int:
    x, y = int(x), int(y)
    return x - x % y


# ---------------------------------------------------------------------------
# Bytes32 / Subaccount
# ---------------------------------------------------------------------------


def str_to_hex(s: str) -> str:
    return binascii.hexlify(s.encode()).decode()


def hex_to_bytes32(value) -> bytes:
    if isinstance(value, bytes):
        return value
    if value.startswith("0x"):
        value = value[2:]
    data = bytes.fromhex(value)
    return data + b"\x00" * (32 - len(data))


def bytes32_to_hex(b: bytes) -> str:
    if isinstance(b, bytes):
        return f"0x{b.hex()}"
    return b


def subaccount_to_bytes32(owner: str, name: str = "default") -> bytes:
    """Convert wallet address + subaccount name to bytes32."""
    return hex_to_bytes32(owner + str_to_hex(name))


def subaccount_to_hex(owner: str, name: str = "default") -> str:
    return bytes32_to_hex(subaccount_to_bytes32(owner, name))


# ---------------------------------------------------------------------------
# Order appendix
# ---------------------------------------------------------------------------

APPENDIX_VERSION = 1


def build_appendix(
    order_type: OrderType,
    reduce_only: bool = False,
    isolated: bool = False,
) -> int:
    appendix = 0
    appendix |= APPENDIX_VERSION & 0xFF  # bits 7..0: version
    if isolated:
        appendix |= 1 << 8  # bit 8: isolated
    appendix |= (int(order_type) & 0x3) << 9  # bits 10..9: order type
    if reduce_only:
        appendix |= 1 << 11  # bit 11: reduce only
    return appendix


# ---------------------------------------------------------------------------
# Verifying contract for place_order
# ---------------------------------------------------------------------------


def gen_order_verifying_contract(product_id: int) -> str:
    be_bytes = product_id.to_bytes(20, byteorder="big", signed=False)
    return "0x" + be_bytes.hex()
