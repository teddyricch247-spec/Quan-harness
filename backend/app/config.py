"""
Central settings object. Everything reads from environment variables so the same
code runs unmodified locally (.env) and on Render (dashboard-configured env vars).
See /docs/YOUR_SETUP_CHECKLIST.md for where each value comes from.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str
    supabase_service_role_key: str
    supabase_anon_key: str
    supabase_jwt_secret: str = ""

    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""

    # --- Fly.io Machines API (§23 — the Workspace Service, Phase 2) ---
    # A dedicated Fly org for workspaces is strongly recommended (never your
    # personal org) — see /docs/YOUR_SETUP_CHECKLIST.md §2.
    fly_api_token: str = ""
    fly_org_slug: str = ""
    fly_api_base: str = "https://api.machines.dev/v1"
    fly_region: str = "iad"
    # A trivial always-available base image is enough — every workspace clones
    # or scaffolds real content into it at ensure_workspace() time; nothing
    # project-specific is baked into the image itself.
    workspace_image: str = "registry-1.docker.io/library/ubuntu:24.04"
    workspace_volume_size_gb: int = 5
    workspace_guest_cpu_kind: str = "shared"
    workspace_guest_cpus: int = 1
    workspace_guest_memory_mb: int = 1024

    frontend_url: str = "http://localhost:3000"
    backend_public_url: str = "http://localhost:8000"

    cors_allowed_origins: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def supabase_jwks_url(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

    @property
    def supabase_auth_url(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
