"""
Ties an OAuth `state` value back to the user_id that started the flow, so the
callback (a plain browser redirect from GitHub/a connector, with no Authorization
header) knows whose account to attach the resulting credential to, and rejects a
forged or replayed state.

In-process and single-instance for Phase 1 — fine for one backend process, but
won't work if you run more than one backend instance behind a load balancer
without sticky sessions. See /docs/PHASE1_NOTES.md if you need to scale the
backend horizontally: swap this for a Postgres table or Redis with the same
create/pop/expire shape.
"""
import time

_STORE: dict[str, tuple[str, float]] = {}
_TTL_SECONDS = 600  # 10 minutes — plenty for an OAuth redirect round-trip


def put(state: str, user_id: str) -> None:
    _STORE[state] = (user_id, time.monotonic() + _TTL_SECONDS)


def pop(state: str) -> str | None:
    entry = _STORE.pop(state, None)
    if entry is None:
        return None
    user_id, expires_at = entry
    if time.monotonic() > expires_at:
        return None
    return user_id
