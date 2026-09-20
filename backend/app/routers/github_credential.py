from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.core.security import AuthedUser
from app.dependencies import verified_user
from app.models.schemas import GithubCredentialManualCreate, GithubCredentialOut, GithubCredentialRotate
from app.repositories import audit, github_credentials as repo
from app.services import github_oauth, oauth_state, vault

router = APIRouter(prefix="/connections/github-credential", tags=["connections"])


def _to_out(row: dict, last_four: str | None) -> GithubCredentialOut:
    return GithubCredentialOut(
        id=row["id"],
        credential_type=row["credential_type"],
        label=row["label"],
        github_app_account_login=row.get("github_app_account_login"),
        is_default=row["is_default"],
        token_last_four=last_four,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("", response_model=list[GithubCredentialOut])
async def list_credentials(user: AuthedUser = Depends(verified_user)):
    rows = await repo.list_for_user(user.user_id)
    out = []
    for row in rows:
        last_four = None
        if row.get("token_ref"):
            secret = await vault.read_secret(row["token_ref"])
            last_four = (secret or "")[-4:] if secret else "----"
        out.append(_to_out(row, last_four))
    return out


@router.post("", response_model=GithubCredentialOut, status_code=status.HTTP_201_CREATED)
async def add_token_manually(body: GithubCredentialManualCreate, user: AuthedUser = Depends(verified_user)):
    """§8: 'Add a token manually' — a fine-grained personal access token, for anyone
    who wants finer control than the OAuth flow gives."""
    login = None
    try:
        login = await github_oauth.fetch_authenticated_login(body.token)
    except Exception:  # noqa: BLE001
        # Don't hard-fail on this — a fine-grained PAT scoped to specific repos can
        # still fail a broad /user call under some GitHub configurations. The token
        # itself gets validated for real the first time Push/Pull actually uses it.
        pass

    token_ref = await vault.create_secret(body.token, name=f"github-pat:{user.user_id}")
    if body.is_default:
        await repo.clear_default_for_user(user.user_id)
    row = await repo.create(
        user.user_id,
        {
            "credential_type": "pat",
            "label": body.label,
            "token_ref": token_ref,
            "github_app_account_login": login,
            "is_default": body.is_default,
        },
    )
    await audit.record(user.user_id, "github_credential", "create_manual", True, output_summary=body.label)
    return _to_out(row, body.token[-4:] if len(body.token) >= 4 else "****")


@router.get("/oauth-start")
async def oauth_start(user: AuthedUser = Depends(verified_user)):
    """Fetched via `fetch()` with the Authorization header attached, not a direct
    browser navigation — the frontend then does `window.location.href =
    authorize_url` with the URL this returns. See §8's 'One Connect GitHub flow'."""
    settings = get_settings()
    if not settings.github_oauth_client_id:
        raise HTTPException(
            status_code=501,
            detail="GITHUB_OAUTH_CLIENT_ID is not configured on this deployment yet — "
            "see /docs/YOUR_SETUP_CHECKLIST.md, or use 'Add a token manually' instead.",
        )
    state = github_oauth.new_state_token()
    oauth_state.put(state, user.user_id)
    return {"authorize_url": github_oauth.build_authorize_url(state)}


@router.get("/oauth-callback")
async def oauth_callback(code: str = Query(...), state: str = Query(...)):
    """Public — GitHub redirects the browser here directly, with no Authorization
    header. The state token (bound to a user_id in oauth_state.put above) is what
    stands in for auth on this one request."""
    settings = get_settings()
    user_id = oauth_state.pop(state)
    if user_id is None:
        return RedirectResponse(f"{settings.frontend_url}/connections/github?error=invalid_or_expired_state")

    try:
        token = await github_oauth.exchange_code_for_token(code)
        login = await github_oauth.fetch_authenticated_login(token)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"{settings.frontend_url}/connections/github?error={exc}")

    token_ref = await vault.create_secret(token, name=f"github-oauth:{user_id}")
    existing_defaults = await repo.list_for_user(user_id)
    is_first = len(existing_defaults) == 0
    await repo.create(
        user_id,
        {
            "credential_type": "pat",
            "label": f"GitHub OAuth ({login})",
            "token_ref": token_ref,
            "github_app_account_login": login,
            "is_default": is_first,
        },
    )
    await audit.record(user_id, "github_credential", "create_oauth", True, output_summary=login)
    return RedirectResponse(f"{settings.frontend_url}/connections/github?connected={login}")


@router.patch("/{credential_id}/rotate", response_model=GithubCredentialOut)
async def rotate_credential(
    credential_id: str, body: GithubCredentialRotate, user: AuthedUser = Depends(verified_user)
):
    """§24: 'Rotate a credential — Overwrites the Vault-stored value; every project
    currently selecting that credential picks up the new value on its next session
    automatically.' Only meaningful for credential_type == 'pat' — a GitHub App
    credential stores an installation id, not a token, so there's nothing here to
    rotate (it mints short-lived tokens on demand instead, per §13)."""
    existing = await repo.get_for_user(user.user_id, credential_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Credential not found.")
    if existing["credential_type"] != "pat":
        raise HTTPException(
            status_code=400,
            detail="Only 'pat'-type credentials store a rotatable token — GitHub App credentials mint short-lived tokens on demand instead.",
        )

    login = None
    try:
        login = await github_oauth.fetch_authenticated_login(body.token)
    except Exception:  # noqa: BLE001
        pass  # same "validate for real on first use" reasoning as add_token_manually above

    await vault.update_secret(existing["token_ref"], body.token)
    fields = {"github_app_account_login": login} if login else {}
    row = await repo.update_for_user(user.user_id, credential_id, fields) if fields else existing
    await audit.record(user.user_id, "github_credential", "rotate", True, output_summary=credential_id)
    return _to_out(row, body.token[-4:] if len(body.token) >= 4 else "****")


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(credential_id: str, user: AuthedUser = Depends(verified_user)):
    """§24: disconnecting leaves any project that had this credential selected with
    a broken selection, surfaced on that project's page — never a silent fallback."""
    existing = await repo.get_for_user(user.user_id, credential_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Credential not found.")
    affected = await repo.projects_using_credential(user.user_id, credential_id)
    if existing.get("token_ref"):
        await vault.delete_secret(existing["token_ref"])
    await repo.delete_for_user(user.user_id, credential_id)
    await audit.record(
        user.user_id,
        "github_credential",
        "delete",
        True,
        output_summary=f"affected_projects={[p['name'] for p in affected]}",
    )
    return None
