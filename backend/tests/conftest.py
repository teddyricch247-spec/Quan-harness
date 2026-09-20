"""
§5: "RLS must be live-tested, not declared and forgotten. An automated suite
connects to Postgres as the authenticated role using two distinct real
test-account JWTs and asserts, for every user-owned and project-owned table,
that account A's queries against account B's rows return zero rows — run in CI
on every pull request touching a table's schema or policies."

These fixtures sign in as two real Supabase accounts using the anon key — the
same way a browser would — so every query in test_rls_isolation.py runs through
PostgREST as the `authenticated` role with that account's own JWT, exactly the
path RLS actually has to defend. This deliberately does NOT use the service_role
key anywhere in this test file; that key bypasses RLS entirely; testing with it
would prove nothing about RLS.

Required env vars (see /docs/YOUR_SETUP_CHECKLIST.md for how to create these two
throwaway accounts):
  SUPABASE_URL, SUPABASE_ANON_KEY
  TEST_ACCOUNT_A_EMAIL, TEST_ACCOUNT_A_PASSWORD
  TEST_ACCOUNT_B_EMAIL, TEST_ACCOUNT_B_PASSWORD
"""
import os

import pytest
from supabase import Client, create_client


def _client_for(email: str, password: str) -> Client:
    url = os.environ["SUPABASE_URL"]
    anon_key = os.environ["SUPABASE_ANON_KEY"]
    client = create_client(url, anon_key)
    client.auth.sign_in_with_password({"email": email, "password": password})
    return client


@pytest.fixture(scope="session")
def client_a() -> Client:
    return _client_for(os.environ["TEST_ACCOUNT_A_EMAIL"], os.environ["TEST_ACCOUNT_A_PASSWORD"])


@pytest.fixture(scope="session")
def client_b() -> Client:
    return _client_for(os.environ["TEST_ACCOUNT_B_EMAIL"], os.environ["TEST_ACCOUNT_B_PASSWORD"])
