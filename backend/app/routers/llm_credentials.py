from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import AuthedUser
from app.dependencies import verified_user
from app.models.schemas import LlmCredentialCreate, LlmCredentialOut, LlmCredentialUpdate
from app.repositories import audit, llm_credentials as repo
from app.services import vault

router = APIRouter(prefix="/connections/llm-credentials", tags=["connections"])


def _to_out(row: dict, last_four: str) -> LlmCredentialOut:
    return LlmCredentialOut(
        id=row["id"],
        label=row["label"],
        provider=row["provider"],
        model=row["model"],
        base_url=row.get("base_url"),
        extra_headers=row.get("extra_headers", {}),
        is_default=row["is_default"],
        api_key_last_four=last_four,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("", response_model=list[LlmCredentialOut])
async def list_credentials(user: AuthedUser = Depends(verified_user)):
    rows = await repo.list_for_user(user.user_id)
    out = []
    for row in rows:
        secret = await vault.read_secret(row["api_key_ref"])
        out.append(_to_out(row, (secret or "")[-4:] if secret else "----"))
    return out


@router.post("", response_model=LlmCredentialOut, status_code=status.HTTP_201_CREATED)
async def create_credential(body: LlmCredentialCreate, user: AuthedUser = Depends(verified_user)):
    if body.provider == "custom" and not body.base_url:
        raise HTTPException(status_code=400, detail="base_url is required when provider is 'custom'.")

    api_key_ref = await vault.create_secret(body.api_key, name=f"llm-key:{user.user_id}")

    if body.is_default:
        await repo.clear_default_for_user(user.user_id)

    row = await repo.create(
        user.user_id,
        {
            "label": body.label,
            "provider": body.provider,
            "model": body.model,
            "api_key_ref": api_key_ref,
            "base_url": body.base_url,
            "extra_headers": body.extra_headers,
            "is_default": body.is_default,
        },
    )
    await audit.record(
        user.user_id, "llm_credential", "create", True, output_summary=f"label={body.label}"
    )
    return _to_out(row, body.api_key[-4:] if len(body.api_key) >= 4 else "****")


@router.patch("/{credential_id}", response_model=LlmCredentialOut)
async def update_credential(
    credential_id: str, body: LlmCredentialUpdate, user: AuthedUser = Depends(verified_user)
):
    existing = await repo.get_for_user(user.user_id, credential_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Credential not found.")

    fields: dict = {}
    if body.label is not None:
        fields["label"] = body.label
    if body.model is not None:
        fields["model"] = body.model
    if body.base_url is not None:
        fields["base_url"] = body.base_url
    if body.extra_headers is not None:
        fields["extra_headers"] = body.extra_headers
    if body.api_key is not None:
        # Rotation (§24): overwrite the Vault-stored value in place — every project
        # currently selecting this credential picks up the new value automatically.
        await vault.update_secret(existing["api_key_ref"], body.api_key)
        await audit.record(user.user_id, "llm_credential", "rotate", True, output_summary=credential_id)

    row = await repo.update_for_user(user.user_id, credential_id, fields) if fields else existing
    secret = await vault.read_secret(row["api_key_ref"])
    return _to_out(row, (secret or "")[-4:] if secret else "----")


@router.post("/{credential_id}/set-default", response_model=LlmCredentialOut)
async def set_default(credential_id: str, user: AuthedUser = Depends(verified_user)):
    existing = await repo.get_for_user(user.user_id, credential_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Credential not found.")
    await repo.clear_default_for_user(user.user_id)
    row = await repo.update_for_user(user.user_id, credential_id, {"is_default": True})
    secret = await vault.read_secret(row["api_key_ref"])
    return _to_out(row, (secret or "")[-4:] if secret else "----")


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(credential_id: str, user: AuthedUser = Depends(verified_user)):
    existing = await repo.get_for_user(user.user_id, credential_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Credential not found.")
    await vault.delete_secret(existing["api_key_ref"])
    await repo.delete_for_user(user.user_id, credential_id)
    await audit.record(user.user_id, "llm_credential", "delete", True, output_summary=credential_id)
