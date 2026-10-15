"""
§14.9 (Phase 5.8) — "is the preview the same as the files?" without comparing clocks.

A deploy records the git TREE HASH of the workspace's content (migration 0012, `deploy_runs.workspace_fingerprint`);
`preview_status` computes the same hash now and compares. Equal → the running preview was built from exactly these files.
Different → stale. Unknown (an older run, or the hash couldn't be computed) → say so, never guess.

The hash is computed with a THROWAWAY index (GIT_INDEX_FILE), so the workspace's real index, HEAD and working tree are
never touched — this must be safe to run while the agent or a Push is also using the repo. Build output and dependency
directories are excluded, because they change on every build and say nothing about the source (the workspace has no default
.gitignore, so these are named explicitly); anything the repo's own .gitignore ignores is excluded as well.
"""
import logging
import re

from app.services.workspace_paths import REPO_ROOT

logger = logging.getLogger(__name__)

EXCLUDED_DIRS = (
    "node_modules",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".turbo",
    ".parcel-cache",
    ".cache",
    "dist",
    "build",
    "out",
    "coverage",
    ".venv",
    "venv",
    "__pycache__",
    "target",
    ".qh-scratch-home",
)

_HASH = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")


def build_script() -> str:
    specs = " ".join(f"':(exclude,glob)**/{name}/**'" for name in EXCLUDED_DIRS)
    return f"""set -e
[ -d .git ] || {{ echo "not a git workspace" >&2; exit 3; }}
idx="$(mktemp -u "${{TMPDIR:-/tmp}}/qh-fp.XXXXXX")"
trap 'rm -f "$idx"' EXIT
export GIT_INDEX_FILE="$idx"
git read-tree --empty
git add -A -- . {specs}
git write-tree
"""


def parse_output(exit_code: int, stdout: str) -> str | None:
    if exit_code != 0:
        return None
    value = stdout.strip().splitlines()[-1].strip() if stdout.strip() else ""
    return value if _HASH.match(value) else None


async def compute(project_id: str) -> str | None:
    """The workspace's content fingerprint, or None if it can't be computed (never raises: a deploy must not fail, and a
    status check must not break, because a hash couldn't be taken)."""
    from app.services import workspace_service  # lazy: the script/parse half of this module needs no Sprites SDK

    try:
        result = await workspace_service.exec_in_workspace(project_id, ["bash", "-c", build_script()], timeout=60, cwd=REPO_ROOT)
    except Exception:  # noqa: BLE001
        logger.warning("could not compute workspace fingerprint for project %s", project_id, exc_info=True)
        return None
    return parse_output(result.exit_code, result.stdout)
