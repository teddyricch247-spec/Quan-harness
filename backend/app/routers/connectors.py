import json
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.core.security import AuthedUser
from app.dependencies import verified_user
from app.models.schemas import McpServerCreate, McpServerOut, McpToolOverrideUpdate
from app.repositories import audit, mcp_servers as repo
from app.services import mcp_handshake, mcp_oauth, mcp_oauth_state, vault

router = APIRouter(prefix="/connections/connectors", tags=["connections"])


async def _to_out(row: dict) -> McpServerOut:
    # §9.4's own resolution rule: mcp_tool_overrides.permission_state if set, else
    # the server's default_permission_state. Without this, the person has no way
    # to see what's actually in effect for a tool without re-clicking through the
    # three options — the UI would show every tool as blank/unset on every reload.
    overrides = {o["tool_name"]: o["permission_state"] for o in await repo.list_overrides(row["id"])}
    tools = []
    for t in row.get("discovered_tools") or []:
        effective = overrides.get(t["name"]) or row["default_permission_state"]
        tools.append({"name": t["name"], "description": t.get("description", ""), "permission_state": effective})
    return McpServerOut(
        id=row["id"],
        name=row["name"],
        url=row["url"],
        auth_mode=row["auth_mode"],
        enabled=row["enabled"],
        default_permission_state=row["default_permission_state"],
        discovered_tools=tools,
        oauth_client_id=row.get("oauth_client_id"),
        last_handshake_at=row.get("last_handshake_at"),
        last_handshake_error=row.get("last_handshake_error"),
        created_at=row["created_at"],
    )


def _callback_url(connector_id: str) -> str:
    settings = get_settings()
    return f"{settings.backend_public_url}/connections/connectors/{connector_id}/oauth-callback"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("", response_model=list[McpServerOut])
async def list_connectors(user: AuthedUser = Depends(verified_user)):
    rows = await repo.list_for_user(user.user_id)
    return [await _to_out(r) for r in rows]


@router.post("", response_model=McpServerOut, status_code=status.HTTP_201_CREATED)
async def create_connector(body: McpServerCreate, user: AuthedUser = Depends(verified_user)):
    """§9.1: writes a *draft* row (enabled=false) immediately so oauth-mode
    connectors have an {id} to redirect against; for none/static_token modes the
    handshake runs right away since no redirect is needed. Either way, nothing
    merges into any project's tool set until the person calls /confirm — §9.4's
    runtime tool merge only ever looks at enabled=true servers.

    Phase 4.3: also accepts a pre-registered oauth_client_id (and, for a
    confidential client, oauth_client_secret) — see mcp_oauth.py's module
    docstring for why this exists (GitHub's own remote MCP server is the
    concrete real-world case that doesn't work without it). Stored now, used
    by oauth_start below at connect time.
    """
    if body.auth_mode == "static_token" and not body.static_token:
        raise HTTPException(status_code=400, detail="static_token is required when auth_mode is 'static_token'.")
    if body.oauth_client_secret and not body.oauth_client_id:
        raise HTTPException(status_code=400, detail="oauth_client_secret requires oauth_client_id to also be set.")
    if (body.oauth_client_id or body.oauth_client_secret) and body.auth_mode != "oauth":
        raise HTTPException(
            status_code=400, detail="oauth_client_id/oauth_client_secret only apply when auth_mode is 'oauth'."
        )

    auth_token_ref = None
    if body.auth_mode == "static_token":
        auth_token_ref = await vault.create_secret(body.static_token, name=f"mcp-token:{user.user_id}")

    oauth_client_secret_ref = None
    if body.oauth_client_secret:
        oauth_client_secret_ref = await vault.create_secret(
            body.oauth_client_secret, name=f"mcp-oauth-client-secret:{user.user_id}"
        )

    row = await repo.create(
        user.user_id,
        {
            "name": body.name,
            "url": body.url,
            "auth_mode": body.auth_mode,
            "auth_token_ref": auth_token_ref,
            "oauth_client_id": body.oauth_client_id,
            "oauth_client_secret_ref": oauth_client_secret_ref,
            "enabled": False,
            "default_permission_state": body.default_permission_state,
        },
    )

    if body.auth_mode in ("none", "static_token"):
        result = await mcp_handshake.handshake(body.url, body.auth_mode, body.static_token)
        row = await repo.update_for_user(
            user.user_id,
            row["id"],
            {
                "discovered_tools": result.tools,
                "last_handshake_error": result.error,
                "last_handshake_at": _now_iso(),
            },
        )
    return await _to_out(row)


