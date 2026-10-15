"""
Implementation order step 7: 'build and test these before wiring the agent loop
to anything, so the sync mechanism is proven correct in isolation first, with
zero agent-facing surface of any kind.'

Requires a real Fly workspace (see test_workspace_integration.py) plus a real
GitHub credential connected for the test user (a PAT with `repo` scope is
enough — see /docs/YOUR_SETUP_CHECKLIST.md §1). Creates a real (private, by
default) repository under that account's GitHub — clean up manually afterward.
Not run as part of this delivery, same reasoning as test_workspace_integration.py.
"""
import asyncio
import os

from app.services import git_sync

TEST_USER_ID = os.environ.get("QH_TEST_USER_ID")
TEST_PROJECT_ID = os.environ.get("QH_TEST_PROJECT_ID")


def test_push_creates_repo_and_pull_round_trips():
    if not (TEST_USER_ID and TEST_PROJECT_ID):
        raise RuntimeError(
            "Set QH_TEST_USER_ID and QH_TEST_PROJECT_ID against a real account with a "
            "connected GitHub credential — see /docs/YOUR_SETUP_CHECKLIST.md."
        )

    async def _run():
        push_result = await git_sync.push(TEST_USER_ID, TEST_PROJECT_ID, repo_name=None, private=True)
        assert push_result["branch"] == git_sync.HARNESS_BRANCH
        assert push_result["commit_sha"]

        # Pull immediately after a Push, with nothing changed locally in
        # between, must report no confirmation needed — local already matches
        # exactly what was just pushed.
        pull_result = await git_sync.pull(TEST_USER_ID, TEST_PROJECT_ID, confirm_discard=False)
        assert pull_result["needs_confirmation"] is False

    asyncio.run(_run())


def test_pull_requires_confirmation_when_local_changes_would_be_discarded():
    if not (TEST_USER_ID and TEST_PROJECT_ID):
        raise RuntimeError("Set QH_TEST_USER_ID and QH_TEST_PROJECT_ID — see the module docstring.")

    async def _run():
        from app.services import workspace_service
        from app.services.workspace_paths import REPO_ROOT

        await workspace_service.exec_in_workspace(
            TEST_PROJECT_ID, ["bash", "-c", f"echo unpushed >> {REPO_ROOT}/untracked-local-change.txt"]
        )
        result = await git_sync.pull(TEST_USER_ID, TEST_PROJECT_ID, confirm_discard=False)
        assert result["needs_confirmation"] is True

        confirmed = await git_sync.pull(TEST_USER_ID, TEST_PROJECT_ID, confirm_discard=True)
        assert confirmed["needs_confirmation"] is False

    asyncio.run(_run())
