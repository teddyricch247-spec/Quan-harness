"""
§23.4. "Checkpoints are backed by local, never-pushed git commits inside the
workspace's own hidden git history." create_checkpoint() is called unconditionally
by file_tools.py after every successful str_replace/create_file, and by
shell_tools.py after every execute_bash call that could have touched files —
never something the model decides to do.
"""
from app.repositories import audit as audit_repo
from app.repositories import checkpoints as checkpoints_repo
from app.repositories import sessions as sessions_repo
from app.services import workspace_service
from app.services.checkpoint_fifo import FIFO_CAP, select_ids_to_evict
from app.services.workspace_paths import REPO_ROOT

_GIT_ENV = ["-c", "user.email=agent@quanharness.local", "-c", "user.name=Quan Harness"]


class CheckpointRestoreError(ValueError):
    pass


async def create_checkpoint(project_id: str, session_id: str, conversation_snapshot: list | None = None) -> str:
    """Returns the new checkpoint's id. `conversation_snapshot` — db/migrations
    0005's own column comment: "full session_events payload at this point" —
    is populated by agent_loop.py, the one caller that actually holds the
    accumulated event log: it passes the same `events` list it just built
    this iteration's `messages` from (§17's assembled context) straight
    through file_tools.str_replace/create_file and shell_tools.execute_bash
    into this parameter. Still defaults to None/empty for any other caller
    (tests, a future direct invocation) that has no event log in hand — the
    git-commit half of a checkpoint, which is what restore_checkpoint
    actually depends on, is fully real either way."""
    await workspace_service.exec_in_workspace(
        project_id, ["git", *_GIT_ENV, "-C", REPO_ROOT, "add", "-A"], timeout=30
    )
    commit = await workspace_service.exec_in_workspace(
        project_id,
        ["git", *_GIT_ENV, "-C", REPO_ROOT, "commit", "--allow-empty", "-m", "checkpoint"],
        timeout=30,
    )
    if commit.exit_code != 0:
        raise RuntimeError(f"Checkpoint commit failed: {commit.stderr.strip()}")
    sha = await workspace_service.exec_in_workspace(
        project_id, ["git", "-C", REPO_ROOT, "rev-parse", "HEAD"], timeout=15
    )
    git_commit_sha = sha.stdout.strip()

    row = await checkpoints_repo.create(project_id, session_id, git_commit_sha, conversation_snapshot or [])

    ids_oldest_first = [c["id"] for c in await checkpoints_repo.list_for_project_ids_oldest_first(project_id)]
    await checkpoints_repo.delete_many(select_ids_to_evict(ids_oldest_first))

    return row["id"]


async def restore_checkpoint(user_id: str, checkpoint_id: str) -> dict:
    """§23.4. Raises CheckpointRestoreError (caught by the router and turned into
    a 400/403) for every rule this section states as a hard restriction."""
    checkpoint = await checkpoints_repo.get_owned(user_id, checkpoint_id)
    if checkpoint is None:
        raise CheckpointRestoreError("Checkpoint not found.")

    session = await sessions_repo.get_owned(user_id, checkpoint["session_id"])
    if session is None:
        raise CheckpointRestoreError("The session this checkpoint belongs to no longer exists.")

    active_session_id = await checkpoints_repo.get_active_session_id(checkpoint["project_id"])
    if active_session_id != checkpoint["session_id"]:
        raise CheckpointRestoreError(
            "This session is no longer the active one for this project — only the "
            "session that most recently edited the workspace can restore checkpoints."
        )
    if session["read_only"]:
        raise CheckpointRestoreError("This session is already read-only and cannot perform a restore.")

    await workspace_service.exec_in_workspace(
        checkpoint["project_id"],
        ["git", "-C", REPO_ROOT, "reset", "--hard", checkpoint["git_commit_sha"]],
        timeout=30,
    )

    # "Permanently deletes every message and checkpoint created after it, within
    # that session."
    await sessions_repo.delete_events_after(checkpoint["session_id"], checkpoint["created_at"])
    await checkpoints_repo.delete_after(checkpoint["session_id"], checkpoint["created_at"])

    await sessions_repo.close_others_to_read_only(
        checkpoint["project_id"], except_session_id=checkpoint["session_id"], reason="checkpoint_restore"
    )

    # 0005_sessions.sql's audit_log.tool comment lists 'checkpoint_restore' as an
    # expected value — this is exactly the irreversible, user-triggered action
    # push/pull already audit (git_sync.py), and restore deserves the same trail.
    await audit_repo.record(
        user_id, "checkpoint_restore", "restore", True,
        project_id=checkpoint["project_id"], session_id=checkpoint["session_id"],
        output_summary=checkpoint["git_commit_sha"], initiated_by="user",
    )

    return checkpoint
