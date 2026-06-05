"""
Minimal Nado HTTP client.
Handles market order placement without nado-protocol SDK dependency.
"""

import logging
from dataclasses import dataclass
from http import client as http_client

import requests

from app.nado_client.signing import sign_order
from app.nado_client.utils import (
    OrderType,
    TriggerType,
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
        "trigger_url": "https://trigger.test.nado.xyz/v1",
        "chain_id": 763373,
        "endpoint_addr": "0x698D87105274292B5673367DEC81874Ce3633Ac2",
    },
    "mainnet": {
        "gateway_url": "https://gateway.prod.nado.xyz/v1",
        "trigger_url": "https://trigger.prod.nado.xyz/v1",
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
        self.trigger_url = config["trigger_url"]
        self.chain_id = config["chain_id"]
        self.endpoint_addr = config["endpoint_addr"]
        self.private_key = private_key
        self.session = requests.Session()
        self.session.headers.update({"Accept-Encoding": "gzip"})
        http_client.HTTPConnection.debuglevel = 1

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

        subaccount_info = self._query("subaccount_info", {"subaccount": sender_hex})

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

        spread = to_x18(0.005)
        if current_amount > 0:
            closing_price = mul_x18(oracle_price, to_x18(1) - spread)
        else:
            closing_price = mul_x18(oracle_price, to_x18(1) + spread)

        final_price = round_x18(closing_price, price_increment)
        closing_amount = -round_x18(current_amount, size_increment)

        sender_bytes32 = subaccount_to_bytes32(sender_address, subaccount_name)
        nonce = gen_order_nonce()
        expiration = get_expiration_timestamp(1000)
        appendix = build_appendix(OrderType.FOK, reduce_only=True)

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

    def place_limit_order(
        self,
        product_id: int,
        price_usd: float,
        notional_usd: float,
        is_buy: bool,
        sender_address: str,
        subaccount_name: str = "default",
        order_type: OrderType = OrderType.DEFAULT,
    ) -> OrderResult:
        if notional_usd <= 0 or price_usd <= 0:
            return OrderResult(
                status="failure", error="Price and notional must be positive"
            )

        try:
            book_info = self._get_product_book_info(
                product_id, sender_address, subaccount_name
            )
        except Exception as e:
            return OrderResult(
                status="failure", error=f"Could not fetch product metadata: {e}"
            )

        price_increment = book_info["price_increment_x18"]
        size_increment = book_info["size_increment"]
        min_size = book_info.get("min_size", 0)  # Достаем min_size

        raw_price_x18 = to_x18(price_usd)
        final_price = round_x18(raw_price_x18, price_increment)

        amount = self._notional_to_base_amount(
            notional_usd=notional_usd,
            price_x18=final_price,
            size_increment=size_increment,
            min_size=min_size,
        )

        if amount <= 0:
            return OrderResult(
                status="failure",
                error=f"Calculated amount is 0. Notional too small or rounded to zero by size_increment ({size_increment})",
            )

        min_notional_usd = min_size / 1e18 if min_size > 0 else 0
        if min_notional_usd > 0 and notional_usd + 1e-6 < min_notional_usd:
            return OrderResult(
                status="failure",
                error=f"Minimum order notional is ${min_notional_usd:.0f}",
            )

        signed_amount = amount if is_buy else -amount

        sender_bytes32 = subaccount_to_bytes32(sender_address, subaccount_name)
        nonce = gen_order_nonce()
        expiration = get_expiration_timestamp(
            604800 if order_type == OrderType.DEFAULT else 1000
        )
        appendix = build_appendix(order_type)

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

        return self._execute(payload)

    def cancel_orders(
        self,
        product_ids: list[int],
        digests: list[str],
        sender_address: str,
        subaccount_name: str = "default",
    ) -> OrderResult:
        """
        Cancel specific orders by their digests.

        Args:
            product_ids:  List of product IDs for orders to cancel.
            digests:      List of order digests (returned when order was placed).
        """
        from app.nado_client.signing import sign_cancel_orders

        sender_bytes32 = subaccount_to_bytes32(sender_address, subaccount_name)
        nonce = gen_order_nonce()

        signature, sender_hex = sign_cancel_orders(
            sender_bytes32=sender_bytes32,
            product_ids=product_ids,
            digests=digests,
            nonce=nonce,
            chain_id=self.chain_id,
            endpoint_addr=self.endpoint_addr,
            private_key=self.private_key,
        )

        payload = {
            "cancel_orders": {
                "tx": {
                    "sender": sender_hex.lower(),
                    "productIds": product_ids,
                    "digests": [d.lower() for d in digests],
                    "nonce": str(nonce),
                },
                "signature": signature,
            }
        }

        logger.info(
            "Cancelling orders | products=%s | digests=%s | sender=%s",
            product_ids,
            digests,
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
        min_size = book_info.get("min_size", 0)

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
            min_size=min_size,
        )

        if amount <= 0:
            return OrderResult(
                status="failure",
                error=f"Order notional is too small for product {product_id}",
            )

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
        orders: list[dict],
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
            notional_usd = order["notional_usd"]
            is_buy = order["is_buy"]

            if notional_usd <= 0:
                return OrderResult(
                    status="failure",
                    error=f"Order notional must be positive for product {product_id}",
                )

            # Берём top-of-book для каждого продукта
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
            min_size = book_info.get("min_size", 0)

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
                min_size=min_size,
            )

            if amount <= 0:
                return OrderResult(
                    status="failure",
                    error=f"Order notional is too small for product {product_id}",
                )

            signed_amount = amount if is_buy else -amount

            sender_bytes32 = subaccount_to_bytes32(sender_address, subaccount_name)
            nonce = gen_order_nonce()
            expiration = get_expiration_timestamp(1000)
            appendix = build_appendix(OrderType.FOK)

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

            signed_orders.append(
                {
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
            )
            logger.info(
                "Prepared batch order | product=%s | notional_usd=%s | "
                "amount=%s | price=%s | size_increment=%s",
                product_id,
                notional_usd,
                signed_amount,
                final_price,
                size_increment,
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

    def place_trigger_order(
        self,
        product_id: int,
        price_usd: float,
        notional_usd: float,
        is_buy: bool,
        trigger_price_usd: float,
        trigger_type: str,  # "last_price_above" | "last_price_below" | "oracle_price_above" | "oracle_price_below"
        sender_address: str,
        subaccount_name: str = "default",
        reduce_only: bool = True,
        dependency_digest: str | None = None,
    ) -> OrderResult:
        """
        Place a TP or SL trigger order.
        trigger_type examples:
            TP long  → "last_price_above"   (sell when price goes up)
            SL long  → "last_price_below"   (sell when price drops)
            TP short → "last_price_below"   (buy  when price drops)
            SL short → "last_price_above"   (buy  when price rises)
        """
        if notional_usd <= 0 or price_usd <= 0 or trigger_price_usd <= 0:
            return OrderResult(
                status="failure", error="All prices and notional must be positive"
            )

        try:
            book_info = self._get_product_book_info(
                product_id, sender_address, subaccount_name
            )
        except Exception as e:
            return OrderResult(
                status="failure", error=f"Could not fetch product metadata: {e}"
            )

        price_increment = book_info["price_increment_x18"]
        size_increment = book_info["size_increment"]
        min_size = book_info.get("min_size", 0)

        raw_price_x18 = to_x18(price_usd)
        final_price = round_x18(raw_price_x18, price_increment)

        amount = self._notional_to_base_amount(
            notional_usd=notional_usd,
            price_x18=final_price,
            size_increment=size_increment,
            min_size=min_size,
        )
        if amount <= 0:
            return OrderResult(status="failure", error="Notional too small")

        signed_amount = amount if is_buy else -amount

        sender_bytes32 = subaccount_to_bytes32(sender_address, subaccount_name)
        nonce = gen_order_nonce()
        expiration = get_expiration_timestamp(60 * 60 * 24 * 7)  # 7 дней
        appendix = build_appendix(
            OrderType.DEFAULT, reduce_only=reduce_only, trigger_type=TriggerType.PRICE
        )

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

        trigger_price_x18 = to_x18(trigger_price_usd)
        price_requirement = {trigger_type: str(trigger_price_x18)}

        price_trigger: dict = {"price_requirement": price_requirement}
        if dependency_digest:
            price_trigger["dependency"] = {
                "digest": dependency_digest,
                "on_partial_fill": False,
            }

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
                "trigger": {"price_trigger": price_trigger},
                "signature": signature,
            }
        }

        logger.info(
            "Placing trigger order | product=%s | trigger_type=%s | trigger_price=%s | sender=%s",
            product_id,
            trigger_type,
            trigger_price_usd,
            sender_hex,
        )

        # resp = self.session.post(f"{self.trigger_url}/execute", json=payload)
        # if resp.status_code != 200:
        #     return OrderResult(status="failure", error=resp.text)
        # data = resp.json()
        # return OrderResult(
        #     status=data.get("status", "failure"),
        #     data=data.get("data"),
        #     error=data.get("error"),
        #     error_code=data.get("error_code"),
        # )
        return self._execute_trigger(payload)

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

    def _execute_trigger(self, payload: dict) -> OrderResult:
        import time

        for attempt in range(3):
            try:
                resp = self.session.post(
                    f"{self.trigger_url}/execute",
                    json=payload,
                    timeout=10,
                )
                if resp.status_code != 200:
                    return OrderResult(status="failure", error=resp.text)
                data = resp.json()
                return OrderResult(
                    status=data.get("status", "failure"),
                    data=data.get("data"),
                    error=data.get("error"),
                    error_code=data.get("error_code"),
                )
            except Exception as e:
                logger.warning("Trigger attempt %s failed: %s", attempt + 1, e)
                if attempt < 2:
                    time.sleep(1)
        return OrderResult(
            status="failure", error="Trigger endpoint unreachable after 3 attempts"
        )

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
        min_size: int = 0,
    ) -> int:
        """
        Convert USD notional to base amount (x18), rounded to size_increment.
        If min_size is set (Nado: abs(amount)*price >= min_size), round up so the
        order meets the exchange minimum (~$100 notional on mainnet perps).
        """
        if price_x18 <= 0 or size_increment <= 0:
            return 0

        quote_amount_x18 = to_x18(notional_usd)
        base_amount = quote_amount_x18 * 10**18 // price_x18
        amount = round_x18(base_amount, size_increment)

        if min_size > 0:
            while amount > 0 and mul_x18(amount, price_x18) < min_size:
                amount += size_increment

        return amount

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
