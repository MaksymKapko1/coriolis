import logging
import time

import httpx
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt

from app.core.config import settings

logger = logging.getLogger(__name__)

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
            token,
            await get_jwks(),
            algorithms=["ES256"],
            issuer="privy.io",
            audience=settings.privy_app_id,
        )
    except jwt.JWTError:
        try:
            return jwt.decode(
                token,
                await get_jwks(force_refresh=True),
                algorithms=["ES256"],
                issuer="privy.io",
                audience=settings.privy_app_id,
            )
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_wallet(
    token_data: dict = Depends(verify_privy_token),
) -> str:
    privy_did = token_data.get("sub")
    if not privy_did:
        raise HTTPException(status_code=401, detail="Invalid token claims")

    url = f"https://auth.privy.io/api/v1/users/{privy_did}"

    auth = (settings.privy_app_id, settings.privy_app_secret)

    headers = {"privy-app-id": settings.privy_app_id}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, auth=auth, headers=headers, timeout=10)
            response.raise_for_status()
            user_profile = response.json()
    except Exception as e:
        logger.error("Failed to fetch user profile from Privy API: %s", e)
        raise HTTPException(
            status_code=500, detail="Authentication provider unavailable"
        )
    linked_accounts = user_profile.get("linked_accounts", [])
    evm_wallet = None

    for acc in linked_accounts:
        if acc.get("type") == "wallet" and acc.get("chain_type") == "ethereum":
            evm_wallet = acc.get("address")
            break
    if not evm_wallet:
        logger.warning("No EVM wallet found for Privy user %s", privy_did)
        raise HTTPException(
            status_code=401, detail="No EVM wallet linked to this account"
        )
    return evm_wallet
