"""
Every credential this system stores — LLM API keys, GitHub tokens, connector auth
tokens, project application secrets — goes through here, never into a plaintext
column (§13). This wraps the qh_vault_* Postgres functions created in
db/migrations/0003_vault_helpers.sql, which are the only things allowed to touch
the `vault` schema directly.

Uses the service_role client (app.db.get_service_client) — the raw secret value
never passes through anywhere the model's tool-calling loop can reach it, and
never gets logged.
"""
import uuid

from starlette.concurrency import run_in_threadpool

from app.db import get_service_client


async def create_secret(secret_value: str, name: str, description: str = "") -> str:
    """Stores a new secret, returns its Vault id (what gets saved as *_ref in the
    owning table — e.g. llm_credentials.api_key_ref)."""
    client = get_service_client()

    def _call():
        # Vault secret names must be unique; suffix with a short random component so
        # two credentials that happen to share a human label never collide.
        unique_name = f"{name}:{uuid.uuid4().hex[:8]}"
        resp = client.rpc(
            "qh_vault_create_secret",
            {"p_secret": secret_value, "p_name": unique_name, "p_description": description},
        ).execute()
        return resp.data

    return await run_in_threadpool(_call)


async def read_secret(secret_id: str) -> str | None:
    client = get_service_client()

    def _call():
        resp = client.rpc("qh_vault_read_secret", {"p_id": secret_id}).execute()
        return resp.data

    return await run_in_threadpool(_call)


async def update_secret(secret_id: str, new_value: str) -> None:
    client = get_service_client()

    def _call():
        client.rpc("qh_vault_update_secret", {"p_id": secret_id, "p_secret": new_value}).execute()

    await run_in_threadpool(_call)


async def delete_secret(secret_id: str) -> None:
    client = get_service_client()

    def _call():
        client.rpc("qh_vault_delete_secret", {"p_id": secret_id}).execute()

    await run_in_threadpool(_call)


def mask_last_four(secret_value: str) -> str:
    """Per §13: the frontend only ever sees 'configured: yes/no' plus the credential's
    last four characters — never the full value."""
    if len(secret_value) <= 4:
        return "*" * len(secret_value)
    return f"{'*' * (len(secret_value) - 4)}{secret_value[-4:]}"
