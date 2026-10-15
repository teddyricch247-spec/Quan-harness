"""
Phase Convert (C8.1, C8.6) — POST /projects, both shapes, with every collaborator faked.

These call `create_project` directly (the way the rest of this suite calls its units) rather than
through an HTTP client, with the repositories and services monkeypatched, so they need no
database, no Sprites and no network. What they pin down:

- without `prompt` the endpoint is exactly what it was: a ProjectOut, no session, no turn;
- with `prompt` it creates project + session + turn in one call and derives the name;
- if an early setup step fails the project is deleted again (the compensation), and nothing is
  started;
- once the session exists the project is kept even if the turn can't start;
- the three stable error codes, and that nothing is created before they are raised.
"""
import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app import dependencies
from app.core.security import AuthedUser
from app.models.schemas import ProjectCreate, ProjectOut, ProjectStartOut
from app.routers import projects as router

USER = AuthedUser(user_id="u1", email="a@example.com", email_confirmed=True)


class Recorder:
    """Everything the endpoint touched, in order, so a test can assert on what did NOT happen."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.project_row: dict | None = None

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]


def _install(
    monkeypatch,
    *,
    default_llm=True,
    default_github=None,
    github_by_id=None,
    session_fails=False,
    turn="ok",  # "ok" | "refused" | "raises"
    pull_error=None,
):
    rec = Recorder()

    async def create(user_id, row):
        rec.calls.append(("project.create", row))
        rec.project_row = {
            "id": "p1",
            "created_at": datetime(2026, 10, 10, tzinfo=timezone.utc),
            "max_turn_iterations": 50,
            "harness_branch_ready": False,
            "deploy_targets": [],
            "deploy_targets_confirmed": False,
            **row,
        }
        return rec.project_row

    async def delete_for_user(user_id, project_id):
        rec.calls.append(("project.delete", project_id))
        return True

    async def create_workspace_stub(project_id, sprite_handle):
        rec.calls.append(("workspace.stub", project_id))

    async def grant(project_id, ids):
        rec.calls.append(("connectors.grant", list(ids)))

    async def get_workspace(project_id):
        return {"billing_state": "cold", "sprite_handle": "pending-x"}

    async def noop(*a, **k):
        return None

    async def create_session(user_id, project_id, title, **k):
        rec.calls.append(("session.create", project_id))
        if session_fails:
            raise RuntimeError("insert failed")
        return {"id": "s1"}

    async def start_turn(session_id, user_id, text):
        rec.calls.append(("turn.start", session_id, text))
        if turn == "raises":
            raise RuntimeError("boom")
        return turn == "ok"

    async def pull(user_id, project_id, confirm_discard=False):
        rec.calls.append(("pull", project_id))
        if pull_error:
            raise router.git_sync.GitSyncError(pull_error)

    async def llm_default(user_id):
        return {"id": "k1"} if default_llm else None

    async def gh_default(user_id):
        return default_github

    async def gh_by_id(user_id, cid):
        return (github_by_id or {}).get(cid)

    async def get_repository(token, full_name):
        return {"full_name": full_name, "default_branch": "main"}

    async def read_secret(ref):
        return "token"

    monkeypatch.setattr(router.repo, "create", create)
    monkeypatch.setattr(router.repo, "delete_for_user", delete_for_user)
    monkeypatch.setattr(router.repo, "create_workspace_stub", create_workspace_stub)
    monkeypatch.setattr(router.repo, "grant_connector_access", grant)
    monkeypatch.setattr(router.repo, "get_workspace", get_workspace)
    monkeypatch.setattr(router.preview_runtime, "ensure_preview_subdomain", noop)
    monkeypatch.setattr(router.audit, "record", noop)
    monkeypatch.setattr(router.sessions_repo, "create_for_project", create_session)
    monkeypatch.setattr(router.agent_loop, "start_turn", start_turn)
    monkeypatch.setattr(router.git_sync, "pull", pull)
    monkeypatch.setattr(router.llm_repo, "get_default_for_user", llm_default)
    monkeypatch.setattr(router.github_repo, "get_default_for_user", gh_default)
    monkeypatch.setattr(router.github_repo, "get_for_user", gh_by_id)
    monkeypatch.setattr(router.github_oauth, "get_repository", get_repository)
    monkeypatch.setattr(router.vault, "read_secret", read_secret)
    monkeypatch.setattr(router.workspace_setup, "kick_off", lambda pid: rec.calls.append(("workspace.kick_off", pid)))
    monkeypatch.setattr(router.workspace_setup, "forget", lambda pid: rec.calls.append(("workspace.forget", pid)))
    return rec


def _run(body: ProjectCreate):
    return asyncio.run(router.create_project(body, USER))


def _code(exc: HTTPException) -> str:
    assert isinstance(exc.detail, dict), exc.detail
    return exc.detail["code"]


# --- the legacy shape: no prompt -------------------------------------------------------------


def test_without_prompt_it_is_exactly_the_old_behavior(monkeypatch):
    rec = _install(monkeypatch)
    out = _run(ProjectCreate(name="Legacy"))
    assert isinstance(out, ProjectOut) and out.name == "Legacy"
    assert "session.create" not in rec.names() and "turn.start" not in rec.names()
    assert "workspace.kick_off" not in rec.names()


def test_without_prompt_a_setup_failure_is_not_rolled_back(monkeypatch):
    rec = _install(monkeypatch)

    async def boom(project_id, sprite_handle):
        raise RuntimeError("stub failed")

    monkeypatch.setattr(router.repo, "create_workspace_stub", boom)
    with pytest.raises(RuntimeError):
        _run(ProjectCreate(name="Legacy"))
    assert "project.delete" not in rec.names()  # "exactly as today": the legacy path never compensated


def test_scratch_without_name_or_prompt_is_still_rejected(monkeypatch):
    rec = _install(monkeypatch)
    for body in (ProjectCreate(), ProjectCreate(name="   ")):
        with pytest.raises(HTTPException) as err:
            _run(body)
        assert err.value.status_code == 422
    assert rec.calls == []


def test_a_new_repository_without_a_name_is_named_after_the_repository(monkeypatch):
    rec = _install(monkeypatch, default_github={"id": "g1", "token_ref": "ref"})

    async def create_repository(token, name, private):
        return {"full_name": f"me/{name}", "default_branch": "main"}

    monkeypatch.setattr(router.github_oauth, "create_repository", create_repository)
    out = _run(ProjectCreate(mode="create_new_repo", new_repo_name="shiny-app"))
    assert isinstance(out, ProjectOut) and out.name == "Shiny-app"


# --- the one-call shape -----------------------------------------------------------------------


def test_prompt_creates_project_session_and_turn_and_derives_the_name(monkeypatch):
    rec = _install(monkeypatch)
    out = _run(ProjectCreate(prompt="  Build a habit tracker with streaks  "))
    assert isinstance(out, ProjectStartOut)
    assert out.project.name == "Build a habit tracker with streaks"
    assert out.session_id == "s1" and out.turn.status == "running"
    assert rec.names() == ["project.create", "workspace.stub", "connectors.grant", "session.create", "workspace.kick_off", "turn.start"]
    assert rec.calls[-1] == ("turn.start", "s1", "Build a habit tracker with streaks")  # stripped


def test_an_explicit_name_is_kept(monkeypatch):
    rec = _install(monkeypatch)
    out = _run(ProjectCreate(name="  Mine  ", prompt="whatever"))
    assert out.project.name == "Mine"


def test_no_credential_ids_are_sent_when_the_client_sends_none(monkeypatch):
    rec = _install(monkeypatch)
    _run(ProjectCreate(prompt="hello"))
    row = rec.calls[0][1]
    assert row["llm_credential_id"] is None and row["github_credential_id"] is None


def test_connector_ids_are_granted(monkeypatch):
    rec = _install(monkeypatch)

    async def connector(user_id, cid):
        return {"id": cid}

    monkeypatch.setattr(router.connectors_repo, "get_for_user", connector)
    _run(ProjectCreate(prompt="hello", connector_ids=["c1", "c2"]))
    assert ("connectors.grant", ["c1", "c2"]) in rec.calls


# --- compensation -----------------------------------------------------------------------------


def test_session_insert_failure_deletes_the_project_and_starts_nothing(monkeypatch):
    rec = _install(monkeypatch, session_fails=True)
    with pytest.raises(HTTPException) as err:
        _run(ProjectCreate(prompt="hello"))
    assert err.value.status_code == 500
    assert ("project.delete", "p1") in rec.calls
    assert "turn.start" not in rec.names() and "workspace.kick_off" not in rec.names()


def test_workspace_stub_failure_also_rolls_back(monkeypatch):
    rec = _install(monkeypatch)

    async def boom(project_id, sprite_handle):
        raise RuntimeError("stub failed")

    monkeypatch.setattr(router.repo, "create_workspace_stub", boom)
    with pytest.raises(HTTPException):
        _run(ProjectCreate(prompt="hello"))
    assert ("project.delete", "p1") in rec.calls


def test_a_new_repository_that_was_already_created_is_named_in_the_error(monkeypatch):
    rec = _install(monkeypatch, default_github={"id": "g1", "token_ref": "ref"}, session_fails=True)

    async def create_repository(token, name, private):
        return {"full_name": f"me/{name}", "default_branch": "main"}

    monkeypatch.setattr(router.github_oauth, "create_repository", create_repository)
    with pytest.raises(HTTPException) as err:
        _run(ProjectCreate(prompt="hello", mode="create_new_repo", new_repo_name="shiny"))
    assert "me/shiny" in err.value.detail and "not deleted" in err.value.detail


# --- the turn can fail without losing the project ---------------------------------------------


@pytest.mark.parametrize("how", ["refused", "raises"])
def test_turn_failure_keeps_the_project_and_reports_failed(monkeypatch, how):
    rec = _install(monkeypatch, turn=how)
    out = _run(ProjectCreate(prompt="hello"))
    assert out.turn.status == "failed" and out.session_id == "s1"
    assert "project.delete" not in rec.names()


# --- import ------------------------------------------------------------------------------------


def test_import_uses_the_default_github_credential_and_stores_it(monkeypatch):
    rec = _install(monkeypatch, default_github={"id": "g9", "token_ref": "ref"})
    out = _run(ProjectCreate(prompt="", mode="import", github_repo="acme/widget-shop"))
    # empty prompt on import: legacy-shaped answer, project named after the repo, credential stored
    assert isinstance(out, ProjectOut) and out.name == "Widget-shop"
    assert rec.calls[0][1]["github_credential_id"] == "g9"
    assert ("pull", "p1") in rec.calls


def test_import_with_a_prompt_starts_the_turn_after_a_good_pull(monkeypatch):
    rec = _install(monkeypatch, default_github={"id": "g9", "token_ref": "ref"})
    out = _run(ProjectCreate(prompt="add tests", mode="import", github_repo="acme/widget-shop"))
    assert out.turn.status == "running"
    assert rec.names().index("pull") < rec.names().index("turn.start")


def test_import_whose_pull_fails_keeps_the_project_and_holds_the_turn_back(monkeypatch):
    rec = _install(monkeypatch, default_github={"id": "g9", "token_ref": "ref"}, pull_error="no workspace yet")
    out = _run(ProjectCreate(prompt="add tests", mode="import", github_repo="acme/widget-shop"))
    assert out.turn.status == "not_started"
    assert out.project.import_pull_error == "no workspace yet"
    assert "turn.start" not in rec.names() and "project.delete" not in rec.names()


# --- stable error codes -------------------------------------------------------------------------


def test_llm_key_required_is_raised_before_anything_is_created(monkeypatch):
    rec = _install(monkeypatch, default_llm=False)
    with pytest.raises(HTTPException) as err:
        _run(ProjectCreate(prompt="hello"))
    assert err.value.status_code == 400 and _code(err.value) == "llm_key_required"
    assert rec.calls == []


def test_llm_key_required_is_checked_before_a_github_repository_is_created(monkeypatch):
    rec = _install(monkeypatch, default_llm=False, default_github={"id": "g1", "token_ref": "ref"})
    created = []

    async def create_repository(token, name, private):
        created.append(name)
        return {"full_name": f"me/{name}", "default_branch": "main"}

    monkeypatch.setattr(router.github_oauth, "create_repository", create_repository)
    with pytest.raises(HTTPException):
        _run(ProjectCreate(prompt="hello", mode="create_new_repo", new_repo_name="shiny"))
    assert created == []


def test_no_prompt_means_no_llm_requirement(monkeypatch):
    _install(monkeypatch, default_llm=False)
    assert isinstance(_run(ProjectCreate(name="Legacy")), ProjectOut)  # as before: the key is only needed to run a turn


@pytest.mark.parametrize("mode,extra", [("import", {"github_repo": "a/b"}), ("create_new_repo", {"new_repo_name": "x"})])
def test_github_not_connected_when_there_is_no_default(monkeypatch, mode, extra):
    rec = _install(monkeypatch, default_github=None)
    with pytest.raises(HTTPException) as err:
        _run(ProjectCreate(prompt="hello", mode=mode, **extra))
    assert err.value.status_code == 400 and _code(err.value) == "github_not_connected"
    assert rec.calls == []


def test_import_still_requires_a_repository_name_as_a_plain_400(monkeypatch):
    _install(monkeypatch)
    with pytest.raises(HTTPException) as err:
        _run(ProjectCreate(mode="import"))
    assert err.value.status_code == 400 and isinstance(err.value.detail, str)


def test_email_not_verified_carries_a_code(monkeypatch):
    class _FailingClient:
        class auth:
            class admin:
                @staticmethod
                def get_user_by_id(user_id):
                    raise RuntimeError("no network in tests")  # any lookup failure counts as "not verified"

    monkeypatch.setattr(dependencies, "get_service_client", lambda: _FailingClient)
    unverified = AuthedUser(user_id="u2", email="b@example.com", email_confirmed=False)
    with pytest.raises(HTTPException) as err:
        asyncio.run(dependencies.verified_user_coded(unverified))
    assert err.value.status_code == 403 and _code(err.value) == "email_not_verified"
    # the plain dependency every other endpoint uses keeps its string detail
    with pytest.raises(HTTPException) as plain:
        asyncio.run(dependencies.verified_user(unverified))
    assert plain.value.status_code == 403 and isinstance(plain.value.detail, str)
