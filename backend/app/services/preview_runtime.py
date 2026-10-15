"""
§23.7 — Preview compute on Fly.io Sprites: everything between "the app was built"
and "a request reaches it", except the HTTP proxy itself (preview_proxy.py).

The decisions that shape this module, each forced by how Sprites actually behave
(docs.sprites.dev/working-with-sprites — read before changing any of them):

  1. The app runs as a Sprite SERVICE, not a detached `nohup` process. A Sprite's
     RAM doesn't persist across hibernation: every process stops ~30s after the
     last activity and only the disk survives. A `nohup`ed app is therefore dead
     by the time a person opens the preview. A service is restarted by the
     platform whenever the Sprite wakes, and can declare an `http_port` that the
     Sprite's URL routes to — so "first request wakes the Sprite, the Sprite wakes
     the service, the service answers" works with no keep-alive and no idle timer
     built by us.

  2. Only the *entry* target gets `http_port`. A Sprite's URL points at one port;
     for a monorepo that's the frontend (see entry_target_name). Other targets
     (a backend) stay reachable inside the Sprite — which is exactly how the
     existing BACKEND_URL=http://127.0.0.1:<port> injection already works.

  3. Preview secrets reach the app ONLY through the service's `env`. Never in a
     command line (visible in `ps`), never written to a file by this harness, never
     in any text the model sees. See secret_redaction.py and
     docs/PHASE5_3_5_4_NOTES.md for the honest boundary of "the agent cannot read
     these."

  4. Nothing here builds a keep-alive. Billing (running → warm → cold) is the
     platform's idle detection; the only job on our side is to not hold connections
     open (preview_proxy.py) and not poll the Sprite's *URL* (status uses the
     Sprites metadata API, which neither wakes it nor counts as traffic).

The script builders and the probe parser are pure on purpose: backend/tests runs
the generated wrapper in a real local bash, the way test_deploy_pipeline.py has
since 5.1, because a script that's only ever read is a script that's never been run.
"""
import re
import secrets as _secrets
import time

from app.config import get_settings
from app.repositories import deploy_runs as deploy_runs_repo
from app.repositories import projects as projects_repo
from app.services import preview_rules, workspace_service
from app.services.guard_rules import truncate_output
from app.services.workspace_paths import REPO_ROOT, resolve_repo_path

START_PROBE_TIMEOUT_SECONDS = 30
DEFAULT_PROBE_SECONDS = 5

_UPSTREAM_TTL_SECONDS = 300.0
_BILLING_TTL_SECONDS = 10.0
_upstream_cache: dict[str, tuple[float, str]] = {}
_billing_cache: dict[str, tuple[float, str | None]] = {}


