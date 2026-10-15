"""
§9.1: connector auth_mode='oauth' is "for a server implementing the MCP
authorization spec — redirect out, grant, redirect back, tokens stored in Vault
and auto-refreshed."

The MCP authorization spec builds on OAuth 2.1 + RFC 8414 (authorization server
metadata discovery) + RFC 7591 (dynamic client registration) + PKCE, specifically
so a client like this backend never needs a server-specific pre-registered
client_id — it registers itself against whatever server the person points it at,
at connect time.

This is a best-effort implementation of that chain. Real MCP servers vary in how
strictly they follow the spec (some skip DCR and expect a pre-registered client;
some put the metadata document at a path-scoped location rather than the origin
root). Where discovery or registration fails, the error is surfaced plainly
(mcp_servers.last_handshake_error) rather than silently retried — see
/docs/PHASE1_NOTES.md for what to check if a specific server's OAuth connect
fails, and remember static_token mode is the reliable fallback for any server
that just issues a plain bearer token instead.

Phase 4.3 closed two real gaps here, both found by exercising this against a
concrete real-world server rather than only against the spec's own text:

1. **No path for a server without a registration_endpoint.** GitHub's own
   remote MCP server (api.githubcopilot.com/mcp) is a confirmed, documented
   example: its authorization server (github.com) advertises no
   registration_endpoint at all, so `register_client` below always fails
   against it — not a bug in this implementation, but a real gap in what it
   could connect (see github/copilot-cli#4604 and
   github/github-mcp-server#1404 for two independent, current reports of
   exactly this failure). `routers/connectors.py`'s `oauth_start` now accepts
   a pre-registered `oauth_client_id` (optionally with a confidential
   `oauth_client_secret`) as an alternative to DCR — the standard fallback
   every MCP client that talks to GitHub's real server ends up needing,
   confirmed by the same two issues above. `exchange_code` and
   `refresh_access_token` both take an optional `client_secret` for this
   case; a public client (the DCR path) never sends one.
2. **No refresh-token exchange at all** — `exchange_code` got an access token
   and, when the server issued one, a refresh token, but nothing ever
   exchanged that refresh token for a new access token once the original
   expired. Flagged as a real gap in /docs/PHASE3_NOTES.md ("No MCP OAuth
   token refresh"); `refresh_access_token` below closes it. The actual
   refresh-and-retry orchestration (detecting a 401, calling this, updating
   Vault, retrying the call once) lives in `agent_loop.py`'s `_execute_mcp` —
   this module stays a plain, stateless HTTP-call layer, consistent with how
   `exchange_code` itself never touched Vault either.
"""
import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse

import httpx


@dataclass
class AuthServerMetadata:
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None


async def discover_metadata(mcp_server_url: str) -> AuthServerMetadata:
    origin = urlparse(mcp_server_url)
    base = f"{origin.scheme}://{origin.netloc}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{base}/.well-known/oauth-authorization-server")
        if resp.status_code >= 400:
            raise ValueError(
                f"No OAuth authorization server metadata found at {base}/.well-known/"
                "oauth-authorization-server — this server may not implement the MCP "
                "authorization spec's discovery step. Try 'static token' auth mode instead."
            )
        doc = resp.json()
        if "authorization_endpoint" not in doc or "token_endpoint" not in doc:
            raise ValueError("Authorization server metadata is missing required fields.")
        return AuthServerMetadata(
            authorization_endpoint=doc["authorization_endpoint"],
            token_endpoint=doc["token_endpoint"],
            registration_endpoint=doc.get("registration_endpoint"),
        )


async def register_client(registration_endpoint: str, redirect_uri: str) -> str:
    """RFC 7591 dynamic client registration — a public client (no client_secret),
    since PKCE is what actually protects the authorization code exchange.
    Not attempted at all when a connector has a pre-registered oauth_client_id
    on file — see routers/connectors.py's oauth_start, and item 1 in this
    module's own docstring for why that path has to exist."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            registration_endpoint,
            json={
                "client_name": "Quan Harness",
                "redirect_uris": [redirect_uri],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
        )
        if resp.status_code >= 400:
            raise ValueError(f"Dynamic client registration failed: {resp.status_code} {resp.text}")
        return resp.json()["client_id"]


def new_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorize_url(
    authorization_endpoint: str, client_id: str, redirect_uri: str, state: str, code_challenge: str
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{authorization_endpoint}?{urlencode(params)}"


async def exchange_code(
    token_endpoint: str,
    client_id: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    client_secret: str | None = None,
) -> dict:
    """`client_secret` is only ever sent for a pre-registered confidential
    client (see this module's own docstring, item 1) — the DCR path above
    always registers a public client and never has one to pass. Sent as a
    plain POST body parameter (RFC 6749 §2.3.1's "client_secret_post" style),
    the same form GitHub's own `/login/oauth/access_token` endpoint accepts
    for an OAuth App's client_secret."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": code_verifier,
        }
        if client_secret:
            data["client_secret"] = client_secret
        resp = await client.post(
            token_endpoint,
            headers={"Accept": "application/json"},
            data=data,
        )
        if resp.status_code >= 400:
            raise ValueError(f"Token exchange failed: {resp.status_code} {resp.text}")
        return resp.json()  # {access_token, refresh_token?, expires_in?, ...}


async def refresh_access_token(
    token_endpoint: str,
    client_id: str,
    refresh_token: str,
    client_secret: str | None = None,
) -> dict:
    """The refresh half of the token exchange — see this module's own
    docstring, item 2. A plain RFC 6749 §6 grant_type=refresh_token POST,
    same shape and same error handling as exchange_code above (including the
    optional client_secret for a pre-registered confidential client). The
    server may or may not issue a new refresh_token alongside the new
    access_token — some rotate it on every use, some don't; the caller
    (agent_loop.py's `_refresh_oauth_token`) checks for one and only updates
    its stored session if a new one actually came back, rather than assuming
    either behavior."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        }
        if client_secret:
            data["client_secret"] = client_secret
        resp = await client.post(
            token_endpoint,
            headers={"Accept": "application/json"},
            data=data,
        )
        if resp.status_code >= 400:
            raise ValueError(f"Token refresh failed: {resp.status_code} {resp.text}")
        return resp.json()  # {access_token, refresh_token?, expires_in?, ...}
