"""
Pure path logic for the Workspace Service (§23) — deliberately zero external
imports (no httpx, no app.config) so it's testable in complete isolation from
the Fly.io client. app/services/workspace_service.py imports REPO_ROOT and
resolve_repo_path from here rather than defining them itself.
"""
import re

REPO_ROOT = "/workspace/repo"
VOLUME_MOUNT_PATH = "/workspace"
VOLUME_NAME = "workspace_data"

_VALID_PATH_RE = re.compile(r"^[^\x00]+$")


def resolve_repo_path(relative_path: str) -> str:
    """Every file-tool path argument is relative to the repo root (§14.2's
    `view_file` schema: 'Path relative to the repository root.'). Rejects
    anything that would resolve outside REPO_ROOT — the same boundary
    execute_bash's heuristic guard enforces for shell commands (§14.3), enforced
    here structurally for the three structured file tools instead of by pattern
    matching, since a real path join can be checked exactly."""
    if not relative_path or not _VALID_PATH_RE.match(relative_path):
        raise ValueError("Invalid path.")
    if relative_path.startswith("/"):
        raise ValueError("Path must be relative to the repository root, not absolute.")
    normalized_parts = [part for part in relative_path.split("/") if part not in ("", ".")]
    segments: list[str] = []
    for part in normalized_parts:
        if part == "..":
            if not segments:
                raise ValueError("Path escapes the repository root.")
            segments.pop()
        else:
            segments.append(part)
    return f"{REPO_ROOT}/{'/'.join(segments)}" if segments else REPO_ROOT
