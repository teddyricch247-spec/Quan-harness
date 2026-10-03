"""
§23.7 / §23.8's user-facing HTTP surface — Live Preview sessions, the preview-only
Secrets panel, and the known-limitations notifications. Strictly user-triggered, same
as routers/deploy.py and Push/Pull: no agent tool reaches any of this, and nothing
here changes anything on the person's own systems (§23.8: "notify-only and opt-in").

What this router never returns, anywhere: a secret's value, the Sprite's own URL, or
the Sprites API token.
"""
from fastapi import APIRouter, Depends, HTTPException, status

from app.config import get_settings
from app.core.security import AuthedUser
from app.dependencies import verified_user
from app.models.schemas import (
    GuidanceOut,
    PreviewLimitationsOut,
    PreviewNotificationOut,
    PreviewRestartOut,
    PreviewRestartTargetResult,
    PreviewSecretOut,
    PreviewSecretUpsert,
    PreviewSessionOut,
    PreviewStatusOut,
)
from app.repositories import audit
from app.repositories import notifications as notifications_repo
from app.repositories import preview_secrets as preview_secrets_repo
from app.repositories import projects as projects_repo
from app.services import (
    deploy_pipeline,
    preview_limitations,
    preview_notifications,
    preview_rules,
    preview_runtime,
    preview_secrets_service,
    preview_tokens,
    vault,
)

router = APIRouter(prefix="/projects", tags=["preview"])

# Show the last four characters only when that's a small fraction of the value.
_HINT_MIN_LENGTH = 12