@router.get("/{connector_id}/oauth-start")
async def oauth_start(connector_id: str, user: AuthedUser = Depends(verified_user)):
    row = await repo.get_for_user(user.user_id, connector_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Connector not found.")
    if row["auth_mode"] != "oauth":
        raise HTTPException(status_code=400, detail="This connector isn't set up for OAuth auth.")

    try:
        metadata = await mcp_oauth.discover_metadata(row["url"])
        redirect_uri = _callback_url(connector_id)
        if row.get("oauth_client_id"):
            # Phase 4.3: a stored pre-registered client always wins over
            # attempting DCR, even if the server happens to also advertise a
            # registration_endpoint — the person explicitly supplied this one
            # (typically because DCR is known not to work against this
            # server; GitHub's remote MCP server is the confirmed case this
            # was added for — see mcp_oauth.py's module docstring).
            client_id = row["oauth_client_id"]
        elif metadata.registration_endpoint:
            client_id = await mcp_oauth.register_client(metadata.registration_endpoint, redirect_uri)
        else:
            raise ValueError(
                "Server has no dynamic client registration endpoint — it expects a "
                "pre-registered client. Add this connector's OAuth Client ID (and Client "
                "Secret, if it's confidential) and try again, or use 'static token' mode "
                "instead if the server accepts a personal access token."
            )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc))

    verifier, challenge = mcp_oauth.new_pkce_pair()
    state = secrets.token_urlsafe(24)
    mcp_oauth_state.put(
        state,
        {
            "user_id": user.user_id,
            "connector_id": connector_id,
            "code_verifier": verifier,
            "client_id": client_id,
            "client_secret_ref": row.get("oauth_client_secret_ref"),
            "token_endpoint": metadata.token_endpoint,
            "redirect_uri": redirect_uri,
        },
    )
    authorize_url = mcp_oauth.build_authorize_url(
        metadata.authorization_endpoint, client_id, redirect_uri, state, challenge
    )
    return {"authorize_url": authorize_url}


@router.get("/{connector_id}/oauth-callback")
async def oauth_callback(connector_id: str, code: str = Query(...), state: str = Query(...)):
    settings = get_settings()
    entry = mcp_oauth_state.pop(state)
    if entry is None or entry["connector_id"] != connector_id:
        return RedirectResponse(f"{settings.frontend_url}/connections/connectors?error=invalid_or_expired_state")

    client_secret = None
    if entry.get("client_secret_ref"):
        client_secret = await vault.read_secret(entry["client_secret_ref"])

    try:
        token_response = await mcp_oauth.exchange_code(
            entry["token_endpoint"],
            entry["client_id"],
            code,
            entry["redirect_uri"],
            entry["code_verifier"],
            client_secret=client_secret,
        )
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"{settings.frontend_url}/connections/connectors?error={exc}")

    access_token = token_response.get("access_token")
    refresh_token = token_response.get("refresh_token")
    auth_token_ref = await vault.create_secret(access_token, name=f"mcp-oauth-access:{entry['user_id']}")
    oauth_session_ref = None
    if refresh_token:
        oauth_session_ref = await vault.create_secret(
            json.dumps(
                {
                    "refresh_token": refresh_token,
                    "client_id": entry["client_id"],
                    "token_endpoint": entry["token_endpoint"],
                }
            ),
            name=f"mcp-oauth-session:{entry['user_id']}",
        )

    result = await mcp_handshake.handshake(
        (await repo.get_for_user(entry["user_id"], connector_id))["url"], "oauth", access_token
    )
    await repo.update_for_user(
        entry["user_id"],
        connector_id,
        {
            "auth_token_ref": auth_token_ref,
            "oauth_session_ref": oauth_session_ref,
            "discovered_tools": result.tools,
            "last_handshake_error": result.error,
            "last_handshake_at": _now_iso(),
        },
    )
    return RedirectResponse(f"{settings.frontend_url}/connections/connectors?review={connector_id}")


