"""§23.7/§23.1 — enter token + session cookie. See app/services/preview_tokens.py."""
import time

import jwt

from app.services import preview_tokens as t
from app.services.preview_tokens import PreviewTokenError

SECRET = "unit-test-signing-secret-0123456789abcdef"


def _expect_error(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except PreviewTokenError:
        return
    raise AssertionError("expected PreviewTokenError")


def setup_function(_):
    t._reset_for_tests()


def test_enter_token_roundtrips_and_carries_project_and_subdomain():
    t._reset_for_tests()
    token = t.mint_enter_token(SECRET, "proj-1", "my-app-1a2b3c4d", user_id="u1")
    claims = t.redeem_enter_token(SECRET, token, "my-app-1a2b3c4d")
    assert claims["pid"] == "proj-1" and claims["sd"] == "my-app-1a2b3c4d" and claims["uid"] == "u1"


def test_enter_token_is_single_use():
    t._reset_for_tests()
    token = t.mint_enter_token(SECRET, "p", "sub-a")
    t.redeem_enter_token(SECRET, token, "sub-a")
    _expect_error(t.redeem_enter_token, SECRET, token, "sub-a")


def test_token_for_one_preview_cannot_be_replayed_against_another():
    t._reset_for_tests()
    token = t.mint_enter_token(SECRET, "p", "sub-a")
    _expect_error(t.redeem_enter_token, SECRET, token, "sub-b")


def test_expired_token_is_rejected():
    t._reset_for_tests()
    token = t.mint_enter_token(SECRET, "p", "sub-a", ttl_seconds=-120)  # already past its exp
    _expect_error(t.redeem_enter_token, SECRET, token, "sub-a")
    session = t.mint_session_token(SECRET, "p", "sub-a", -120)
    _expect_error(t.verify_session_token, SECRET, session, "sub-a")


def test_wrong_secret_is_rejected():
    t._reset_for_tests()
    token = t.mint_enter_token(SECRET, "p", "sub-a")
    _expect_error(t.redeem_enter_token, "a-different-secret-entirely-0123456789ab", token, "sub-a")


def test_enter_token_cannot_be_used_as_a_session_and_vice_versa():
    t._reset_for_tests()
    enter = t.mint_enter_token(SECRET, "p", "sub-a")
    session = t.mint_session_token(SECRET, "p", "sub-a", 3600)
    _expect_error(t.verify_session_token, SECRET, enter, "sub-a")
    _expect_error(t.redeem_enter_token, SECRET, session, "sub-a")


def test_session_token_verifies_repeatedly_unlike_enter():
    t._reset_for_tests()
    session = t.mint_session_token(SECRET, "p", "sub-a", 3600)
    assert t.verify_session_token(SECRET, session, "sub-a")["pid"] == "p"
    assert t.verify_session_token(SECRET, session, "sub-a")["pid"] == "p"


def test_alg_none_token_is_rejected():
    t._reset_for_tests()
    forged = jwt.encode({"aud": "qh-preview", "use": "session", "pid": "p", "sd": "sub-a", "jti": "x", "exp": int(time.time()) + 600}, key=None, algorithm="none")
    _expect_error(t.verify_session_token, SECRET, forged, "sub-a")


def test_missing_required_claim_is_rejected():
    t._reset_for_tests()
    forged = jwt.encode({"aud": "qh-preview", "use": "session", "sd": "sub-a", "exp": int(time.time()) + 600}, SECRET, algorithm="HS256")
    _expect_error(t.verify_session_token, SECRET, forged, "sub-a")


def test_unconfigured_secret_refuses_to_mint_or_verify():
    _expect_error(t.mint_enter_token, "", "p", "sub-a")
    _expect_error(t.verify_session_token, "", "whatever", "sub-a")
