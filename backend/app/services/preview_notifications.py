"""
I/O shell around preview_limitations.py (pure) and repositories/notifications.py —
§23.8's notification system, and the other half of §23.9 point 4 ("environment, not
code → routes to the notification system"), which Phase 5.5 left open because
nothing existed to route to.

Everything here is NOTIFY-ONLY. It writes rows that the person reads; it never
touches their CORS config, OAuth provider, database, or secrets, and nothing it
creates is acted on automatically. The only way any of the "fixes" happens is the
person doing it (adding a secret in the panel, editing their backend's allow-list).
"""
import logging

from app.config import get_settings
from app.repositories import notifications as notifications_repo
from app.repositories import preview_secrets as preview_secrets_repo
from app.repositories import projects as projects_repo
from app.services import preview_limitations as pl
from app.services import preview_runtime

logger = logging.getLogger(__name__)


async def context_for(project_id: str, project: dict | None = None, missing: list[str] | None = None) -> pl.GuidanceContext:
    project = project or await projects_repo.get_by_id(project_id) or {}
    return pl.GuidanceContext(
        origin=preview_runtime.preview_origin_for(project.get("preview_subdomain")),
        egress_ips=get_settings().preview_egress_ip_list,
        missing_names=missing or [],
    )


async def raise_environment_failure(project_id: str, kind: str, diagnosis_text: str | None, run_id: str | None) -> None:
    """A deploy failed for a reason that isn't a bug in the app's code (§23.9 point
    4) — tell the person which §23.8 limitation it looks like. Never raises: a
    notification problem must not turn into a deploy problem."""
    try:
        ctx = await context_for(project_id)
        note = pl.build_notification(kind if kind in pl.KINDS else "other", ctx, diagnosis_text)
        await notifications_repo.raise_or_update(
            project_id, kind=note["kind"], source="deploy_failure", title=note["title"], body=note["body"],
            detail_key=note["detail_key"], detail={}, deploy_run_id=run_id,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Could not raise a preview notification for project %s", project_id)


async def scan_missing_env(project_id: str, env_example_text: str | None, run_id: str | None) -> list[str]:
    """§23.8's secrets row, caught BEFORE the app fails: the repo ships a
    .env.example naming variables the preview hasn't been given. Compares names only
    (values from the example file are discarded at parse time). Non-blocking by
    design — plenty of variables in an example file have defaults, so this informs
    and the deploy proceeds. Returns the missing names."""
    try:
        names = pl.parse_env_example_names(env_example_text)
        configured = await preview_secrets_repo.list_names(project_id)
        missing = pl.missing_secret_names(names, configured)
        if not missing:
            await notifications_repo.resolve_open(project_id, kinds=["secrets"], source="env_scan")
            return []
        ctx = await context_for(project_id, missing=missing)
        note = pl.build_notification("secrets", ctx)
        await notifications_repo.raise_or_update(
            project_id, kind="secrets", source="env_scan", title=note["title"], body=note["body"],
            detail_key=note["detail_key"], detail={"missing": missing[:50]}, deploy_run_id=run_id,
        )
        return missing
    except Exception:  # noqa: BLE001
        logger.exception("Could not check .env.example for project %s", project_id)
        return []


async def resolve_after_success(project_id: str) -> None:
    """A deploy that worked closes the notifications a *failed* deploy raised. It
    deliberately leaves env-scan and manual ones alone: a CORS/OAuth problem only
    shows up in the browser at runtime, so a green deploy says nothing about it."""
    try:
        await notifications_repo.resolve_open(project_id, source="deploy_failure")
    except Exception:  # noqa: BLE001
        logger.exception("Could not resolve preview notifications for project %s", project_id)


async def guidance_for_project(project: dict) -> dict:
    ctx = await context_for(project["id"], project)
    return {
        "origin": ctx.origin,
        "egress_ips": ctx.egress_ips,
        "guidance": pl.all_guidance(ctx),
    }


async def reconcile_secrets(project_id: str) -> None:
    """After the Secrets panel changes: if an open "missing secrets" notification
    named variables that are now all set, close it — otherwise the panel would keep
    saying "missing STRIPE_KEY" right after the person added STRIPE_KEY. Closes it
    only when EVERYTHING it named is set; a partial fix leaves it open (the next
    deploy re-scans and shrinks the list)."""
    try:
        open_note = await notifications_repo.get_open(project_id, "secrets")
        if open_note is None:
            return
        named = (open_note.get("detail") or {}).get("missing") or []
        if not named:
            return  # a deploy-failure "secrets" notification: only a later successful deploy closes it
        configured = set(await preview_secrets_repo.list_names(project_id))
        if all(name in configured for name in named):
            await notifications_repo.resolve_open(project_id, kinds=["secrets"])
    except Exception:  # noqa: BLE001
        logger.exception("Could not reconcile secrets notification for project %s", project_id)
