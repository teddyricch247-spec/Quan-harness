"""
Implementation order step 5: 'stood up and tested in isolation — create a
trivial project workspace, run a command, confirm persistence — before wiring
any agent tool to it.'

Same convention as test_rls_isolation.py: reads real credentials straight out
of the environment (no fixtures, no mocking) and talks to the real Fly.io
Sprites API. Requires:
  SPRITES_API_TOKEN  (see /docs/YOUR_SETUP_CHECKLIST.md §3)
and a real Supabase project configured the same way test_rls_isolation.py
needs (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY) plus one already-existing test
user/project row, since ensure_workspace() reads/writes project_workspaces.

Ported from a Fly Machines version of this test (see git history /
PHASE2_NOTES.md) — the old assertion that billing_state reads "cold" right
after sleep() no longer holds: Sprites expose no manual pause endpoint, so
sleep() now just refreshes billing_state from the Sprite's own reported
status instead of commanding a stop (see workspace_service.py's module
docstring). This checks persistence across two separate exec calls instead of
across a forced stop/start cycle — the guarantee that actually matters (files
outlive any one command) is the same either way.

Not run as part of this delivery — no live Fly.io account is available in the
sandbox this was written in. See /docs/PHASE2_NOTES.md's testing section for
exactly what was and wasn't possible to verify here.
"""
import asyncio
import os
import uuid

from app.repositories import projects as projects_repo
from app.services import workspace_service
from app.services.workspace_paths import REPO_ROOT

TEST_PROJECT_ID = os.environ.get("QH_TEST_PROJECT_ID")  # a project row that already exists, pending workspace


def test_ensure_workspace_provisions_and_files_persist_across_calls():
    if not TEST_PROJECT_ID:
        raise RuntimeError(
            "Set QH_TEST_PROJECT_ID (and SPRITES_API_TOKEN) to run this "
            "against a real Fly.io account — see /docs/YOUR_SETUP_CHECKLIST.md §3."
        )

    async def _run():
        workspace = await workspace_service.ensure_workspace(TEST_PROJECT_ID)
        assert not workspace["sprite_handle"].startswith("pending-")
        assert workspace["billing_state"] == "running"

        marker = f"qh-test-{uuid.uuid4().hex[:8]}"
        write = await workspace_service.exec_in_workspace(
            TEST_PROJECT_ID, ["bash", "-c", f"echo {marker} > {REPO_ROOT}/.qh-test-marker"]
        )
        assert write.exit_code == 0

        await workspace_service.sleep(TEST_PROJECT_ID)

        # The whole point of a Sprite's persistent filesystem (§23.1): the
        # file is still there on a completely separate exec call. There's no
        # stop/start cycle to force anymore (Sprites don't expose one), but
        # every exec below is its own fresh connection, so this genuinely
        # isn't just reading back the same in-memory process.
        read_back = await workspace_service.exec_in_workspace(
            TEST_PROJECT_ID, ["cat", f"{REPO_ROOT}/.qh-test-marker"]
        )
        assert read_back.stdout.strip() == marker

        woken = await projects_repo.get_workspace(TEST_PROJECT_ID)
        assert woken["billing_state"] == "running"

    asyncio.run(_run())


def test_execute_bash_cannot_reach_the_git_sync_credential():
    """Step 6's live counterpart to test_execute_bash_env_isolation.py's
    structural tests: proves the isolation holds against a real workspace, not
    just by inspecting build_bash_env's signature."""
    if not TEST_PROJECT_ID:
        raise RuntimeError("Set QH_TEST_PROJECT_ID — see the module docstring.")
    from app.services import shell_tools

    async def _run():
        result = await shell_tools.execute_bash(
            TEST_PROJECT_ID,
            session_id="test-session",
            user_id="test-user",
            command="env",
        )
        assert result.executed
        for leaked_marker in ("GITHUB_TOKEN", "ghp_", "GH_TOKEN", "x-access-token"):
            assert leaked_marker not in result.stdout

    asyncio.run(_run())
