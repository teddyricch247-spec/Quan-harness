"""
The orchestration backend is the only thing that touches the database with
application privileges (§5). It connects using the Supabase service_role key,
which bypasses RLS entirely by design — the real security boundary is the
disciplined, structural user_id scoping in app/repositories/, not RLS. RLS is
still enabled on every table (0002/0004/0005 migrations) as defense in depth
against some future code path querying Postgres through a different credential.

supabase-py's client is synchronous under the hood; every repository call runs it
inside a threadpool so it doesn't block the event loop.
"""
import logging
from functools import lru_cache

import httpx
from supabase import Client, create_client

from app.config import get_settings

logger = logging.getLogger(__name__)


def _harden_postgrest_session(client: Client) -> Client:
    """postgrest-py hard-codes http2=True and this process shares ONE client across
    every threadpool worker. After any idle gap Supabase closes the multiplexed HTTP/2
    connection, and the next burst of concurrent requests dies with
    `httpx.RemoteProtocolError: Server disconnected` (seen in the live Render logs: the
    agent's very first turn failed with exactly that, before it ever called the model).
    Swap the session for plain HTTP/1.1 with a short keep-alive so a dead connection is
    never reused. Best-effort: if the library's internals ever change, leave it alone."""
    try:
        old = client.postgrest.session
        # `limits` must go on the transport: httpx ignores Client(limits=...) once a custom
        # transport is supplied, which would silently drop the short keep-alive.
        transport = httpx.HTTPTransport(
            http2=False,
            retries=2,  # connect-time retries only
            limits=httpx.Limits(max_connections=40, max_keepalive_connections=10, keepalive_expiry=5.0),
        )
        client.postgrest.session = httpx.Client(
            base_url=old.base_url,
            headers=old.headers,
            timeout=old.timeout,
            follow_redirects=True,
            transport=transport,
        )
    except Exception:  # noqa: BLE001
        logger.warning("could not harden the Supabase PostgREST session; using library defaults", exc_info=True)
    return client


@lru_cache
def get_service_client() -> Client:
    settings = get_settings()
    return _harden_postgrest_session(create_client(settings.supabase_url, settings.supabase_service_role_key))


@lru_cache
def get_anon_client() -> Client:
    """Used only for the /auth/* proxy routes (signup/login/reset), which should run
    with the same privileges an end user's own browser would have — never service_role."""
    settings = get_settings()
    return _harden_postgrest_session(create_client(settings.supabase_url, settings.supabase_anon_key))
