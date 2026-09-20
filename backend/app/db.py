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
from functools import lru_cache

from supabase import Client, create_client

from app.config import get_settings


@lru_cache
def get_service_client() -> Client:
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


@lru_cache
def get_anon_client() -> Client:
    """Used only for the /auth/* proxy routes (signup/login/reset), which should run
    with the same privileges an end user's own browser would have — never service_role."""
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_anon_key)