class PreviewUnavailable(Exception):
    """A plain-language reason the preview can't be served right now. The message
    is meant to be shown to the person."""


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def slot_slug(target_name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", target_name.strip()) or "app"


def service_name(target_name: str) -> str:
    return f"qh-app-{slot_slug(target_name)}"[:60]


def slot_paths(slug: str) -> tuple[str, str, str]:
    return (f"/tmp/qh-deploy-{slug}.pid", f"/tmp/qh-deploy-{slug}.exit", f"/tmp/qh-deploy-{slug}.log")


def build_service_wrapper(run_cmd: str, slug: str) -> str:
    """What the Sprite service actually runs (`bash -c <this>`). It records its own
    pid, appends everything the app prints to a log the harness owns (so crash
    output survives a platform restart instead of being truncated by it), runs the
    app, then records the app's real exit status. The harness — not the platform's
    service log — owns the log because the platform's restart-on-crash would
    otherwise be free to roll it over before the probe reads it."""
    pid_path, exit_path, log_path = slot_paths(slug)
    return (
        f"exec >> {log_path} 2>&1; "
        f"echo $$ > {pid_path}; "
        f"bash -c {shell_quote(run_cmd)}; "
        f"code=$?; echo $code > {exit_path}; exit $code"
    )


def build_reset_script(slug: str) -> str:
    """Run before (re)creating the service. stop_service has normally already
    ended the previous process; this is the backstop for one it didn't reach — and
    for an app left running by the pre-5.3 `nohup` launcher, which still holds the
    port after an upgrade. Kills the pid's group, its children, then the pid."""
    pid_path, exit_path, log_path = slot_paths(slug)
    return (
        f"if [ -f {pid_path} ]; then "
        f"P=$(cat {pid_path}); "
        f"kill -- -$P 2>/dev/null; pkill -P $P 2>/dev/null; kill $P 2>/dev/null; sleep 1; "
        f"fi; "
        f"rm -f {pid_path} {exit_path}; : > {log_path}; true"
    )


def build_probe_script(slug: str, probe_seconds: int) -> str:
    """Same health signal as 5.1 (module docstring of deploy_pipeline.py): "still
    alive after a short window," not an HTTP check — many apps don't serve 200 on
    `/`. The exit file is checked BEFORE `kill -0`, because an exited-but-unreaped
    process answers `kill -0` and a crashed app looked healthy when this was first
    run in a real shell."""
    pid_path, exit_path, log_path = slot_paths(slug)
    return (
        f"sleep {int(probe_seconds)}; "
        f"if [ -f {exit_path} ]; then "
        f'  echo "QH_EXIT_CODE:$(cat {exit_path})"; '
        f"elif [ -f {pid_path} ] && kill -0 $(cat {pid_path}) 2>/dev/null; then "
        f'  echo "QH_STILL_RUNNING"; '
        f"else "
        f'  echo "QH_EXIT_CODE:"; '
        f"fi; "
        f"echo '---QH_LOG---'; tail -n 400 {log_path} 2>/dev/null"
    )


def parse_probe_output(stdout: str) -> tuple[bool, str, int | None]:
    """(still_running, log_tail, exit_code)."""
    still_running = "QH_STILL_RUNNING" in stdout.splitlines()[:3] if stdout else False
    log_tail = stdout.split("---QH_LOG---", 1)[-1].strip() if "---QH_LOG---" in stdout else stdout
    exit_code = None
    if not still_running:
        for line in stdout.splitlines():
            if line.startswith("QH_EXIT_CODE:"):
                try:
                    exit_code = int(line.split(":", 1)[1])
                except ValueError:
                    exit_code = None
                break
    return still_running, log_tail, exit_code


def order_targets(targets: list[dict]) -> list[dict]:
    """A target literally named "backend" goes first when "frontend" is also
    present, so the frontend's BACKEND_URL injection has a resolved port by the
    time it's that target's turn. Everything else stays as declared."""
    names = {t["name"].strip().lower() for t in targets}
    if "backend" in names and "frontend" in names:
        return sorted(targets, key=lambda t: 0 if t["name"].strip().lower() == "backend" else 1)
    return targets


_ENTRY_PREFERENCE = ("frontend", "web", "client", "ui", "app", "site")
_NOT_ENTRY = ("backend", "api", "server", "worker")


def entry_target_name(targets: list[dict]) -> str | None:
    """Which target the Sprite's URL (and so the preview iframe) points at. A
    Sprite's URL routes to one port, so for a monorepo it has to be a choice:
    a conventionally-named frontend if there is one, else the first target that
    isn't obviously a backend, else the first target."""
    names = [t["name"] for t in targets if t.get("name")]
    if not names:
        return None
    if len(names) == 1:
        return names[0]
    by_lower = {n.strip().lower(): n for n in names}
    for preferred in _ENTRY_PREFERENCE:
        if preferred in by_lower:
            return by_lower[preferred]
    candidates = [n for n in names if n.strip().lower() not in _NOT_ENTRY]
    return (candidates or names)[0]


def build_target_env(port: int | None, extra_env: dict[str, str], secret_env: dict[str, str]) -> dict[str, str]:
    """The environment a service starts with: the person's preview secrets, then
    the harness-managed variables (PORT, BACKEND_URL) on top — so a secret that
    happens to share a name can never redirect the app off the port the proxy
    routes to. (The Secrets panel also rejects those names up front.)"""
    managed = {**({"PORT": str(port)} if port else {}), **extra_env}
    return {**secret_env, **managed}


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------


async def launch_and_probe(
    project_id: str,
    target_dir: str,
    run_cmd: str,
    env: dict[str, str],
    target_name: str,
    *,
    http_port: int | None = None,
    probe_seconds: int = DEFAULT_PROBE_SECONDS,
) -> tuple[bool, str, str, int | None]:
    """Starts `run_cmd` as a Sprite service and judges it by the probe. Returns
    (started, log_tail, stderr, exit_code) — the shape deploy_pipeline already
    consumed from the 5.1 launcher. On a failed start the service is stopped so a
    crash loop doesn't keep burning compute after the deploy has already failed."""
    slug = slot_slug(target_name)
    name = service_name(target_name)

    await workspace_service.stop_service(project_id, name)
    await workspace_service.exec_in_workspace(
        project_id, ["bash", "-c", build_reset_script(slug)], timeout=20, cwd=REPO_ROOT
    )
    try:
        await workspace_service.create_or_replace_service(
            project_id,
            name,
            cmd="bash",
            args=["-c", build_service_wrapper(run_cmd, slug)],
            cwd=target_dir,
            env=env,
            http_port=http_port,
        )
    except workspace_service.SpriteServiceError as exc:
        return False, "", truncate_output(str(exc)), None

    result = await workspace_service.exec_in_workspace(
        project_id,
        ["bash", "-c", build_probe_script(slug, probe_seconds)],
        timeout=START_PROBE_TIMEOUT_SECONDS,
        cwd=REPO_ROOT,
    )
    still_running, log_tail, exit_code = parse_probe_output(result.stdout)
    if not still_running:
        await workspace_service.stop_service(project_id, name)
    return still_running, truncate_output(log_tail), truncate_output(result.stderr), exit_code


async def restart_all(project: dict) -> list[dict]:
    """Re-issues every target's service from its last-resolved plan and the CURRENT
    preview secrets — no rebuild (the build output is on the Sprite's disk, which
    is the whole point of a persistent disk). This is how a change in the Secrets
    panel takes effect. Returns one result per target."""
    targets = [t for t in (project.get("deploy_targets") or []) if t.get("run_cmd")]
    if not targets:
        raise PreviewUnavailable("Nothing has been deployed yet — deploy the project first.")

    all_targets = project.get("deploy_targets") or []
    entry = entry_target_name(all_targets)
    secret_env = await _runtime_env(project["id"])
    resolved_ports: dict[str, int] = {}
    results: list[dict] = []

    for target in order_targets(targets):
        extra: dict[str, str] = {}
        if target["name"].strip().lower() == "frontend" and "backend" in resolved_ports:
            extra["BACKEND_URL"] = f"http://127.0.0.1:{resolved_ports['backend']}"
        port = target.get("port")
        started, log, stderr, exit_code = await launch_and_probe(
            project["id"],
            resolve_repo_path(target["root"]),
            target["run_cmd"],
            build_target_env(port, extra, secret_env),
            target["name"],
            http_port=port if (target["name"] == entry and port) else None,
        )
        if started and port:
            resolved_ports[target["name"].strip().lower()] = port
        results.append({"target": target["name"], "started": started, "exit_code": exit_code, "log": log, "stderr": stderr})
    return results


async def _runtime_env(project_id: str) -> dict[str, str]:
    from app.services import preview_secrets_service  # local: keeps this module importable without the repo layer in pure tests

    return await preview_secrets_service.get_runtime_env(project_id)


# ---------------------------------------------------------------------------
# The Sprite's own URL (for the proxy and, later, the agent's browser tools)
# ---------------------------------------------------------------------------


async def get_upstream_origin(project_id: str, *, use_cache: bool = True) -> str:
    """The Sprite's validated `https://<host>` origin. Only the harness backend ever
    sees this — it is never returned by any API (§23.7: "never exposed directly").
    The agent's own browser tools (Phase 5.8) call THIS for the internal URL; the
    person's iframe goes through preview_proxy.

    Refuses to hand out an origin whose URL was made public: a Sprite URL is
    bearer-gated by default and the proxy is the only intended way in. If something
    flipped it to public, serving through the proxy would hide a real exposure."""
    now = time.monotonic()
    hit = _upstream_cache.get(project_id)
    if use_cache and hit is not None and hit[0] > now:
        return hit[1]
    try:
        info = await workspace_service.get_sprite_info(project_id)
    except workspace_service.SpriteServiceError as exc:
        raise PreviewUnavailable("The preview workspace couldn't be reached right now.") from exc
    if info is None or not info.url:
        raise PreviewUnavailable("This project's workspace hasn't been created yet — deploy it first.")
    if info.url_auth == "public":
        raise PreviewUnavailable(
            "This workspace's URL is set to public, which the preview refuses to serve through. "
            "Set its URL authentication back to the default (sprite) and try again."
        )
    try:
        origin = preview_rules.validate_upstream_origin(info.url, get_settings().sprites_url_host_suffix)
    except ValueError as exc:
        raise PreviewUnavailable("The workspace reported a URL the preview won't send credentials to.") from exc
    _upstream_cache[project_id] = (now + _UPSTREAM_TTL_SECONDS, origin)
    return origin


def sprites_auth_headers() -> dict[str, str]:
    """The ONLY place the Sprites token is turned into a header. Used by the proxy
    when it forwards a request. Must never be returned over HTTP or logged."""
    return {"Authorization": f"Bearer {get_settings().sprites_api_token}"}


def forget_upstream(project_id: str) -> None:
    _upstream_cache.pop(project_id, None)


# ---------------------------------------------------------------------------
# Subdomain + status
# ---------------------------------------------------------------------------


async def ensure_preview_subdomain(project: dict) -> str:
    """Normally assigned at project creation (routers/projects.py) and backfilled by
    0011_preview.sql — this is the lazy backstop. Assigned once; the DB trigger
    guarantees it's never changed after that."""
    existing = project.get("preview_subdomain")
    if existing:
        return existing
    for _ in range(5):
        candidate = preview_rules.new_subdomain(project["name"], _secrets.token_hex(8))
        try:
            row = await projects_repo.set_preview_subdomain_if_unset(project["id"], candidate)
        except Exception:  # noqa: BLE001 — a unique-index collision: just try another suffix
            row = None
        if row and row.get("preview_subdomain"):
            return row["preview_subdomain"]
        fresh = await projects_repo.get_by_id(project["id"])
        if fresh and fresh.get("preview_subdomain"):
            return fresh["preview_subdomain"]
    raise PreviewUnavailable("Couldn't allocate a preview address — try again.")


def preview_origin_for(subdomain: str | None) -> str | None:
    settings = get_settings()
    if not subdomain or not settings.preview_enabled:
        return None
    return preview_rules.public_origin(subdomain, settings.preview_base_domain, settings.preview_scheme)


async def _billing_state(project_id: str) -> str | None:
    now = time.monotonic()
    hit = _billing_cache.get(project_id)
    if hit is not None and hit[0] > now:
        return hit[1]
    workspace = await workspace_service.refresh_billing_state(project_id)
    state = workspace["billing_state"] if workspace else None
    _billing_cache[project_id] = (now + _BILLING_TTL_SECONDS, state)
    return state


async def get_status(project: dict) -> dict:
    settings = get_settings()
    targets = project.get("deploy_targets") or []
    latest = await deploy_runs_repo.get_latest_for_project(project["id"])
    deployed = bool(latest) and latest.get("status") == "success"
    configured = settings.preview_enabled
    subdomain = project.get("preview_subdomain") or (await ensure_preview_subdomain(project) if configured else None)

    reason = None
    if not configured:
        reason = (
            "Live Preview isn't set up on this server yet. The server needs PREVIEW_BASE_DOMAIN and "
            "PREVIEW_SIGNING_SECRET (see docs/YOUR_SETUP_CHECKLIST.md)."
        )
    elif not deployed:
        reason = "Deploy the project first — there's nothing running to preview yet."

    try:
        billing_state = await _billing_state(project["id"])
    except Exception:  # noqa: BLE001 — a status read must never take the page down
        billing_state = None

    return {
        "configured": configured,
        "can_open": configured and deployed,
        "unavailable_reason": reason,
        "subdomain": subdomain,
        "origin": preview_origin_for(subdomain),
        "billing_state": billing_state,
        "entry_target": entry_target_name(targets),
        "deployed": deployed,
    }
