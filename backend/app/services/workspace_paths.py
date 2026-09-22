"""
Pure path logic for the Workspace Service (§23) — deliberately zero external
imports (no httpx, no app.config) so it's testable in complete isolation from
the Sprites client. app/services/workspace_service.py imports REPO_ROOT and
resolve_repo_path from here rather than defining them itself.

REPO_ROOT lives under /home/sprite/ — Sprites' own home-directory convention
(see https://docs.sprites.dev). Ported from a Fly Machines integration where
this was /workspace/repo on a separately mounted Volume (see git history /
PHASE2_NOTES.md); a Sprite has no separate volume to mount — the whole
filesystem is one persistent disk — so there's no VOLUME_MOUNT_PATH /
VOLUME_NAME equivalent here anymore (confirmed nothing outside this file and
workspace_service.py ever imported those two).
"""
import re

REPO_ROOT = "/home/sprite/repo"

_VALID_PATH_RE = re.compile(r"^[^\x00]+$")


def resolve_repo_path(relative_path: str) -> str:
    """Every file-tool path argument is relative to the repo root (§14.2's
    `view_file` schema: 'Path relative to the repository root.'). Rejects
    anything that would resolve outside REPO_ROOT — the same boundary
    execute_bash's heuristic guard enforces for shell commands (§14.3),
    enforced here structurally for the three structured file tools instead of
    by pattern matching, since a real path join can be checked exactly."""
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
