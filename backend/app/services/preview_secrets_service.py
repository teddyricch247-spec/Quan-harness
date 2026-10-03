"""
I/O shell around secret_redaction.py and repositories/preview_secrets.py — the
two things the rest of the backend needs from preview secrets, both of which are
about *keeping them out of places*, not putting them anywhere:

  - get_redaction_values / redact_text: what agent_loop._execute_call and
    deploy_pipeline use to scrub a preview secret's value out of any text on its
    way to the transcript / the model / the database.
  - get_runtime_env: what preview_runtime injects into the Sprite service's
    environment. The one and only place a value leaves this module toward the
    running app.

A short TTL cache fronts the Vault reads: _execute_call runs for *every* tool call
and must not cost a Vault round trip each time. Staleness is bounded two ways —
the TTL, and an explicit invalidate() from the router on every upsert/delete, so
within this single backend process a secret is protected from the instant it's
saved. (Same single-process assumption as agent_loop.py's in-memory state.)
"""
import time

from app.repositories import preview_secrets as preview_secrets_repo
from app.services.secret_redaction import redact

_CACHE_TTL_SECONDS = 30.0
_cache: dict[str, tuple[float, dict[str, str]]] = {}


def invalidate(project_id: str) -> None:
    _cache.pop(project_id, None)


async def get_redaction_values(project_id: str) -> dict[str, str]:
    now = time.monotonic()
    hit = _cache.get(project_id)
    if hit is not None and hit[0] > now:
        return hit[1]
    names = await preview_secrets_repo.list_names(project_id)  # cheap: no Vault read when there are none
    values = await preview_secrets_repo.resolve_all_for_project(project_id) if names else {}
    _cache[project_id] = (now + _CACHE_TTL_SECONDS, values)
    return values


async def redact_text(project_id: str, text: str | None) -> str | None:
    if not text:
        return text
    values = await get_redaction_values(project_id)
    return redact(text, values) if values else text


async def get_runtime_env(project_id: str) -> dict[str, str]:
    """Fresh from Vault, deliberately NOT the cache: this is what the app will
    actually run with, and a stale value here would be a real bug."""
    return await preview_secrets_repo.resolve_all_for_project(project_id)
