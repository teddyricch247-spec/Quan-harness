"""
Verifies the Supabase-issued JWT the frontend attaches as a Bearer token on every
request (§4 of the spec: "the frontend receives a JWT and attaches it as a Bearer
token to every backend request"). Supports both of Supabase's signing setups:

- Legacy projects: a single HS256 secret (Settings -> API -> JWT Secret).
- Newer projects: asymmetric keys, verified against the project's JWKS endpoint.

Either way, the only claim this system trusts is `sub` (the user_id every table is
scoped by, per §5) and `email_confirmed_at` / a `user_metadata`/top-level
verification flag used to gate actions per §4's email verification requirement.
"""
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import HTTPException, status

from app.config import get_settings


@dataclass
class AuthedUser:
    user_id: str
    email: str | None
    email_confirmed: bool


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    settings = get_settings()
    return jwt.PyJWKClient(settings.supabase_jwks_url)


def _decode(token: str) -> dict:
    settings = get_settings()
    if settings.supabase_jwt_secret:
        try:
            return jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
        except jwt.InvalidTokenError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}")
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience="authenticated",
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}")


def verify_supabase_jwt(token: str) -> AuthedUser:
    claims = _decode(token)
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing sub claim")
    # Supabase includes email_confirmed_at (or is_email_verified in some configs) either
    # at the top level or under user_metadata depending on project settings — check both.
    email_confirmed = bool(
        claims.get("email_confirmed_at")
        or claims.get("is_email_verified")
        or claims.get("user_metadata", {}).get("email_verified")
    )
    return AuthedUser(user_id=user_id, email=claims.get("email"), email_confirmed=email_confirmed)
