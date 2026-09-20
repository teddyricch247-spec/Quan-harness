"""
Implementation order step 5: 'stood up and tested in isolation — create a
trivial project workspace, run a command, confirm persistence across a
sleep/wake cycle — before wiring any agent tool to it.'

Same convention as test_rls_isolation.py: reads real credentials straight out
of the environment (no fixtures, no mocking) and talks to the real Fly.io
Machines API. Requires:
  FLY_API_TOKEN, FLY_ORG_SLUG  (see /docs/YOUR_SETUP_CHECKLIST.md §2)
and a real Supabase project configured the same way test_rls_isolation.py
needs (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY) plus one already-existing test
user/project row, since ensure_workspace() reads/writes project_workspaces.

Not run as part of this delivery — no live Fly.io account is available in the
sandbox this was built in. See /docs/PHASE2_NOTES.md's testing section for
exactly what was and wasn't possible to verify here.
"""
import asyncio
import os
import uuid

from app.repositories import projects as projects_repo
from app.services import workspace_service

TEST_PROJECT_ID = os.environ.get("QH_TEST_PROJECT_ID")  # a project row that already exists, pending workspace


def test_ensure_workspace_provisions_and_wake_sleep_persist_files():
    if not TEST_PROJECT_ID:
        raise RuntimeError(
            "Set QH_TEST_PROJECT_ID (and FLY_API_TOKEN/FLY_ORG_SLUG) to run this "
            "against a real Fly.io account — see /docs/YOUR_SETUP_CHECKLIST.md §2."
        )

    async def _run():
        workspace = await workspace_service.ensure_workspace(TEST_PROJECT_ID)
        assert not workspace["sprite_handle"].startswith("pending-")
        assert workspace["billing_state"] == "running"

        marker = f"qh-test-{uuid.uuid4().hex[:8]}"
        write = await workspace_service.exec_in_workspace(
            TEST_PROJECT_ID, ["bash", "-c", f"echo {marker} > /workspace/repo/.qh-test-marker"]
        )
        assert write.exit_code == 0

        await workspace_service.sleep(TEST_PROJECT_ID)
        slept = await projects_repo.get_workspace(TEST_PROJECT_ID)
        assert slept["billing_state"] == "cold"

        # The whole point of the volume/machine split (§23.1): the file must
        # still be there after a full stop/start cycle, because it lives on
        # the persistent volume, not on the machine's own ephemeral disk.
        read_back = await workspace_service.exec_in_workspace(
            TEST_PROJECT_ID, ["cat", "/workspace/repo/.qh-test-marker"]
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