@router.post("/{connector_id}/confirm", response_model=McpServerOut)
async def confirm_connector(connector_id: str, user: AuthedUser = Depends(verified_user)):
    """§9.1: 'Only on explicit confirmation does a row get written to mcp_servers,
    discovered_tools populated from that handshake, enabled = true.' The draft row
    already exists (created in POST /connectors above); this is the activation step
    — before this, the connector is inert everywhere (§9.4 only merges enabled=true
    servers into any session's tool set)."""
    row = await repo.get_for_user(user.user_id, connector_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Connector not found.")
    if row.get("last_handshake_error"):
        raise HTTPException(
            status_code=400,
            detail=f"Last handshake failed ({row['last_handshake_error']}) — fix the connector and refresh before confirming.",
        )
    updated = await repo.update_for_user(user.user_id, connector_id, {"enabled": True})
    await audit.record(user.user_id, "mcp_server_admin", "confirm", True, output_summary=row["name"])
    return await _to_out(updated)


@router.post("/{connector_id}/refresh", response_model=McpServerOut)
async def refresh_connector(connector_id: str, user: AuthedUser = Depends(verified_user)):
    """§9.2: 'Refreshing a connector re-runs the handshake and updates
    discovered_tools; a newly-present tool starts at Ask; a permission override
    whose tool_name no longer appears is deleted.'"""
    row = await repo.get_for_user(user.user_id, connector_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Connector not found.")

    token = None
    if row["auth_mode"] == "static_token" and row.get("auth_token_ref"):
        token = await vault.read_secret(row["auth_token_ref"])
    elif row["auth_mode"] == "oauth" and row.get("auth_token_ref"):
        token = await vault.read_secret(row["auth_token_ref"])

    result = await mcp_handshake.handshake(row["url"], row["auth_mode"], token)
    updated = await repo.update_for_user(
        user.user_id,
        connector_id,
        {
            "discovered_tools": result.tools,
            "last_handshake_error": result.error,
            "last_handshake_at": _now_iso(),
        },
    )
    current_names = [t["name"] for t in result.tools]
    await repo.delete_overrides_not_in(connector_id, current_names)
    await audit.record(user.user_id, "mcp_server_admin", "refresh", result.ok, output_summary=row["name"])
    return await _to_out(updated)


@router.patch("/{connector_id}/tools/{tool_name}", status_code=status.HTTP_204_NO_CONTENT)
async def set_tool_permission(
    connector_id: str, tool_name: str, body: McpToolOverrideUpdate, user: AuthedUser = Depends(verified_user)
):
    row = await repo.get_for_user(user.user_id, connector_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Connector not found.")
    await repo.upsert_override(connector_id, tool_name, body.permission_state)
    await audit.record(
        user.user_id,
        "mcp_server_admin",
        "set_tool_permission",
        True,
        output_summary=f"{row['name']}:{tool_name}={body.permission_state}",
    )


@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connector(connector_id: str, user: AuthedUser = Depends(verified_user)):
    """§9.2: 'Disconnecting hard-deletes the mcp_servers row, cascading to
    overrides and every project's project_mcp_access grant, invalidating its Vault
    credential in the same operation.'"""
    row = await repo.get_for_user(user.user_id, connector_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Connector not found.")
    if row.get("auth_token_ref"):
        await vault.delete_secret(row["auth_token_ref"])
    if row.get("oauth_session_ref"):
        await vault.delete_secret(row["oauth_session_ref"])
    if row.get("oauth_client_secret_ref"):
        # Phase 4.3: the pre-registered confidential client's secret, when one
        # was stored — same "invalidating its Vault credential in the same
        # operation" requirement §9.2 already states for the other two refs
        # on this row, just as real a credential as either of them.
        await vault.delete_secret(row["oauth_client_secret_ref"])
    await repo.delete_for_user(user.user_id, connector_id)
    await audit.record(user.user_id, "mcp_server_admin", "delete", True, output_summary=row["name"])
