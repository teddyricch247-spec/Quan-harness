"""Phase Convert (C8.4) — POST /connections/github-credential/{id}/set-default."""
import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.core.security import AuthedUser
from app.routers import github_credential as router

USER = AuthedUser(user_id="u1", email="a@example.com", email_confirmed=True)
NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def _row(cred_id, is_default):
    return {
        "id": cred_id,
        "credential_type": "pat",
        "label": cred_id,
        "github_app_account_login": "me",
        "is_default": is_default,
        "token_ref": "ref",
        "created_at": NOW,
        "updated_at": NOW,
    }


def test_clears_the_previous_default_before_marking_the_new_one(monkeypatch):
    order: list[str] = []

    async def get_for_user(user_id, cid):
        return _row(cid, False)

    async def clear(user_id):
        order.append("clear")

    async def update(user_id, cid, fields):
        order.append(f"set:{cid}:{fields}")
        return _row(cid, True)

    async def read_secret(ref):
        return "ghp_abcd1234"

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(router.repo, "get_for_user", get_for_user)
    monkeypatch.setattr(router.repo, "clear_default_for_user", clear)
    monkeypatch.setattr(router.repo, "update_for_user", update)
    monkeypatch.setattr(router.vault, "read_secret", read_secret)
    monkeypatch.setattr(router.audit, "record", noop)

    out = asyncio.run(router.set_default("g2", USER))
    assert order == ["clear", "set:g2:{'is_default': True}"]
    assert out.id == "g2" and out.is_default is True and out.token_last_four == "1234"


def test_unknown_credential_is_a_404_and_changes_nothing(monkeypatch):
    changed: list[str] = []

    async def get_for_user(user_id, cid):
        return None

    async def clear(user_id):
        changed.append("clear")

    monkeypatch.setattr(router.repo, "get_for_user", get_for_user)
    monkeypatch.setattr(router.repo, "clear_default_for_user", clear)
    with pytest.raises(HTTPException) as err:
        asyncio.run(router.set_default("nope", USER))
    assert err.value.status_code == 404 and changed == []


def test_a_credential_deleted_mid_request_is_a_404(monkeypatch):
    async def get_for_user(user_id, cid):
        return _row(cid, False)

    async def clear(user_id):
        return None

    async def update(user_id, cid, fields):
        return None  # gone between the lookup and the update

    monkeypatch.setattr(router.repo, "get_for_user", get_for_user)
    monkeypatch.setattr(router.repo, "clear_default_for_user", clear)
    monkeypatch.setattr(router.repo, "update_for_user", update)
    with pytest.raises(HTTPException) as err:
        asyncio.run(router.set_default("g2", USER))
    assert err.value.status_code == 404
