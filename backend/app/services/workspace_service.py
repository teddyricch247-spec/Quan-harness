"""
§23: the Workspace Service — the sandboxed environment behind every project
(§14.6: "the model's tools ... operate against a project's own persistent
workspace, provisioned lazily on first use"). exec_in_workspace() is the one
primitive app/services/file_tools.py, shell_tools.py, checkpoints.py, and
git_sync.py are all built on top of — none of them talk to Sprites directly.

Backed by Fly.io Sprites (https://sprites.dev) via the official `sprites-py`
SDK (PyPI: sprites-py, import name `sprites`) — one Sprite per project, holding
its repo checkout at REPO_ROOT (app/services/workspace_paths.py). Ported from
a Fly.io Machines integration (see git history / PHASE2_NOTES.md's "Workspace
Service" entry) — kept identical where it mattered: same function names and
signatures (ensure_workspace, wake, sleep, exec_in_workspace, ExecResult), same
project_workspaces.sprite_handle / .billing_state columns, so nothing in
file_tools.py / shell_tools.py / checkpoints.py / git_sync.py /
routers/workspace.py / routers/projects.py had to change.

What's genuinely simpler on Sprites than it was on Machines, and why:
  - No separate App + Volume + Machine to provision — a Sprite is one unit
    with its own built-in persistent disk (100GB, fixed size). ensure_workspace()
    below is a single create_sprite() call plus REPO_ROOT's own `git init`,
    not a four-step App/Volume/Machine/wait-for-started sequence.
  - No manual start/stop — Sprites hibernate automatically ~30s after the
    last request and wake automatically on the next one (100ms-2s), so
    exec_in_workspace() can call the SDK directly with no wait-for-state
    polling step the way Machines needed. wake() below still exists (it's
    the UI's manual "resume before you open a session" action — see
    routers/workspace.py) — it just no longer has to do very much.
  - No bootstrap install step — every Sprite ships with git and python3
    preinstalled, so PHASE2_NOTES.md's old rough edge #2 is moot here.
  - No image/region/CPU/memory/volume-size settings — see config.py's
    comment on sprites_api_token for why those are all gone from Settings.

What's a real behavior change, flagged rather than hidden:
  - sleep() can no longer force a Sprite to stop right now — Sprites expose
    no manual pause endpoint, only automatic idle hibernation. It's kept as a
    function (nothing calls it today, but §23.1 anticipated a future idle
    reaper using it) and now just refreshes billing_state from the Sprite's
    own reported status instead of commanding a stop.
  - billing_state is therefore a last-known snapshot, not a live push — it
    updates whenever ensure_workspace()/wake()/sleep() run, but Sprites has
    no webhook for "a Sprite just went idle," so a workspace that's been
    untouched for a while can still show "running" in the DB after it has
    actually hibernated on Fly's side. Harmless (the next exec just wakes it
    again transparently) but worth knowing if the UI ever needs a truly live
    badge — that would mean polling get_sprite() from routers/workspace.py's
    GET endpoint, not something this module does on its own today.

ROUGH EDGE (flagged the same way PHASE2_NOTES.md flagged the old Machines
`/exec` response shape — a real gap, not a guess dressed up as fact):
`sprites-py` shipped its first stable release on 2026-09-17 — days before
this was written. Three things below are inferred rather than confirmed
against a source-level signature check, since no live Sprites account or
outbound network access was available in the environment this was written in
to actually install the package and inspect it: `sprite.run(..., dir=cwd)`'s
`dir` kwarg name (inferred from the SDK's REST API using that same
query-string parameter for exec — https://sprites.dev/api/sprites/exec — and
from `create_service(..., dir="/app")` using that exact kwarg name in the
SDK's own README); that `client.sprite(name)` is a plain, non-async handle
constructor with no I/O (inferred from it being used unawaited everywhere the
docs show it); and the exception handling below, inferred from the README's
explicit "subprocess.run style" framing. Run test_workspace_integration.py
(already updated for Sprites) against your real account before leaning on
this in production — if `dir=` turns out to be the wrong kwarg name, the fix
is one line (wrap the argv in `["bash", "-c", f"cd {cwd} && ..."]` instead,
the same trick this codebase's own git_sync.py/checkpoints.py already use
elsewhere).

A related, already-fixed gap worth knowing about: `project_workspaces.billing_state`
has a DB check constraint (db/migrations/0004_projects.sql) limiting it to
exactly 'running'/'warm'/'cold'. sleep() below maps whatever status string
the Sprite reports onto one of those three rather than writing it through
unvalidated — Sprites' own status vocabulary isn't confirmed either, so an
unrecognized value falls back to 'running' instead of crashing the update.

One thing that IS confirmed, not just inferred: create_sprite() below is
deliberately called without a `url_settings` argument, and that's safe rather
than an oversight — Fly's own docs (docs.sprites.dev/reference/configuration)
state the `auth` default is `"sprite"` (bearer-token-gated), not `"public"`,
so a freshly created Sprite isn't openly reachable on the internet by
default. Worth knowing regardless, since this workspace holds a project's
actual code: don't call update_sprite(..., url_settings=URLSettings(auth="public"))
anywhere without meaning to.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sprites import AsyncSpritesClient

from app.config import get_settings
from app.repositories import projects as projects_repo
from app.services.workspace_paths import REPO_ROOT


class WorkspaceProvisionError(RuntimeError):
    pass


class WorkspaceExecError(RuntimeError):
    pass


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


def new_workspace_stub_handle() -> str:
    """Phase 1's placeholder, written by projects_repo.create_workspace_stub()
    at project-creation time, before Phase 2 provisions anything real. Kept
    identical to the Machines-era version — every caller/check that looks for
    a 'pending-' prefix (routers/projects.py, ensure_workspace() below) still
    works unchanged."""
    return f"pending-{uuid.uuid4()}"


def _sprite_name(project_id: str) -> str:
    """Deterministic from project_id, so ensure_workspace() never has to
    remember a Fly-assigned id the way the Machines version did (a Fly App
    name was ours to choose; a Machine id wasn't — a Sprite's name is ours to
    choose, full stop). Truncated the same defensively-conservative way the
    old Fly App name was, even though Sprites' own name-length limit isn't
    published anywhere this could confirm it against."""
    return f"qh-{project_id}"[:63]


def _new_client() -> AsyncSpritesClient:
    settings = get_settings()
    return AsyncSpritesClient(token=settings.sprites_api_token, base_url=settings.sprites_api_base, timeout=30.0)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def ensure_workspace(project_id: str) -> dict:
    """The one entry point that guarantees a project has a real, usable Sprite
    behind it. Called by wake() and, internally, by exec_in_workspace() itself
    on every call — cheap once already provisioned (one Supabase read, zero
    Sprites API calls on the common path, since Sprites don't need an
    explicit "make sure this is started" call the way Machines did; see the
    module docstring)."""
    workspace = await projects_repo.get_workspace(project_id)
    if workspace is None:
        raise WorkspaceProvisionError(f"No workspace record for project {project_id}.")
    if not workspace["sprite_handle"].startswith("pending-"):
        # Already provisioned — the common case on every exec_in_workspace()
        # call. Still worth a cheap Supabase write (no Sprites API call) to
        # keep last_active_at meaningful for the UI/any future idle reaper;
        # if that write volume ever becomes a real cost at scale, this is the
        # line to throttle or drop first.
        return await projects_repo.update_workspace(project_id, {"last_active_at": _now_iso()})

    name = _sprite_name(project_id)
    async with _new_client() as client:
        try:
            sprite = await client.create_sprite(name, labels=["quan-harness"], wait_for_capacity=True)
        except Exception as exc:  # noqa: BLE001 — see module docstring's ROUGH EDGE note
            # Idempotency for a retried request whose Sprite got created but
            # whose DB write then failed: treat a name-conflict-shaped error
            # as success rather than a hard failure — the same defensive
            # idiom the Machines-era version used for Fly's own "already
            # exists" 4xx response.
            message = str(exc).lower()
            if not any(token in message for token in ("exist", "taken", "conflict", "409")):
                raise WorkspaceProvisionError(f"Could not create Sprite {name}: {exc}") from exc
            sprite = client.sprite(name)

        init = await sprite.run(
            "bash",
            "-c",
            f"mkdir -p {REPO_ROOT} && git -C {REPO_ROOT} rev-parse --git-dir "
            f"|| git -C {REPO_ROOT} init -q",
            capture_output=True,
            timeout=30,
        )
        if init.returncode != 0:
            raise WorkspaceProvisionError(
                f"Could not initialize {REPO_ROOT} on {name}: {init.stderr.decode(errors='replace').strip()}"
            )

    return await projects_repo.update_workspace(
        project_id, {"sprite_handle": name, "billing_state": "running", "last_active_at": _now_iso()}
    )


async def wake(project_id: str) -> dict:
    """A manual 'resume' action for the UI (routers/workspace.py) — forces the
    wake-from-hibernation to happen now rather than waiting for whatever tool
    call happens to run first. Sprites wake automatically on any request
    (including the exec calls below), so this is a convenience, not something
    exec_in_workspace() itself needs to call first — see the module
    docstring."""
    workspace = await ensure_workspace(project_id)
    async with _new_client() as client:
        await client.sprite(workspace["sprite_handle"]).run("true", capture_output=True, timeout=20)
    return await projects_repo.update_workspace(
        project_id, {"billing_state": "running", "last_active_at": _now_iso()}
    )


async def sleep(project_id: str) -> dict:
    """No manual pause endpoint exists on Sprites (see module docstring) — this
    can no longer command a stop the way it did against Fly Machines. Kept as
    a function since nothing calls it today but §23.1 anticipated an idle
    reaper eventually using it; for now it just refreshes billing_state from
    the Sprite's own reported status rather than pretending to force one."""
    workspace = await projects_repo.get_workspace(project_id)
    if workspace is None or workspace["sprite_handle"].startswith("pending-"):
        return workspace
    async with _new_client() as client:
        try:
            sprite = await client.get_sprite(workspace["sprite_handle"])
            reported_status = sprite.status
        except Exception:  # noqa: BLE001 — a failed status check shouldn't crash the caller
            return workspace

    # project_workspaces.billing_state has a DB check constraint limiting it to
    # exactly 'running'/'warm'/'cold' (db/migrations/0004_projects.sql) — see
    # the module docstring's ROUGH EDGE note on why this doesn't write
    # reported_status through unvalidated.
    billing_state = reported_status if reported_status in ("running", "warm", "cold") else "running"
    return await projects_repo.update_workspace(project_id, {"billing_state": billing_state})


