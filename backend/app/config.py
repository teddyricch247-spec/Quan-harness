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

    # --- Fly.io Sprites (§23 — the Workspace Service, Phase 2) ---
    # Ported from a Fly Machines integration (see PHASE2_NOTES.md) — Sprites
    # replace the old App+Volume+Machine trio with one unit that already has
    # its own persistent disk, so there's no image/volume-size/guest-resources
    # config left to set: every Sprite gets a fixed 8 vCPUs, autoscaled
    # memory, and 100GB of storage from the platform itself. A token scopes to
    # one org on its own (create one at https://sprites.dev/account, or via
    # `sprite org auth`), so there's no separate org-slug/region setting to
    # keep in sync the way Machines needed either — see
    # /docs/YOUR_SETUP_CHECKLIST.md §3.
    sprites_api_token: str = ""
    sprites_api_base: str = "https://api.sprites.dev"

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
