from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import AuthedUser
from app.dependencies import current_user, verified_user
from app.models.schemas import (
    LlmCredentialCreate,
    LlmCredentialOut,
    LlmCredentialUpdate,
    LlmModelOut,
    LlmProbeOut,
    LlmProbeRequest,
    ReasoningConfig,
)
from app.repositories import audit, llm_credentials as repo
from app.services import provider_catalog, provider_probe, vault

router = APIRouter(prefix="/connections/llm-credentials", tags=["connections"])


def _reasoning_options(provider: str, model: str) -> dict | None:
    profile = provider_catalog.reasoning_profile(provider, model)
    return profile.to_public() if profile else None


def _validate_reasoning(provider: str, model: str, cfg: ReasoningConfig) -> dict:
    """The dict to store for a credential's thinking config, or a 400 explaining why not.

    An all-default config is always fine (it stores `{}` = the model's own behaviour) — that
    is how a person resets. Anything else must be something this provider/model accepts:
    saying yes to a level the model doesn't know would only fail on the first agent turn.
    """
    stored = cfg.to_stored()
    if not stored:
        return {}
    profile = provider_catalog.reasoning_profile(provider, model)
    if profile is None:
        raise HTTPException(
            status_code=400,
            detail="Thinking controls are only available for OpenRouter models right now; "
            "leave this at the model default for other providers.",
        )
    if cfg.effort is not None and cfg.effort not in profile.accepted_efforts():
        raise HTTPException(
            status_code=400,
            detail=f"{model} doesn't offer the '{cfg.effort}' thinking level. "
            f"Available: {', '.join(profile.accepted_efforts())}.",
        )
    if cfg.max_tokens is not None and not profile.supports_budget:
        raise HTTPException(status_code=400, detail=f"{model} doesn't take a thinking token budget.")
    return stored


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
        # .get: a row read before migration 0013 landed has no such column.
        reasoning=row.get("reasoning") or {},
        reasoning_options=_reasoning_options(row["provider"], row["model"]),
    )


def _probe_out(result: provider_probe.ProbeResult) -> LlmProbeOut:
    return LlmProbeOut(
        status=result.status,
        message=result.message,
        models=[
            LlmModelOut(
                id=m.id,
                name=m.name,
                context_length=m.context_length,
                supports_tools=m.supports_tools,
                supports_reasoning=m.supports_reasoning,
            )
            for m in result.models
        ],
    )


@router.get("/providers")
async def list_provider_presets(_user: AuthedUser = Depends(current_user)):
    """The BYOK preset catalog (provider_catalog.py) — static, no secrets, so any
    signed-in account may read it (an unverified one can still see the page; it just
    can't connect anything yet)."""
    return provider_catalog.public_catalog()


@router.get("/quick-models")
async def list_quick_models(_user: AuthedUser = Depends(current_user)):
    """One-tap connections (provider_catalog.QUICK_MODELS): the person pastes a key and
    nothing else — provider, model and its native thinking levels are preset."""
    return provider_catalog.public_quick_models()


@router.post("/probe", response_model=LlmProbeOut)
async def probe_key(body: LlmProbeRequest, user: AuthedUser = Depends(verified_user)):
    """Check a key (and list its models) BEFORE saving it. Nothing is stored. The key
    is never logged or echoed back; audit records only the provider and the outcome."""
    result = await provider_probe.probe(body.provider, body.api_key, body.base_url)
    await audit.record(
        user.user_id, "llm_credential", "probe", result.status == provider_probe.OK,
        output_summary=f"provider={body.provider} status={result.status}",
    )
    return _probe_out(result)


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
    preset = provider_catalog.get_preset(body.provider)
    if preset is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{body.provider}'.")
    if preset.requires_base_url and not body.base_url:
        raise HTTPException(status_code=400, detail="base_url is required when provider is 'custom'.")

    # Validated before anything is written, so a bad thinking level can't leave an orphaned
    # Vault secret behind.
    reasoning = _validate_reasoning(body.provider, body.model, body.reasoning) if body.reasoning else {}

    api_key_ref = await vault.create_secret(body.api_key, name=f"llm-key:{user.user_id}")

    if body.is_default:
        await repo.clear_default_for_user(user.user_id)

    payload = {
        "label": body.label,
        "provider": body.provider,
        "model": body.model,
        "api_key_ref": api_key_ref,
        "base_url": body.base_url,
        "extra_headers": body.extra_headers,
        "is_default": body.is_default,
    }
    if reasoning:
        # Only sent when set, so credentials with the model default keep working even if this
        # code is ever live before migration 0013 (the column) is.
        payload["reasoning"] = reasoning
    row = await repo.create(user.user_id, payload)
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
    # The thinking config is validated against the model it will end up with, and a model
    # change alone re-checks the stored config: switching to a model that lacks the saved
    # level must not leave a credential that 400s on every turn.
    new_model = body.model if body.model is not None else existing["model"]
    if body.reasoning is not None:
        fields["reasoning"] = _validate_reasoning(existing["provider"], new_model, body.reasoning)
    elif body.model is not None and (existing.get("reasoning") or {}):
        try:
            _validate_reasoning(existing["provider"], new_model, ReasoningConfig(**existing["reasoning"]))
        except HTTPException:
            fields["reasoning"] = {}  # fall back to the new model's own default rather than fail

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


@router.post("/{credential_id}/probe", response_model=LlmProbeOut)
async def probe_saved_credential(credential_id: str, user: AuthedUser = Depends(verified_user)):
    """"Does this saved key still work?" — reads the key from the vault server-side
    (it never leaves the backend) and runs the same check as /probe. Also the natural
    follow-up to a rotation."""
    existing = await repo.get_for_user(user.user_id, credential_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Credential not found.")
    api_key = await vault.read_secret(existing["api_key_ref"])
    if not api_key:
        return LlmProbeOut(status=provider_probe.INVALID_KEY, message="The stored key could not be read from the vault.")
    result = await provider_probe.probe(existing["provider"], api_key, existing.get("base_url"))
    await audit.record(
        user.user_id, "llm_credential", "probe", result.status == provider_probe.OK,
        output_summary=f"{credential_id} status={result.status}",
    )
    return _probe_out(result)


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
