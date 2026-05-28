"""
Minimal Nado HTTP client.
Handles market order placement without nado-protocol SDK dependency.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import requests

from app.nado_client.signing import sign_order
from app.nado_client.utils import (
    OrderType,
    build_appendix,
    gen_order_nonce,
    get_expiration_timestamp,
    mul_x18,
    round_x18,
    subaccount_to_bytes32,
    to_x18,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Network configs
# ---------------------------------------------------------------------------

NETWORK_CONFIGS = {
    "testnet": {
        "gateway_url": "https://gateway.test.nado.xyz/v1",
        "chain_id": 763373,
        "endpoint_addr": "0x698D87105274292B5673367DEC81874Ce3633Ac2",
    },
    "mainnet": {
        "gateway_url": "https://gateway.prod.nado.xyz/v1",
        "chain_id": 57073,
        "endpoint_addr": "0x05ec92D78ED421f3D3Ada77FFdE167106565974E",
    },
}

DEFAULT_SLIPPAGE = 0.005  # 0.5% — same as SDK default


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class OrderResult:
    status: str
    data: Optional[dict] = None
    error: Optional[str] = None
    error_code: Optional[int] = None


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class NadoClient:
    def __init__(self, network: str, private_key: str):
        config = NETWORK_CONFIGS.get(network)
        if not config:
            raise ValueError(f"Unknown network: {network}. Use 'testnet' or 'mainnet'.")

        self.gateway_url = config["gateway_url"]
        self.chain_id = config["chain_id"]
        self.endpoint_addr = config["endpoint_addr"]
        self.private_key = private_key
        self.session = requests.Session()
        self.session.headers.update({"Accept-Encoding": "gzip"})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def place_market_order(
        self,
        product_id: int,
        amount: int,
        sender_address: str,
        subaccount_name: str = "default",
        slippage: float = DEFAULT_SLIPPAGE,
    ) -> OrderResult:
        """
        Place a market-like FOK order (same behavior as SDK's place_market_order).

        Args:
            product_id:       Nado product ID.
            amount:           Signed amount in x18 (positive = buy, negative = sell).
            sender_address:   linked_signer_address (wallet that signs).
            subaccount_name:  Usually "default".
            slippage:         Slippage fraction, default 0.5%.
        """
        # 1. Get top-of-book price
        is_buy = amount > 0
        orderbook = self._get_market_liquidity(product_id, depth=1)
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])

        if is_buy and not asks:
            return OrderResult(status="failure", error="No asks in orderbook")
        if not is_buy and not bids:
            return OrderResult(status="failure", error="No bids in orderbook")

        raw_price = int(asks[0][0]) if is_buy else int(bids[0][0])
        slippage_x18 = to_x18(slippage)

        # Apply slippage: buy → price * (1 + slippage), sell → price * (1 - slippage)
        if is_buy:
            market_price = mul_x18(raw_price, to_x18(1) + slippage_x18)
        else:
            market_price = mul_x18(raw_price, to_x18(1) - slippage_x18)

        # Round to price increment
        price_increment = self._get_price_increment(
            product_id, sender_address, subaccount_name
        )
        final_price = round_x18(market_price, price_increment)

        # 2. Build order fields
        sender_bytes32 = subaccount_to_bytes32(sender_address, subaccount_name)
        nonce = gen_order_nonce()
        expiration = get_expiration_timestamp(1000)
        appendix = build_appendix(OrderType.FOK)

        # 3. Sign
        signature, sender_hex = sign_order(
            sender_bytes32=sender_bytes32,
            price_x18=final_price,
            amount=amount,
            expiration=expiration,
            nonce=nonce,
            appendix=appendix,
            product_id=product_id,
            chain_id=self.chain_id,
            private_key=self.private_key,
        )

        # 4. Send to engine
        payload = {
            "place_order": {
                "product_id": product_id,
                "order": {
                    "sender": sender_hex,
                    "priceX18": str(final_price),
                    "amount": str(amount),
                    "expiration": str(expiration),
                    "nonce": str(nonce),
                    "appendix": str(appendix),
                },
                "signature": signature,
            }
        }

        logger.info(
            "Placing market order | product=%s | amount=%s | price=%s | sender=%s",
            product_id,
            amount,
            final_price,
            sender_hex,
        )

        return self._execute(payload)

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    def _query(self, query_type: str, params: dict) -> dict:
        payload = {"type": query_type}
        payload.update(params)

        resp = self.session.post(f"{self.gateway_url}/query", json=payload)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "success":
            raise RuntimeError(f"Query failed: {data.get('error')}")
        return data["data"]

    def _execute(self, payload: dict) -> OrderResult:
        resp = self.session.post(f"{self.gateway_url}/execute", json=payload)
        if resp.status_code != 200:
            return OrderResult(status="failure", error=resp.text)
        data = resp.json()
        return OrderResult(
            status=data.get("status", "failure"),
            data=data.get("data"),
            error=data.get("error"),
            error_code=data.get("error_code"),
        )

    def _get_market_liquidity(self, product_id: int, depth: int = 1) -> dict:
        return self._query(
            "market_liquidity", {"product_id": product_id, "depth": depth}
        )

    def _get_price_increment(
        self, product_id: int, sender_address: str, subaccount_name: str
    ) -> int:
        from app.nado_client.utils import subaccount_to_hex

        sender_hex = subaccount_to_hex(sender_address, subaccount_name)
        try:
            data = self._query(
                "subaccount_info",
                {
                    "subaccount": sender_hex,
                    "txns": [{"type": "order", "product_id": product_id}],
                },
            )
            # Try to get price_increment from perp products
            for p in data.get("perp_products", []):
                if p.get("product_id") == product_id:
                    return int(p["book_info"]["price_increment_x18"])
            for p in data.get("spot_products", []):
                if p.get("product_id") == product_id:
                    return int(p["book_info"]["price_increment_x18"])
        except Exception as e:
            logger.warning("Could not fetch price increment: %s, using default", e)
        return to_x18(0.01)  # fallback: 1 cent increment
