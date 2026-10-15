"""
§23.7 / §23.1: the preview is only ever reachable *through* the harness and is
never a shareable link, so every request to a preview subdomain has to be
authenticated — and an iframe navigation can't carry the harness's normal
`Authorization: Bearer` header. The standard answer is a two-step exchange:

  1. The signed-in person calls POST /projects/{id}/preview/session (normal
     Bearer auth, ownership checked). The backend mints a short-lived, SINGLE-USE
     "enter" token and returns an iframe URL carrying it:
         https://<sub>.<preview-domain>/__qh/enter?t=<token>
  2. The proxy verifies the token, burns it, sets a host-only HttpOnly session
     cookie on the preview origin, and redirects to `/`. Every later request
     (documents, scripts, XHR, websocket upgrades) is authenticated by that
     cookie — the URL token never needs to appear again.

Why single-use and 60 seconds: the enter token travels in a URL, so it can end up
in browser history, proxy logs, or a Referer header. A token that's dead after one
use (or a minute) turns any of those leaks into a non-event. The session cookie is
HttpOnly (the previewed app's own JavaScript can't read it) and is stripped from
every request forwarded to the app, so the app can't see it either.

Tokens are bound to BOTH the project and the subdomain, so a token minted for one
project's preview can't be replayed against another's.

HS256 with a dedicated PREVIEW_SIGNING_SECRET — deliberately not the Supabase JWT
secret, which may be blank on asymmetric-key projects and which should never sign
anything a user-controlled app origin might see.
"""
import threading
import time
import uuid

import jwt

AUDIENCE = "qh-preview"
ALGORITHM = "HS256"

USE_ENTER = "enter"
USE_SESSION = "session"


class PreviewTokenError(Exception):
    """Invalid, expired, wrong-scope or already-used token. The message is for
    logs; the proxy never shows it to the caller."""


# jti -> expiry (epoch seconds) of enter tokens that have been redeemed. In-process
# is correct here: the backend is a single process (same assumption as agent_loop's
# in-memory session claims), a token lives 60s, and the set is pruned on every use.
_used_enter_jtis: dict[str, float] = {}
_used_lock = threading.Lock()


def _now() -> float:
    return time.time()


def _mint(secret: str, use: str, project_id: str, subdomain: str, ttl_seconds: int, user_id: str | None) -> str:
    if not secret:
        raise PreviewTokenError("PREVIEW_SIGNING_SECRET is not configured.")
    now = int(_now())
    claims = {
        "aud": AUDIENCE,
        "use": use,
        "pid": project_id,
        "sd": subdomain,
        "iat": now,
        "exp": now + int(ttl_seconds),
        "jti": uuid.uuid4().hex,
    }
    if user_id:
        claims["uid"] = user_id
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def mint_enter_token(secret: str, project_id: str, subdomain: str, ttl_seconds: int = 60, user_id: str | None = None) -> str:
    return _mint(secret, USE_ENTER, project_id, subdomain, ttl_seconds, user_id)


def mint_session_token(secret: str, project_id: str, subdomain: str, ttl_seconds: int, user_id: str | None = None) -> str:
    return _mint(secret, USE_SESSION, project_id, subdomain, ttl_seconds, user_id)


def _decode(secret: str, token: str, use: str, subdomain: str) -> dict:
    if not secret:
        raise PreviewTokenError("PREVIEW_SIGNING_SECRET is not configured.")
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],  # pinned: never accept the token's own `alg` header
            audience=AUDIENCE,
            options={"require": ["exp", "aud", "jti", "pid", "sd", "use"]},
        )
    except jwt.PyJWTError as exc:
        raise PreviewTokenError(f"Token rejected: {exc}") from exc
    if claims.get("use") != use:
        raise PreviewTokenError("Token was minted for a different purpose.")
    if claims.get("sd") != subdomain:
        raise PreviewTokenError("Token was minted for a different preview.")
    return claims


def verify_session_token(secret: str, token: str, subdomain: str) -> dict:
    return _decode(secret, token, USE_SESSION, subdomain)


def redeem_enter_token(secret: str, token: str, subdomain: str) -> dict:
    """Verifies AND burns. A second redemption of the same token raises."""
    claims = _decode(secret, token, USE_ENTER, subdomain)
    jti, exp = claims["jti"], float(claims["exp"])
    now = _now()
    with _used_lock:
        for key in [k for k, v in _used_enter_jtis.items() if v < now]:
            del _used_enter_jtis[key]
        if jti in _used_enter_jtis:
            raise PreviewTokenError("Enter token was already used.")
        _used_enter_jtis[jti] = exp
    return claims


def _reset_for_tests() -> None:
    with _used_lock:
        _used_enter_jtis.clear()
