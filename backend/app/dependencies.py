"""
FastAPI dependencies for auth. Two levels, matching §4 of the spec:

- current_user: any signed-in account, verified or not. Enough to see your own
  (empty) dashboard. Only decodes the JWT — no network call, fast.
- verified_user: additionally blocks any action that "would touch real
  infrastructure" — creating a project, connecting a credential, connecting a
  connector, starting a session.

A bug fixed here: a Supabase-issued JWT does NOT reliably carry an
email-confirmed claim at the top level unless you've configured a custom Access
Token Hook in your Supabase project (nothing in this repo sets one up — see
docs/YOUR_SETUP_CHECKLIST.md if you want to add one later to skip the extra
round-trip below). Treating an absent claim as "not verified" would have meant
verified_user rejected every request forever, even from a genuinely verified
account. verified_user below only trusts the JWT claim as a fast-path skip when
it happens to be true; otherwise it asks Supabase's Admin Auth API directly,
which always knows the real answer regardless of how the JWT was built.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from app.core.security import AuthedUser, verify_supabase_jwt
from app.db import get_service_client

_bearer = HTTPBearer(auto_error=True)


def current_user(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> AuthedUser:
    return verify_supabase_jwt(creds.credentials)


async def verified_user(user: AuthedUser = Depends(current_user)) -> AuthedUser:
    if user.email_confirmed:
        return user  # fast path — true here is trustworthy even if false isn't

    client = get_service_client()

    def _fetch():
        return client.auth.admin.get_user_by_id(user.user_id)

    try:
        resp = await run_in_threadpool(_fetch)
        confirmed = bool(resp.user.email_confirmed_at)
    except Exception:  # noqa: BLE001 — treat any lookup failure as unverified, not as a 500
        confirmed = False

    if not confirmed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verify your email before doing this — check your inbox for the confirmation link.",
        )
    return user
