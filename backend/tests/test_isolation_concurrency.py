"""
Phase 6.2 (§5 + §23.4) — the shared-workspace concurrency model, from the isolation side. Offline: these gates are in
memory, so they need no database (the rows behind them are covered by test_isolation_matrix.py and, through the
HTTP surface, test_isolation_api.py).

§23.4: several sessions of ONE project deliberately share that project's workspace, and a Push/Pull must not run
while ANY of them has a turn going. The mirror-image guarantee this file pins is that all of that coordination is
keyed by PROJECT (and, for a turn, by SESSION), never global and never by account — so one account's long turn or
git sync can't block, delay, or even be observed by another account's.
"""
import asyncio
from unittest import mock

from app.services import agent_loop


def _reset():
    agent_loop._running_sessions.clear()
    agent_loop._syncing_projects.clear()


def _list_for_project(rows_by_owner_and_project):
    """Behaves like sessions_repo.list_for_project: rows only for the project's OWNER, None for anyone else."""

    async def fake(user_id, project_id):
        return rows_by_owner_and_project.get((user_id, project_id))

    return fake


def test_a_git_sync_in_one_project_never_blocks_another_projects():
    _reset()
    try:
        assert agent_loop.begin_git_sync("PROJECT-A") is True
        assert agent_loop.begin_git_sync("PROJECT-B") is True          # B's Push is not queued behind A's
        assert agent_loop.begin_git_sync("PROJECT-A") is False         # …while A's second one correctly is
        assert agent_loop.project_is_syncing("PROJECT-A") and agent_loop.project_is_syncing("PROJECT-B")
        agent_loop.end_git_sync("PROJECT-A")
        assert not agent_loop.project_is_syncing("PROJECT-A") and agent_loop.project_is_syncing("PROJECT-B")
    finally:
        _reset()


def test_a_running_turn_in_one_project_does_not_hold_up_another_accounts_push():
    _reset()
    rows = {("USER-A", "PROJECT-A"): [{"id": "A-S1"}, {"id": "A-S2"}], ("USER-B", "PROJECT-B"): [{"id": "B-S1"}]}
    try:
        with mock.patch.object(agent_loop.sessions_repo, "list_for_project", _list_for_project(rows)):
            assert agent_loop._claim_session("A-S1") is True            # A's turn is running
            assert asyncio.run(agent_loop.project_has_running_turn("USER-A", "PROJECT-A")) is True
            assert asyncio.run(agent_loop.project_has_running_turn("USER-B", "PROJECT-B")) is False  # B is free to Push
    finally:
        _reset()


def test_asking_about_someone_elses_project_reveals_nothing_about_its_turns():
    """B asks the gate about A's project. The answer must be the same as for a project with nothing running, or the
    gate becomes a way to watch another account's activity."""
    _reset()
    rows = {("USER-A", "PROJECT-A"): [{"id": "A-S1"}]}
    try:
        with mock.patch.object(agent_loop.sessions_repo, "list_for_project", _list_for_project(rows)):
            agent_loop._claim_session("A-S1")
            idle = asyncio.run(agent_loop.project_has_running_turn("USER-B", "PROJECT-NOBODY-OWNS"))
            probing = asyncio.run(agent_loop.project_has_running_turn("USER-B", "PROJECT-A"))
            assert probing is idle is False
    finally:
        _reset()


def test_every_session_of_one_project_counts_toward_its_gate_and_only_its():
    _reset()
    rows = {("USER-A", "PROJECT-A"): [{"id": "A-S1"}, {"id": "A-S2"}], ("USER-A", "PROJECT-A2"): [{"id": "A-OTHER"}]}
    try:
        with mock.patch.object(agent_loop.sessions_repo, "list_for_project", _list_for_project(rows)):
            agent_loop._claim_session("A-S2")                           # the SECOND session of the shared workspace is the one running
            assert asyncio.run(agent_loop.project_has_running_turn("USER-A", "PROJECT-A")) is True
            assert asyncio.run(agent_loop.project_has_running_turn("USER-A", "PROJECT-A2")) is False  # same account, other project
    finally:
        _reset()


def test_claiming_one_session_never_claims_another():
    _reset()
    try:
        assert agent_loop._claim_session("A-S1") is True
        assert agent_loop._claim_session("A-S1") is False               # one turn per session
        assert agent_loop._claim_session("B-S1") is True                # a different session — anyone's — is unaffected
        agent_loop._release_session("A-S1")
        assert agent_loop.is_running("B-S1") and not agent_loop.is_running("A-S1")
    finally:
        _reset()
