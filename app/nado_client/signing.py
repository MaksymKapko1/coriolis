"""
EIP-712 signing for Nado orders.
Uses eth_account directly, no pydantic dependency.
"""

from eth_account import Account
from eth_account.messages import encode_typed_data

# EIP-712 type definitions for Order
ORDER_EIP712_TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ],
    "Order": [
        {"name": "sender", "type": "bytes32"},
        {"name": "priceX18", "type": "int128"},
        {"name": "amount", "type": "int128"},
        {"name": "expiration", "type": "uint64"},
        {"name": "nonce", "type": "uint64"},
        {"name": "appendix", "type": "uint128"},
    ],
}

CANCEL_ORDERS_EIP712_TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ],
    "Cancellation": [
        {"name": "sender", "type": "bytes32"},
        {"name": "productIds", "type": "uint32[]"},
        {"name": "digests", "type": "bytes32[]"},
        {"name": "nonce", "type": "uint64"},
    ],
}


def sign_order(
    sender_bytes32: bytes,
    price_x18: int,
    amount: int,
    expiration: int,
    nonce: int,
    appendix: int,
    product_id: int,
    chain_id: int,
    private_key: str,
    verifying_contract: str | None = None,
) -> tuple[str, str]:
    """
    Sign an order with EIP-712 and return (signature, sender_hex).
    """
    from .utils import bytes32_to_hex, gen_order_verifying_contract

    if verifying_contract is None:
        verifying_contract = gen_order_verifying_contract(product_id)

    # verifying_contract = gen_order_verifying_contract(product_id)
    sender_hex = bytes32_to_hex(sender_bytes32)

    domain_data = {
        "name": "Nado",
        "version": "0.0.1",
        "chainId": chain_id,
        "verifyingContract": verifying_contract,
    }

    message_types = {
        "Order": [
            {"name": "sender", "type": "bytes32"},
            {"name": "priceX18", "type": "int128"},
            {"name": "amount", "type": "int128"},
            {"name": "expiration", "type": "uint64"},
            {"name": "nonce", "type": "uint64"},
            {"name": "appendix", "type": "uint128"},
        ]
    }

    message_data = {
        "sender": sender_bytes32,
        "priceX18": price_x18,
        "amount": amount,
        "expiration": expiration,
        "nonce": nonce,
        "appendix": appendix,
    }

    encoded = encode_typed_data(
        domain_data=domain_data, message_types=message_types, message_data=message_data
    )

    account = Account.from_key(private_key)
    signed = account.sign_message(encoded)

    return signed.signature.hex(), sender_hex


def sign_cancel_orders(
    sender_bytes32: bytes,
    product_ids: list[int],
    digests: list[str],
    nonce: int,
    chain_id: int,
    endpoint_addr: str,
    private_key: str,
) -> tuple[str, str]:
    """Sign a cancel orders request using endpoint_addr as verifying contract."""
    from app.nado_client.utils import bytes32_to_hex, hex_to_bytes32

    sender_hex = bytes32_to_hex(sender_bytes32)
    digests_bytes = [hex_to_bytes32(d) for d in digests]

    typed_data = {
        "types": CANCEL_ORDERS_EIP712_TYPES,
        "primaryType": "Cancellation",
        "domain": {
            "name": "Nado",
            "version": "0.0.1",
            "chainId": chain_id,
            "verifyingContract": endpoint_addr,
        },
        "message": {
            "sender": sender_bytes32,
            "productIds": product_ids,
            "digests": digests_bytes,
            "nonce": nonce,
        },
    }

    encoded = encode_typed_data(full_message=typed_data)
    account = Account.from_key(private_key)
    signed = account.sign_message(encoded)
    return signed.signature.hex(), sender_hex
