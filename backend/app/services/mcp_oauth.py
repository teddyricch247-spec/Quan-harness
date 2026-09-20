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
    since PKCE is what actually protects the authorization code exchange."""
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
    token_endpoint: str, client_id: str, code: str, redirect_uri: str, code_verifier: str
) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            token_endpoint,
            headers={"Accept": "application/json"},
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "code_verifier": code_verifier,
            },
        )
        if resp.status_code >= 400:
            raise ValueError(f"Token exchange failed: {resp.status_code} {resp.text}")
        return resp.json()  # {access_token, refresh_token?, expires_in?, ...}
