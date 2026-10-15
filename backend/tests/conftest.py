"""
§5: "RLS must be live-tested, not declared and forgotten. An automated suite
connects to Postgres as the authenticated role using two distinct real
test-account JWTs and asserts, for every user-owned and project-owned table,
that account A's queries against account B's rows return zero rows — run in CI
on every pull request touching a table's schema or policies."

These fixtures sign in as two real Supabase accounts using the anon key — the
same way a browser would — so every query in test_rls_isolation.py and
test_isolation_matrix.py runs through PostgREST as the `authenticated` role with
that account's own JWT, exactly the path RLS actually has to defend. This
deliberately does NOT use the service_role key anywhere in those files; that key
bypasses RLS entirely; testing with it would prove nothing about RLS.

Required env vars (see /docs/YOUR_SETUP_CHECKLIST.md for how to create these two
throwaway accounts):
  SUPABASE_URL, SUPABASE_ANON_KEY
  TEST_ACCOUNT_A_EMAIL, TEST_ACCOUNT_A_PASSWORD
  TEST_ACCOUNT_B_EMAIL, TEST_ACCOUNT_B_PASSWORD

Phase 6.2: when these are missing the live tests SKIP locally (so the offline suite still runs) but FAIL when
ISOLATION_REQUIRED=1 — which .github/workflows/isolation.yml sets — so a CI run whose secrets went missing can
never come back green by silently testing nothing.

Fixtures added in Phase 6.2 (shared by test_isolation_matrix.py and test_isolation_api.py):
  world_a / world_b   one row per registered table for each account, built through that account's own client
                      and torn down afterwards (tests/isolation_registry.py)
  anon_client         an unauthenticated client (the anon key, no sign-in)
  audit               the database's own catalog report (migration 0015's rls_audit)
"""
import os

import pytest
from supabase import Client, create_client

from tests.isolation_registry import World


def _need(*names: str) -> None:
    missing = [n for n in names if not os.environ.get(n)]
    if not missing:
        return
    message = f"live isolation tests need these environment variables: {', '.join(missing)}"
    if os.environ.get("ISOLATION_REQUIRED") == "1":
        pytest.fail(message + " (ISOLATION_REQUIRED=1, so this is a failure, not a skip)")
    pytest.skip(message)


def _client_for(email: str, password: str) -> Client:
    url = os.environ["SUPABASE_URL"]
    anon_key = os.environ["SUPABASE_ANON_KEY"]
    client = create_client(url, anon_key)
    client.auth.sign_in_with_password({"email": email, "password": password})
    return client


@pytest.fixture(scope="session")
def client_a() -> Client:
    _need("SUPABASE_URL", "SUPABASE_ANON_KEY", "TEST_ACCOUNT_A_EMAIL", "TEST_ACCOUNT_A_PASSWORD")
    return _client_for(os.environ["TEST_ACCOUNT_A_EMAIL"], os.environ["TEST_ACCOUNT_A_PASSWORD"])


@pytest.fixture(scope="session")
def client_b() -> Client:
    _need("SUPABASE_URL", "SUPABASE_ANON_KEY", "TEST_ACCOUNT_B_EMAIL", "TEST_ACCOUNT_B_PASSWORD")
    return _client_for(os.environ["TEST_ACCOUNT_B_EMAIL"], os.environ["TEST_ACCOUNT_B_PASSWORD"])


@pytest.fixture(scope="session")
def anon_client() -> Client:
    _need("SUPABASE_URL", "SUPABASE_ANON_KEY")
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])


def _built_world(client: Client, label: str):
    world = World(client, label)
    try:
        world.build()
    except BaseException:
        world.cleanup()  # a half-built world must not be left behind in a real database
        raise
    return world


@pytest.fixture(scope="session")
def world_a(client_a):
    world = _built_world(client_a, "A")
    yield world
    world.cleanup()


@pytest.fixture(scope="session")
def world_b(client_b):
    world = _built_world(client_b, "B")
    yield world
    world.cleanup()


@pytest.fixture(scope="session")
def audit(client_a) -> dict:
    return client_a.rpc("rls_audit").execute().data