async def exec_in_workspace(
    project_id: str, argv: list[str], timeout: int = 60, cwd: str | None = None
) -> ExecResult:
    """The one primitive file_tools.py/shell_tools.py/checkpoints.py/git_sync.py
    are all built on. `cwd` defaults to None (Sprites' own default working
    directory, /home/sprite) rather than REPO_ROOT — callers that need REPO_ROOT
    pass it explicitly (most already do, via workspace_paths.REPO_ROOT) — same
    contract as the Machines-era version."""
    workspace = await ensure_workspace(project_id)
    async with _new_client() as client:
        sprite = client.sprite(workspace["sprite_handle"])
        try:
            kwargs = {"capture_output": True, "timeout": timeout}
            if cwd is not None:
                kwargs["dir"] = cwd
            result = await sprite.run(*argv, **kwargs)
        except Exception as exc:  # noqa: BLE001 — see module docstring's ROUGH EDGE note
            if "timeout" in type(exc).__name__.lower() or "timeout" in str(exc).lower():
                return ExecResult(exit_code=-1, stdout="", stderr="Command timed out.", timed_out=True)
            raise WorkspaceExecError(f"exec failed on {workspace['sprite_handle']}: {exc}") from exc

    return ExecResult(
        exit_code=result.returncode,
        stdout=result.stdout.decode(errors="replace"),
        stderr=result.stderr.decode(errors="replace"),
    )
