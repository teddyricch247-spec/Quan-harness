import time

_STORE: dict[str, dict] = {}
_TTL_SECONDS = 600


def put(state: str, payload: dict) -> None:
    _STORE[state] = {**payload, "_expires_at": time.monotonic() + _TTL_SECONDS}


def pop(state: str) -> dict | None:
    entry = _STORE.pop(state, None)
    if entry is None:
        return None
    if time.monotonic() > entry["_expires_at"]:
        return None
    return entry
