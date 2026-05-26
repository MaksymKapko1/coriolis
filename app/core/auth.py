import json
import time

import httpx
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt

from app.core.config import settings

security = HTTPBearer()

JWKS_URL = f"https://auth.privy.io/api/v1/apps/{settings.privy_app_id}/jwks.json"
JWKS_TTL = 86400

_privy_jwks = None
_jwks_last_fetch = 0

async def get_jwks(force_refresh: bool = False) -> dict:
    global _privy_jwks, _jwks_last_fetch

    now = time.time()
    if _privy_jwks is None or (now - _jwks_last_fetch) > JWKS_TTL or force_refresh:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(JWKS_URL, timeout=10)
                response.raise_for_status()
                _privy_jwks = response.json()
                _jwks_last_fetch = now
        except Exception:
            if _privy_jwks is None:
                raise HTTPException(status_code=500, detail="Auth keys unavailable")

    return _privy_jwks

async def verify_privy_token(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> dict:
    token = credentials.credentials
    try:
        return jwt.decode(
            token, await get_jwks(),
            algorithms=["ES256"],
            issuer="privy.io",
            audience=settings.privy_app_id,
        )
    except jwt.JWTError:
        try:
            return jwt.decode(
                token, await get_jwks(force_refresh=True),
                algorithms=["ES256"],
                issuer="privy.io",
                audience=settings.privy_app_id,
            )
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid token")

async def get_current_wallet(
    token_data: dict = Depends(verify_privy_token),
) -> str:
    accounts_raw = token_data.get("linked_accounts", "[]")
    linked_accounts = json.loads(accounts_raw)

    evm_wallet = next(
        (
            acc.get("address") for acc in linked_accounts
            if acc.get("type") == "wallet"
            and acc.get("chain_type") == "ethereum"
        ),
        None,
    )

    if not evm_wallet:
        raise HTTPException(status_code=401, detail="No EVM wallet linked")

    return evm_wallet