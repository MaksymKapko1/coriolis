"""
EIP-712 signing for Nado orders.
Uses eth_account directly, no pydantic dependency.
"""

from eth_account import Account
from eth_account.messages import encode_structured_data

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
) -> tuple[str, str]:
    """
    Sign an order with EIP-712 and return (signature, sender_hex).
    """
    from .utils import gen_order_verifying_contract, bytes32_to_hex

    verifying_contract = gen_order_verifying_contract(product_id)
    sender_hex = bytes32_to_hex(sender_bytes32)

    typed_data = {
        "types": ORDER_EIP712_TYPES,
        "primaryType": "Order",
        "domain": {
            "name": "Nado",
            "version": "0.0.1",
            "chainId": chain_id,
            "verifyingContract": verifying_contract,
        },
        "message": {
            "sender": sender_bytes32,
            "priceX18": price_x18,
            "amount": amount,
            "expiration": expiration,
            "nonce": nonce,
            "appendix": appendix,
        },
    }

    encoded = encode_structured_data(typed_data)
    account = Account.from_key(private_key)
    signed = account.sign_message(encoded)
    return signed.signature.hex(), sender_hex
