"""
Minimal Nado HTTP client.
Handles market order placement without nado-protocol SDK dependency.
"""

import logging
from dataclasses import dataclass

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
    subaccount_to_hex,
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
    data: dict | None = None
    error: str | None = None
    error_code: int | None = None


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
    def close_position(
        self,
        product_id: int,
        sender_address: str,
        subaccount_name: str = "default",
    ) -> OrderResult:
        """
        Closes an open position for given product_id.
        Mirrors SDK's close_position: queries current balance,
        inverts it with FOK + reduce_only.
        """
        sender_hex = subaccount_to_hex(sender_address, subaccount_name)

        # 1. Получаем текущую позицию
        subaccount_info = self._query("subaccount_info", {"subaccount": sender_hex})

        # Ищем баланс и продукт по product_id
        all_balances = subaccount_info.get("spot_balances", []) + subaccount_info.get(
            "perp_balances", []
        )
        all_products = subaccount_info.get("spot_products", []) + subaccount_info.get(
            "perp_products", []
        )

        balance = next((b for b in all_balances if b["product_id"] == product_id), None)
        product = next((p for p in all_products if p["product_id"] == product_id), None)

        if not balance or not product:
            return OrderResult(
                status="failure", error=f"No position found for product_id={product_id}"
            )

        current_amount = int(balance["balance"]["amount"])
        if current_amount == 0:
            return OrderResult(status="failure", error="Position is already closed")

        oracle_price = int(product["oracle_price_x18"])
        size_increment = int(product["book_info"]["size_increment"])
        price_increment = int(product["book_info"]["price_increment_x18"])

        # 2. Closing price с 0.5% spread (как в SDK)
        spread = to_x18(0.005)
        if current_amount > 0:  # long → закрываем sell по цене чуть ниже
            closing_price = mul_x18(oracle_price, to_x18(1) - spread)
        else:  # short → закрываем buy по цене чуть выше
            closing_price = mul_x18(oracle_price, to_x18(1) + spread)

        final_price = round_x18(closing_price, price_increment)
        closing_amount = -round_x18(current_amount, size_increment)  # инвертируем

        # 3. Подписываем и отправляем
        sender_bytes32 = subaccount_to_bytes32(sender_address, subaccount_name)
        nonce = gen_order_nonce()
        expiration = get_expiration_timestamp(1000)
        appendix = build_appendix(OrderType.FOK, reduce_only=True)  # ← reduce_only!

        signature, sender_hex_signed = sign_order(
            sender_bytes32=sender_bytes32,
            price_x18=final_price,
            amount=closing_amount,
            expiration=expiration,
            nonce=nonce,
            appendix=appendix,
            product_id=product_id,
            chain_id=self.chain_id,
            private_key=self.private_key,
        )

        payload = {
            "place_order": {
                "product_id": product_id,
                "order": {
                    "sender": sender_hex_signed,
                    "priceX18": str(final_price),
                    "amount": str(closing_amount),
                    "expiration": str(expiration),
                    "nonce": str(nonce),
                    "appendix": str(appendix),
                },
                "signature": signature,
            }
        }

        logger.info(
            "Closing position | product=%s | current_amount=%s | "
            "closing_amount=%s | sender=%s",
            product_id,
            current_amount,
            closing_amount,
            sender_hex,
        )

        return self._execute(payload)

    def place_market_order(
        self,
        product_id: int,
        notional_usd: float,
        is_buy: bool,
        sender_address: str,
        subaccount_name: str = "default",
        slippage: float = DEFAULT_SLIPPAGE,
    ) -> OrderResult:
        """
        Place a market-like FOK order (same behavior as SDK's place_market_order).

        Args:
            product_id:       Nado product ID.
            notional_usd:     Quote notional amount in USD.
            is_buy:           True = buy/long, False = sell/short.
            sender_address:   linked_signer_address (wallet that signs).
            subaccount_name:  Usually "default".
            slippage:         Slippage fraction, default 0.5%.
        """
        if notional_usd <= 0:
            return OrderResult(
                status="failure", error="Order notional must be positive"
            )

        # 1. Get top-of-book price
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

        try:
            book_info = self._get_product_book_info(
                product_id, sender_address, subaccount_name
            )
        except Exception as e:
            logger.warning("Could not fetch product book info: %s", e)
            return OrderResult(
                status="failure",
                error=f"Could not fetch product metadata for product {product_id}",
            )

        price_increment = book_info["price_increment_x18"]
        size_increment = book_info["size_increment"]
        min_size = book_info["min_size"]

        if price_increment <= 0:
            return OrderResult(
                status="failure",
                error=f"Invalid price increment for product {product_id}",
            )
        if size_increment <= 0:
            return OrderResult(
                status="failure",
                error=f"Invalid size increment for product {product_id}",
            )

        final_price = round_x18(market_price, price_increment)
        amount = self._notional_to_base_amount(
            notional_usd=notional_usd,
            price_x18=final_price,
            size_increment=size_increment,
        )

        if amount <= 0:
            return OrderResult(
                status="failure",
                error=f"Order notional is too small for product {product_id}",
            )
        # if min_size > 0 and amount < min_size:
        #     return OrderResult(
        #         status="failure",
        #         error=f"Order notional is below min size for product {product_id}",
        #     )

        signed_amount = amount if is_buy else -amount

        # 2. Build order fields
        sender_bytes32 = subaccount_to_bytes32(sender_address, subaccount_name)
        nonce = gen_order_nonce()
        expiration = get_expiration_timestamp(1000)
        appendix = build_appendix(OrderType.FOK)

        # 3. Sign
        signature, sender_hex = sign_order(
            sender_bytes32=sender_bytes32,
            price_x18=final_price,
            amount=signed_amount,
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
                    "amount": str(signed_amount),
                    "expiration": str(expiration),
                    "nonce": str(nonce),
                    "appendix": str(appendix),
                },
                "signature": signature,
            }
        }

        logger.info(
            "Placing market order | product=%s | notional_usd=%s | "
            "amount=%s | price=%s | sender=%s",
            product_id,
            notional_usd,
            signed_amount,
            final_price,
            sender_hex,
        )

        return self._execute(payload)

    def place_batch_orders(
        self,
        orders: list[dict],  # [{"product_id": 1, "amount": 1000, "is_buy": True}, ...]
        sender_address: str,
        subaccount_name: str = "default",
        stop_on_failure: bool = False,
    ) -> OrderResult:
        """
        Place multiple orders in a single request.
        Each order is signed individually, then sent as one batch.
        """
        signed_orders = []

        for order in orders:
            product_id = order["product_id"]
            amount = order["amount"]  # уже в x18

            # Берём top-of-book для каждого продукта
            is_buy = amount > 0
            orderbook = self._get_market_liquidity(product_id, depth=1)
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])

            if is_buy and not asks:
                return OrderResult(
                    status="failure", error=f"No asks for product {product_id}"
                )
            if not is_buy and not bids:
                return OrderResult(
                    status="failure", error=f"No bids for product {product_id}"
                )

            raw_price = int(asks[0][0]) if is_buy else int(bids[0][0])
            slippage_x18 = to_x18(DEFAULT_SLIPPAGE)
            market_price = (
                mul_x18(raw_price, to_x18(1) + slippage_x18)
                if is_buy
                else mul_x18(raw_price, to_x18(1) - slippage_x18)
            )

            price_increment = self._get_price_increment(
                product_id, sender_address, subaccount_name
            )
            final_price = round_x18(market_price, price_increment)

            sender_bytes32 = subaccount_to_bytes32(sender_address, subaccount_name)
            nonce = gen_order_nonce()
            expiration = get_expiration_timestamp(1000)
            appendix = build_appendix(OrderType.FOK)

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

            signed_orders.append(
                {
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
            )

        payload = {
            "place_orders": {
                "orders": signed_orders,
                "stop_on_failure": stop_on_failure,
            }
        }

        logger.info(
            "Placing batch of %s orders | sender=%s", len(signed_orders), sender_address
        )
        return self._execute(payload)

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    def _query(self, query_type: str, params: dict) -> dict:
        payload = {"type": query_type}
        payload.update(params)

        resp = self.session.post(f"{self.gateway_url}/query", json=payload)
        if resp.status_code != 200:
            logger.warning(
                "Nado query failed | type=%s | status=%s | response=%s | payload=%s",
                query_type,
                resp.status_code,
                resp.text[:2000],
                payload,
            )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "success":
            logger.warning(
                "Nado query returned failure | type=%s | response=%s | payload=%s",
                query_type,
                data,
                payload,
            )
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

    @staticmethod
    def _notional_to_base_amount(
        notional_usd: float,
        price_x18: int,
        size_increment: int,
    ) -> int:
        quote_amount_x18 = to_x18(notional_usd)
        base_amount = quote_amount_x18 * 10**18 // price_x18
        return round_x18(base_amount, size_increment)

    def _get_product_book_info(
        self, product_id: int, sender_address: str, subaccount_name: str
    ) -> dict[str, int]:
        sender_hex = subaccount_to_hex(sender_address, subaccount_name)
        data = self._query(
            "subaccount_info",
            {"subaccount": sender_hex},
        )
        for product in data.get("perp_products", []) + data.get("spot_products", []):
            if product.get("product_id") != product_id:
                continue
            book_info = product.get("book_info") or {}
            return {
                "oracle_price_x18": int(product.get("oracle_price_x18", 0)),
                "price_increment_x18": int(book_info.get("price_increment_x18", 0)),
                "size_increment": int(book_info.get("size_increment", 0)),
                "min_size": int(book_info.get("min_size", 0)),
            }
        raise RuntimeError(f"Product {product_id} not found in subaccount info")

    def _get_price_increment(
        self, product_id: int, sender_address: str, subaccount_name: str
    ) -> int:
        try:
            return self._get_product_book_info(
                product_id, sender_address, subaccount_name
            )["price_increment_x18"]
        except Exception as e:
            logger.warning("Could not fetch price increment: %s, using default", e)
        return to_x18(0.01)  # fallback: 1 cent increment
