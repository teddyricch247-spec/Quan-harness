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

    # --- Scheduling (§26, Phase 4.5) ---
    # How often the in-process scheduler loop (app/services/scheduler.py)
    # polls project_schedules for anything due. This is the *only* mechanism
    # driving a scheduled run — see docs/PHASE4_5_NOTES.md for why an
    # in-process asyncio loop rather than a separate Render Cron Job service,
    # and the real consequence that follows from it (a schedule can't fire
    # while this single free-tier Render instance is asleep). 60s is frequent
    # enough that "hourly"/"daily" due-checks (whole-minute granularity is
    # more than enough there) and a custom cron expression's own minute-level
    # granularity both land within a minute of their real target time,
    # without polling so often it's the dominant source of idle-time load on
    # a free-tier instance.
    scheduler_poll_interval_seconds: int = 60

    # --- Live Preview (§23.7 / §23.8, Phase 5.3 + 5.4) ---
    # The preview is served from a stable subdomain PER PROJECT
    # (<projects.preview_subdomain>.<PREVIEW_BASE_DOMAIN>) so (a) a client can
    # allowlist one CORS origin once, and (b) the previewed app is served from the
    # root of its own origin — absolute asset paths like /_next/static/... just
    # work, which a path-prefix proxy can't offer. That needs a wildcard DNS record
    # (*.<PREVIEW_BASE_DOMAIN>) pointed at this backend and a wildcard custom domain
    # on the host — see docs/YOUR_SETUP_CHECKLIST.md. Empty = Live Preview is off,
    # and the UI says so plainly rather than rendering a broken iframe.
    preview_base_domain: str = ""
    # "https" in production. "http" only for local development (cookies then drop
    # Secure/SameSite=None, which browsers refuse over plain http).
    preview_scheme: str = "https"
    # Signs the single-use enter token and the preview session cookie. Required
    # when preview_base_domain is set. Generate with `openssl rand -hex 32`. Kept
    # separate from SUPABASE_JWT_SECRET (may be blank, and should never sign
    # anything a user-controlled app origin could observe).
    preview_signing_secret: str = ""
    preview_enter_token_ttl_seconds: int = 60
    preview_session_ttl_seconds: int = 3600
    # The Sprites API token is only ever sent to hosts under this suffix.
    sprites_url_host_suffix: str = ".sprites.app"
    # Billing guardrails (§23.7): a held-open connection keeps a Sprite in the
    # billed `running` state, so every long-lived connection through the proxy has
    # a hard ceiling. WebSocket: closed after this much silence / this much total.
    preview_ws_idle_seconds: int = 90
    preview_ws_max_seconds: int = 900
    # One proxied HTTP response (SSE, long polling) is cut off after this long.
    preview_response_max_seconds: int = 300
    # How long a request is held, retrying, while a hibernated Sprite wakes and
    # its service comes back up, before the person gets a "still starting" page.
    preview_cold_start_wait_seconds: int = 30
    # Comma-separated egress IPs/CIDRs, shown to the person for DB allowlisting
    # (§23.8). Unset = the UI says the list hasn't been configured.
    preview_egress_ips: str = ""

    @property
    def preview_enabled(self) -> bool:
        return bool(self.preview_base_domain.strip()) and bool(self.preview_signing_secret.strip())

    @property
    def preview_egress_ip_list(self) -> list[str]:
        return [ip.strip() for ip in self.preview_egress_ips.split(",") if ip.strip()]

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
