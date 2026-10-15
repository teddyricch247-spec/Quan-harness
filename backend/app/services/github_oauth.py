"""
§8: the standard OAuth App flow used for the single "Connect GitHub" action
(sync credential). Requires an ordinary GitHub OAuth App — plain client ID/secret,
not a GitHub App with installation/webhook machinery — registered by whoever
deploys this (see /docs/YOUR_SETUP_CHECKLIST.md).

Also used, unmodified, for GitHub-as-a-connector (§9's "GitHub operates its own
hosted, OAuth-based remote MCP server" note is about a *different* thing — that's
GitHub's own remote MCP endpoint, connected like any other connector via
app/routers/connectors.py, not this module).
"""
import secrets
from urllib.parse import urlencode

import httpx

from app.config import get_settings

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_URL = "https://api.github.com"

# repo scope covers read/write to the person's own repositories, which is all the
# Pull/Push sync mechanism (§8) needs. Nothing broader is requested.
OAUTH_SCOPE = "repo"


def build_authorize_url(state: str) -> str:
    settings = get_settings()
    params = {
        "client_id": settings.github_oauth_client_id,
        "redirect_uri": f"{settings.backend_public_url}/connections/github-credential/oauth-callback",
        "scope": OAUTH_SCOPE,
        "state": state,
    }
    return f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"


def new_state_token() -> str:
    return secrets.token_urlsafe(24)


async def exchange_code_for_token(code: str) -> str:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_oauth_client_id,
                "client_secret": settings.github_oauth_client_secret,
                "code": code,
                "redirect_uri": f"{settings.backend_public_url}/connections/github-credential/oauth-callback",
            },
        )
        resp.raise_for_status()
        body = resp.json()
        if "access_token" not in body:
            raise ValueError(body.get("error_description", "GitHub did not return an access token"))
        return body["access_token"]


async def fetch_authenticated_login(token: str) -> str:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{GITHUB_API_URL}/user",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
        resp.raise_for_status()
        return resp.json()["login"]


async def get_repository(token: str, full_name: str) -> dict:
    """Phase 4.4: used by the New Project flow's 'import an existing
    repository' path (§12) to resolve the repository's real default branch
    at project-creation time, rather than assuming "main". A real, common
    mismatch — a repo whose default branch is "master", "develop", or
    anything else GitHub didn't invent for it — and this project's very
    first Pull (git_sync.pull, once harness_branch_ready is still False)
    fetches this exact branch name from the remote, so a wrong guess here
    made that first Pull fail outright with "couldn't find remote ref",
    before the workspace ever had real content in it. A plain REST call,
    same shape as create_repository below."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{GITHUB_API_URL}/repos/{full_name}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
        if resp.status_code >= 400:
            raise ValueError(f"GitHub repository lookup failed: {resp.status_code} {resp.text}")
        data = resp.json()
        return {"full_name": data["full_name"], "default_branch": data.get("default_branch", "main")}


async def create_repository(token: str, name: str, private: bool = True) -> dict:
    """Used by the New Project flow's 'create a new repository right now' path (§12)
    and by git_sync.push()'s 'if the workspace has no linked repo yet, Push first
    prompts to create one' path (§23.3). A plain REST call — no clone, no
    workspace involvement, which is why this is in scope for Phase 1 even though
    the Workspace Service itself isn't."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            f"{GITHUB_API_URL}/user/repos",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            json={"name": name, "private": private},
        )
        if resp.status_code >= 400:
            raise ValueError(f"GitHub repo creation failed: {resp.status_code} {resp.text}")
        data = resp.json()
        return {
            "full_name": data["full_name"],
            "default_branch": data.get("default_branch", "main"),
        }


async def find_open_pull_request(token: str, full_name: str, head_branch: str) -> dict | None:
    """§23.3: 'opening a pull request if one doesn't already exist for it.'"""
    owner = full_name.split("/")[0]
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            f"{GITHUB_API_URL}/repos/{full_name}/pulls",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            params={"head": f"{owner}:{head_branch}", "state": "open"},
        )
        resp.raise_for_status()
        results = resp.json()
        return results[0] if results else None


async def create_pull_request(token: str, full_name: str, head_branch: str, base_branch: str, title: str) -> dict:
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            f"{GITHUB_API_URL}/repos/{full_name}/pulls",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            json={"head": head_branch, "base": base_branch, "title": title},
        )
        if resp.status_code >= 400:
            raise ValueError(f"GitHub PR creation failed: {resp.status_code} {resp.text}")
        data = resp.json()
        return {"number": data["number"], "html_url": data["html_url"]}
