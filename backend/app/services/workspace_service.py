"""
§23: the Workspace Service. Implementation order step 5 — "stood up and tested in
isolation... before wiring any agent tool to it." This module is that foundation;
app/services/file_tools.py, shell_tools.py, checkpoints.py, and git_sync.py are all
built on top of exec_in_workspace() below and never talk to Fly directly themselves.

Backed by Fly.io Machines API (https://api.machines.dev/v1) — one Fly App and one
persistent Volume per Quan Harness project, holding exactly one Machine that's
started when work is happening and stopped (never billed) otherwise (§23.1: "the
underlying Sprite must be fully off, and unbilled, when nobody's looking at it").
"Sprite" in the rest of this codebase (project_workspaces.sprite_handle, per
0004_projects.sql) refers to this Machine — Quan Harness's own name for it, never
exposed to Fly or in any user-facing surface, per NOTICES.md's naming section.

ROUGH EDGE, flagged the same way Phase 1 flagged its OAuth rough edges (see
/docs/YOUR_SETUP_CHECKLIST.md): the exec endpoint's exact response shape
(`/v1/apps/{app}/machines/{id}/exec`) is not in Fly's indexed Machines Resource API
reference as of this writing — it's documented piecemeal (the `fly machine exec`
flyctl command, and third-party examples posting `{"cmd": ...}` to this path). The
request/response parsing below is written defensively (accepts a couple of
plausible field-name variants) specifically because of that gap. Verify against a
real Fly account before relying on this in production — see the checklist.

No credential of any kind lives in this module's own request path except the Fly
API token itself (organization-level infrastructure credential, not a per-project
or per-user secret) — GitHub tokens are handled entirely by git_sync.py, which
calls exec_in_workspace() the same as everything else but is the only caller that
ever passes a credential through to a command it builds (§23.2's table).
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.config import get_settings
from app.repositories import projects as projects_repo
from app.services.workspace_paths import REPO_ROOT, VOLUME_MOUNT_PATH, VOLUME_NAME, resolve_repo_path

# Fly app names are a *global* namespace across every Fly customer, not scoped to
# our org — collision with someone else's app is astronomically unlikely given a
# uuid4 project_id, but not impossible in principle. If ensure_app() ever starts
# failing with a name-conflict-shaped error for a *new* project, that's the first
# thing to check.
_APP_PREFIX = "qh-ws-"


def _app_name(project_id: str) -> str:
    return f"{_APP_PREFIX}{project_id}"


def _sanitize_machine_name(project_id: str) -> str:
    return f"workspace-{project_id}"[:63]


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


class WorkspaceProvisionError(RuntimeError):
    pass


class WorkspaceExecError(RuntimeError):
    pass


def _headers() -> dict:
    settings = get_settings()
    return {"Authorization": f"Bearer {settings.fly_api_token}", "Content-Type": "application/json"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _FlyClient:
    """Thin wrapper over the handful of Machines API calls this system needs.
    Deliberately not a general-purpose Fly SDK — see module docstring."""

    def __init__(self):
        self._settings = get_settings()

    @property
    def _base(self) -> str:
        return self._settings.fly_api_base.rstrip("/")

    async def ensure_app(self, app_name: str) -> None:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{self._base}/apps",
                headers=_headers(),
                json={"app_name": app_name, "org_slug": self._settings.fly_org_slug},
            )
            # Idempotent by design: a 4xx whose body suggests "already exists" is a
            # success from this caller's point of view — ensure_app() is called on
            # every ensure_workspace(), not just the first.
            if resp.status_code >= 400 and "exist" not in resp.text.lower() and "taken" not in resp.text.lower():
                raise WorkspaceProvisionError(f"Fly app create failed: {resp.status_code} {resp.text}")

    async def create_volume(self, app_name: str, region: str, size_gb: int) -> str:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base}/apps/{app_name}/volumes",
                headers=_headers(),
                json={"name": VOLUME_NAME, "region": region, "size_gb": size_gb},
            )
            if resp.status_code >= 400:
                raise WorkspaceProvisionError(f"Fly volume create failed: {resp.status_code} {resp.text}")
            return resp.json()["id"]

    async def list_volumes(self, app_name: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(f"{self._base}/apps/{app_name}/volumes", headers=_headers())
            if resp.status_code >= 400:
                return []
            return resp.json()

    async def create_machine(self, app_name: str, name: str, region: str, volume_id: str) -> dict:
        settings = self._settings
        config = {
            "image": settings.workspace_image,
            "guest": {
                "cpu_kind": settings.workspace_guest_cpu_kind,
                "cpus": settings.workspace_guest_cpus,
                "memory_mb": settings.workspace_guest_memory_mb,
            },
            "mounts": [{"volume": volume_id, "path": VOLUME_MOUNT_PATH}],
            # Keeps the machine alive indefinitely once started so exec() has a
            # process tree to run commands against — the actual work happens via
            # the exec endpoint below, never via this init command.
            "init": {"exec": ["/bin/sleep", "infinity"]},
            "restart": {"policy": "no"},
            "auto_destroy": False,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base}/apps/{app_name}/machines",
                headers=_headers(),
                json={"name": name, "region": region, "config": config},
            )
            if resp.status_code >= 400:
                raise WorkspaceProvisionError(f"Fly machine create failed: {resp.status_code} {resp.text}")
            return resp.json()

    async def get_machine(self, app_name: str, machine_id: str) -> dict | None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{self._base}/apps/{app_name}/machines/{machine_id}", headers=_headers())
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

    async def start_machine(self, app_name: str, machine_id: str) -> None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base}/apps/{app_name}/machines/{machine_id}/start", headers=_headers()
            )
            if resp.status_code >= 400:
                raise WorkspaceProvisionError(f"Fly machine start failed: {resp.status_code} {resp.text}")

    async def stop_machine(self, app_name: str, machine_id: str) -> None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base}/apps/{app_name}/machines/{machine_id}/stop", headers=_headers(), json={}
            )
            if resp.status_code >= 400:
                raise WorkspaceProvisionError(f"Fly machine stop failed: {resp.status_code} {resp.text}")

    async def wait_for_state(self, app_name: str, machine_id: str, state: str, timeout: int = 60) -> None:
        async with httpx.AsyncClient(timeout=timeout + 10.0) as client:
            resp = await client.get(
                f"{self._base}/apps/{app_name}/machines/{machine_id}/wait",
                headers=_headers(),
                params={"state": state, "timeout": timeout},
            )
            if resp.status_code >= 400:
                raise WorkspaceProvisionError(
                    f"Machine did not reach state={state} within {timeout}s: {resp.status_code} {resp.text}"
                )

    async def exec(self, app_name: str, machine_id: str, argv: list[str], timeout: int) -> ExecResult:
        async with httpx.AsyncClient(timeout=timeout + 15.0) as client:
            try:
                resp = await client.post(
                    f"{self._base}/apps/{app_name}/machines/{machine_id}/exec",
                    headers=_headers(),
                    json={"cmd": argv, "timeout": timeout},
                )
            except httpx.TimeoutException:
                return ExecResult(exit_code=-1, stdout="", stderr="Command timed out.", timed_out=True)
            if resp.status_code >= 400:
                raise WorkspaceExecError(f"exec failed: {resp.status_code} {resp.text}")
            body = resp.json()
            # Defensive field-name handling — see module docstring's rough-edge note.
            exit_code = body.get("exit_code", body.get("exitcode", body.get("returncode", 0)))
            stdout = body.get("stdout", "")
            stderr = body.get("stderr", "")
            return ExecResult(exit_code=int(exit_code), stdout=stdout, stderr=stderr)


_fly = _FlyClient()


async def ensure_workspace(project_id: str) -> dict:
    """§14.6: 'provisioned once, the first time it's needed... persists across
    sessions.' Idempotent — safe to call at the start of every operation that
    needs a live workspace; a project whose Machine already exists just gets
    looked up and woken if needed, never re-created.

    Returns the project_workspaces row, updated with the real Fly identifiers in
    place of Phase 1's `pending-*` placeholder handle.
    """
    settings = get_settings()
    workspace = await projects_repo.get_workspace(project_id)
    if workspace is None:
        raise WorkspaceProvisionError(f"No project_workspaces row for project {project_id} — was it created?")

    app_name = _app_name(project_id)

    if workspace["sprite_handle"].startswith("pending-"):
        await _fly.ensure_app(app_name)
        volumes = await _fly.list_volumes(app_name)
        volume_id = volumes[0]["id"] if volumes else await _fly.create_volume(
            app_name, settings.fly_region, settings.workspace_volume_size_gb
        )
        machine = await _fly.create_machine(
            app_name, _sanitize_machine_name(project_id), settings.fly_region, volume_id
        )
        machine_id = machine["id"]
        await _fly.wait_for_state(app_name, machine_id, "started", timeout=60)

        # workspace_image (config.py) is deliberately a trivial, always-available
        # base — nothing project-specific baked in. That means git/python3 (both
        # load-bearing: checkpoints need git, file_tools' writes need python3)
        # aren't guaranteed present. One-time bootstrap, best-effort: failures
        # here surface on the *next* real command against this workspace rather
        # than blocking provisioning, since a already-present toolchain (a
        # custom image someone points workspace_image at) makes this a fast
        # no-op, not a hard dependency on apt succeeding.
        await _fly.exec(
            app_name,
            machine_id,
            [
                "bash", "-c",
                "command -v git >/dev/null && command -v python3 >/dev/null || "
                "(apt-get update -qq && apt-get install -y -qq git python3 python3-pip >/dev/null)",
            ],
            timeout=120,
        )
        await _fly.exec(app_name, machine_id, ["mkdir", "-p", REPO_ROOT], timeout=30)
        await _fly.exec(app_name, machine_id, ["git", "init", REPO_ROOT], timeout=30)
        workspace = await projects_repo.update_workspace(
            project_id,
            {
                "sprite_handle": machine_id,
                "billing_state": "running",
                "last_active_at": _now_iso(),
            },
        )
    return workspace


async def wake(project_id: str) -> dict:
    """Starts a stopped workspace and waits for it to be ready. A no-op (fast) if
    already running. Not itself a tool the model can call (§14.6) — this is
    called internally by exec_in_workspace() whenever a cold workspace is needed."""
    workspace = await ensure_workspace(project_id)
    app_name = _app_name(project_id)
    machine_id = workspace["sprite_handle"]

    machine = await _fly.get_machine(app_name, machine_id)
    if machine is not None and machine.get("state") == "started":
        return workspace

    await projects_repo.update_workspace(project_id, {"billing_state": "warm"})
    await _fly.start_machine(app_name, machine_id)
    await _fly.wait_for_state(app_name, machine_id, "started", timeout=60)
    return await projects_repo.update_workspace(
        project_id, {"billing_state": "running", "last_active_at": _now_iso()}
    )


async def sleep(project_id: str) -> dict:
    """§23.1: 'The underlying Sprite must be fully off, and unbilled, when nobody's
    looking at it.' A stopped Machine (not merely suspended) is Fly's actual
    unbilled-compute state — the persistent Volume (and everything on it) is
    untouched either way, which is the whole point of the volume/machine split."""
    workspace = await projects_repo.get_workspace(project_id)
    if workspace is None or workspace["sprite_handle"].startswith("pending-"):
        return workspace  # nothing provisioned yet — nothing to stop
    app_name = _app_name(project_id)
    await _fly.stop_machine(app_name, workspace["sprite_handle"])
    return await projects_repo.update_workspace(project_id, {"billing_state": "cold"})


async def exec_in_workspace(
    project_id: str, argv: list[str], timeout: int = 120, cwd: str | None = None
) -> ExecResult:
    """The one primitive every other Phase 2 tool (file_tools, shell_tools,
    checkpoints, git_sync) is built on. Wakes a cold workspace automatically —
    from the caller's point of view, a workspace is just always available."""
    workspace = await wake(project_id)
    app_name = _app_name(project_id)
    command = argv if cwd is None else ["sh", "-c", f"cd {_shell_quote(cwd)} && exec \"$0\" \"$@\"", *argv]
    result = await _fly.exec(app_name, workspace["sprite_handle"], command, timeout=timeout)
    await projects_repo.update_workspace(project_id, {"last_active_at": _now_iso()})
    return result


def _shell_quote(path: str) -> str:
    """Minimal POSIX single-quote escaping — used only for the fixed `cd` prefix
    above, never to build a caller-supplied shell string (execute_bash's own
    command text is passed to `bash -c` as a single argv element, never
    concatenated into a larger shell string — see shell_tools.py)."""
    return "'" + path.replace("'", "'\\''") + "'"


def new_workspace_stub_handle() -> str:
    """Used by projects.py at project-creation time (Phase 1 behavior, unchanged)
    — a placeholder until ensure_workspace() does the real provisioning above."""
    return f"pending-{uuid.uuid4().hex[:12]}"