async def _require_project(user: AuthedUser, project_id: str) -> dict:
    project = await projects_repo.get_for_user(user.user_id, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


def _hint(value: str | None) -> str | None:
    return value[-4:] if value and len(value) >= _HINT_MIN_LENGTH else None


# ---------------------------------------------------------------------------
# Preview status / session / restart
# ---------------------------------------------------------------------------


@router.get("/{project_id}/preview", response_model=PreviewStatusOut)
async def get_preview_status(project_id: str, user: AuthedUser = Depends(verified_user)):
    project = await _require_project(user, project_id)
    return PreviewStatusOut(**await preview_runtime.get_status(project))


@router.post("/{project_id}/preview/session", response_model=PreviewSessionOut)
async def create_preview_session(project_id: str, user: AuthedUser = Depends(verified_user)):
    """Mints the single-use URL the iframe loads. This is what makes the preview
    "never a shareable link" (§23.1): the URL is dead after one use and a minute, the
    session it sets is bound to this project and this subdomain, and only the signed-in
    owner of the project can get one."""
    project = await _require_project(user, project_id)
    settings = get_settings()
    status_info = await preview_runtime.get_status(project)
    if not status_info["can_open"]:
        raise HTTPException(status_code=409, detail=status_info["unavailable_reason"] or "The preview isn't available.")
    token = preview_tokens.mint_enter_token(
        settings.preview_signing_secret, project_id, status_info["subdomain"],
        settings.preview_enter_token_ttl_seconds, user_id=user.user_id,
    )
    await audit.record(user.user_id, "preview", "open_session", True, project_id=project_id)
    return PreviewSessionOut(
        url=f"{status_info['origin']}{preview_rules.ENTER_PATH}?t={token}",
        expires_in_seconds=settings.preview_enter_token_ttl_seconds,
    )


@router.post("/{project_id}/preview/restart", response_model=PreviewRestartOut)
async def restart_preview(project_id: str, user: AuthedUser = Depends(verified_user)):
    """Re-issues the app's service(s) with the CURRENT preview secrets, without
    rebuilding. This is how a change in the Secrets panel takes effect (§23.8:
    nothing is applied automatically — the person asks)."""
    project = await _require_project(user, project_id)
    if deploy_pipeline.is_running(project_id):
        raise HTTPException(status_code=409, detail="A deploy is running — wait for it to finish.")
    try:
        results = await preview_runtime.restart_all(project)
    except preview_runtime.PreviewUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    ok = all(r["started"] for r in results)
    await audit.record(user.user_id, "preview", "restart", ok, project_id=project_id)
    return PreviewRestartOut(
        results=[
            PreviewRestartTargetResult(
                target=r["target"], started=r["started"], exit_code=r["exit_code"],
                # Redacted: a start log can echo the environment of a crashing app.
                log=await _safe_log(project_id, r["log"]),
            )
            for r in results
        ]
    )


async def _safe_log(project_id: str, log: str) -> str:
    return (await preview_secrets_service.redact_text(project_id, log)) or ""


# ---------------------------------------------------------------------------
# Preview secrets (§23.8) — preview-only, never visible to the agent
# ---------------------------------------------------------------------------


@router.get("/{project_id}/preview/secrets", response_model=list[PreviewSecretOut])
async def list_preview_secrets(project_id: str, user: AuthedUser = Depends(verified_user)):
    rows = await preview_secrets_repo.list_for_project(user.user_id, project_id)
    if rows is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    out = []
    for row in rows:
        value = await vault.read_secret(row["secret_ref"])
        out.append(PreviewSecretOut(id=row["id"], name=row["name"], value_hint=_hint(value), created_at=row["created_at"], updated_at=row["updated_at"]))
    return out


@router.put("/{project_id}/preview/secrets", response_model=PreviewSecretOut)
async def upsert_preview_secret(project_id: str, body: PreviewSecretUpsert, user: AuthedUser = Depends(verified_user)):
    """Create or replace by name ("one set"). Takes effect on the next deploy or when
    the person restarts the preview — never applied to a running app on its own."""
    error = preview_limitations.validate_secret_name(body.name)
    if error:
        raise HTTPException(status_code=400, detail=error)
    value = preview_limitations.normalize_secret_value(body.value)
    if not value:
        raise HTTPException(status_code=400, detail="The value can't be empty.")
    try:
        result = await preview_secrets_repo.upsert(user.user_id, project_id, body.name, value)
    except preview_secrets_repo.PreviewSecretLimitError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    row, created = result
    preview_secrets_service.invalidate(project_id)  # redaction must know about it immediately
    await preview_notifications.reconcile_secrets(project_id)
    # The audit trail records THAT a secret was set, by name — never its value.
    await audit.record(user.user_id, "preview_secret", "set" if created else "replace", True, project_id=project_id, input_payload={"name": body.name})
    return PreviewSecretOut(
        id=row["id"], name=row["name"], value_hint=_hint(value), created_at=row["created_at"], updated_at=row["updated_at"], created=created
    )


@router.delete("/{project_id}/preview/secrets/{secret_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_preview_secret(project_id: str, secret_id: str, user: AuthedUser = Depends(verified_user)):
    deleted = await preview_secrets_repo.delete_owned(user.user_id, project_id, secret_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Secret not found.")
    preview_secrets_service.invalidate(project_id)
    await audit.record(user.user_id, "preview_secret", "delete", True, project_id=project_id)


# ---------------------------------------------------------------------------
# Known preview limitations (§23.8) — notifications and standing guidance
# ---------------------------------------------------------------------------


@router.get("/{project_id}/preview/notifications", response_model=list[PreviewNotificationOut])
async def list_notifications(project_id: str, user: AuthedUser = Depends(verified_user)):
    project = await _require_project(user, project_id)
    rows = await notifications_repo.list_for_project(user.user_id, project_id)
    out = []
    for row in rows or []:
        ctx = await preview_notifications.context_for(project_id, project, missing=(row.get("detail") or {}).get("missing"))
        out.append(
            PreviewNotificationOut(
                id=row["id"], kind=row["kind"], status=row["status"], source=row["source"], title=row["title"], body=row["body"],
                detail=row.get("detail") or {}, created_at=row["created_at"], updated_at=row["updated_at"],
                guidance=GuidanceOut(**preview_limitations.guidance_for(row["kind"], ctx)),
            )
        )
    return out


@router.post("/{project_id}/preview/notifications/{notification_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_notification(project_id: str, notification_id: str, user: AuthedUser = Depends(verified_user)):
    if not await notifications_repo.dismiss_owned(user.user_id, project_id, notification_id):
        raise HTTPException(status_code=404, detail="Notification not found.")


@router.get("/{project_id}/preview/limitations", response_model=PreviewLimitationsOut)
async def get_limitations(project_id: str, user: AuthedUser = Depends(verified_user)):
    """The standing, always-available version of §23.8's table — so the four known
    limits are explained BEFORE anything breaks, with this project's own stable
    preview origin filled in."""
    project = await _require_project(user, project_id)
    data = await preview_notifications.guidance_for_project(project)
    return PreviewLimitationsOut(origin=data["origin"], egress_ips=data["egress_ips"], guidance=[GuidanceOut(**g) for g in data["guidance"]])
