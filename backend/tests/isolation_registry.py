"""
Phase 6.2 (§5, Implementation Order step 20) — the registry the isolation suite is driven by.

ONE entry per user-owned or project-owned table. An entry says how to build a valid row for an account, which column
the table's owner policy scopes by, and which OTHER foreign keys it carries into user-owned tables (a "cross
reference": the kind of column an owner policy that only checks the row's own scope can miss — see
db/migrations/0014_rls_cross_reference_checks.sql). The matrix (test_isolation_matrix.py) turns each entry into the
full set of attacks; the catalog guard in the same file fails the build if the database contains a table or a
foreign key this file does not know about — which is how a new table can't quietly ship untested the way six did
after Phase 4.

ADDING A TABLE: append a `OwnedTable` to TABLES in dependency order (parents first). If the guard says a foreign key
is undeclared, add it to `cross_refs`. Nothing else — the attacks are generated.

Everything here goes through a signed-in test account's own client (the anon key + that account's token), never the
service role: the service role bypasses RLS, so testing with it would prove nothing about RLS.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

# Every string a test account writes carries this, so a response that leaks another account's data is recognisable.
TAG_PREFIX = "rls-matrix-"


def _hex(n: int = 10) -> str:
    return uuid.uuid4().hex[:n]


class World:
    """One account's set of rows — one per registered table — built through that account's own client."""

    def __init__(self, client, label: str):
        self.client = client
        self.label = label                       # "A" / "B"
        self.tag = f"{TAG_PREFIX}{label}-{_hex()}"
        self.user_id: str = client.auth.get_user().user.id
        self.rows: dict[str, dict] = {}

    # --- building --------------------------------------------------------------------------------------
    def build(self) -> "World":
        for table in TABLES:
            self.rows[table.name] = self.insert(table, table.make(self, {}))
        return self

    def insert(self, table: "OwnedTable", payload: dict) -> dict:
        return self.client.table(table.name).insert(payload).execute().data[0]

    def extra(self, table_name: str, overrides: dict | None = None) -> dict:
        """Another row of `table_name` for this account, with `overrides` applied (the world's own row of each parent
        is used for everything not overridden)."""
        table = BY_NAME[table_name]
        return self.insert(table, table.make(self, overrides or {}))

    # --- ids other rows point at ----------------------------------------------------------------------
    def ref(self, table_name: str):
        """The value another row's foreign key holds when it points at this world's row of `table_name`."""
        return self.rows[table_name]["id"]

    def scope_value(self, scope: str):
        return {
            "user_id": self.user_id,
            "project_id": self.rows.get("projects", {}).get("id"),
            "session_id": self.rows.get("sessions", {}).get("id"),
            "mcp_server_id": self.rows.get("mcp_servers", {}).get("id"),
        }[scope]

    # --- tearing down ---------------------------------------------------------------------------------
    def cleanup(self) -> None:
        """Best effort, children first. Deleting the project cascades most of it; the user-owned tables and
        audit_log have no parent to cascade from, so they're removed by key."""
        for table in reversed(TABLES):
            row = self.rows.get(table.name)
            if not row:
                continue
            try:
                query = self.client.table(table.name).delete()
                for column in table.pk:
                    query = query.eq(column, row[column])
                query.execute()
            except Exception:  # noqa: BLE001 — already gone (cascade), or a failed run left it half-built
                pass


@dataclass(frozen=True)
class OwnedTable:
    name: str
    scope: str                                    # column the owner policy scopes by: user_id | project_id | session_id | mcp_server_id
    make: Callable[[World, dict], dict]           # (world, overrides) -> a valid INSERT payload for that account
    mutate: dict[str, Any]                        # a harmless change an attacker will try on someone else's row
    pk: tuple[str, ...] = ("id",)
    cross_refs: dict[str, str] = field(default_factory=dict)  # column -> table it points at, besides `scope`


def _p(w: World, o: dict) -> dict:
    return {"project_id": w.scope_value("project_id"), **o}


TABLES: list[OwnedTable] = [
    OwnedTable(
        "llm_credentials", "user_id",
        lambda w, o: {"user_id": w.user_id, "label": w.tag, "provider": "anthropic", "model": "claude-test",
                      "api_key_ref": str(uuid.uuid4()), **o},
        mutate={"label": "hijacked"},
    ),
    OwnedTable(
        "github_credentials", "user_id",
        lambda w, o: {"user_id": w.user_id, "credential_type": "pat", "label": w.tag, "token_ref": str(uuid.uuid4()), **o},
        mutate={"label": "hijacked"},
    ),
    OwnedTable(
        "mcp_servers", "user_id",
        lambda w, o: {"user_id": w.user_id, "name": w.tag, "url": "https://example.com/mcp", **o},
        mutate={"name": "hijacked"},
    ),
    OwnedTable(
        "projects", "user_id",
        lambda w, o: {"user_id": w.user_id, "name": w.tag, **o},
        mutate={"name": "hijacked"},
        # guarded by the check_*_credential_owner triggers (P0001), not by the policy — the suite accepts either refusal
        cross_refs={"llm_credential_id": "llm_credentials", "github_credential_id": "github_credentials"},
    ),
    OwnedTable(
        "mcp_tool_overrides", "mcp_server_id",
        lambda w, o: {"mcp_server_id": w.scope_value("mcp_server_id"), "tool_name": f"tool-{_hex()}", "permission_state": "on", **o},
        mutate={"permission_state": "off"},
    ),
    OwnedTable(
        "project_mcp_access", "project_id",
        lambda w, o: _p(w, {"mcp_server_id": w.scope_value("mcp_server_id"), **o}),
        mutate={"granted_at": "2001-01-01T00:00:00+00:00"},
        pk=("project_id", "mcp_server_id"),
        cross_refs={"mcp_server_id": "mcp_servers"},
    ),
    OwnedTable(
        "project_memory", "project_id",
        lambda w, o: _p(w, {"memory_md": f"{w.tag} memory", **o}),
        mutate={"memory_md": "hijacked"},
        pk=("project_id",),
    ),
    OwnedTable(
        "project_knowledge", "project_id",
        lambda w, o: _p(w, {"name": w.tag, "body": "body", "trigger_type": "keyword", "trigger_value": "rls", **o}),
        mutate={"name": "hijacked"},
    ),
    OwnedTable(
        "build_user_memory", "user_id",
        lambda w, o: {"user_id": w.user_id, "memory_md": f"{w.tag} account memory", **o},
        mutate={"memory_md": "hijacked"},
        pk=("user_id",),
    ),
    OwnedTable(
        "project_schedules", "project_id",
        lambda w, o: _p(w, {"description": w.tag, "frequency": "daily", **o}),
        mutate={"description": "hijacked"},
        cross_refs={"last_session_id": "sessions"},
    ),
    OwnedTable(
        "sessions", "project_id",
        lambda w, o: _p(w, {"title": w.tag, **o}),
        mutate={"title": "hijacked"},
        cross_refs={"schedule_id": "project_schedules"},
    ),
    OwnedTable(
        "session_events", "session_id",
        lambda w, o: {"session_id": w.scope_value("session_id"), "role": "user", "event_type": "message",
                      "content": {"text": f"{w.tag} message"}, **o},
        mutate={"content": {"text": "hijacked"}},
        cross_refs={"parent_event_id": "session_events"},
    ),
    OwnedTable(
        "approval_requests", "session_id",
        lambda w, o: {"session_id": w.scope_value("session_id"), "action_type": "execute_bash_escalation",
                      "payload": {"command": w.tag}, **o},
        mutate={"status": "approved"},
    ),
    OwnedTable(
        "session_attachments", "session_id",
        lambda w, o: {"session_id": w.scope_value("session_id"), "filename": f"{w.tag}.png", "media_type": "image/png",
                      "width": 1, "height": 1, "byte_size": 4, "data_b64": "AAAA", **o},
        mutate={"filename": "hijacked.png"},
    ),
    OwnedTable(
        "checkpoints", "project_id",
        lambda w, o: _p(w, {"session_id": w.scope_value("session_id"), "git_commit_sha": "0" * 40,
                            "conversation_snapshot": {"events": [], "tag": w.tag}, **o}),
        mutate={"git_commit_sha": "f" * 40},
        cross_refs={"session_id": "sessions"},
    ),
    OwnedTable(
        "project_memory_log", "project_id",
        lambda w, o: _p(w, {"session_id": w.scope_value("session_id"), "report": f"{w.tag} report", **o}),
        mutate={"report": "hijacked"},
        cross_refs={"session_id": "sessions"},
    ),
    OwnedTable(
        "audit_log", "user_id",
        lambda w, o: {"user_id": w.user_id, "tool": "llm_credential", "action": f"{w.tag} action", "success": True,
                      "initiated_by": "user", **o},
        mutate={"action": "hijacked"},
        cross_refs={"project_id": "projects", "session_id": "sessions"},
    ),
    OwnedTable(
        "project_secrets", "project_id",
        lambda w, o: _p(w, {"name": f"RLS_{_hex()}", "secret_ref": str(uuid.uuid4()), **o}),
        mutate={"name": "HIJACKED"},
    ),
    OwnedTable(
        "preview_secrets", "project_id",
        lambda w, o: _p(w, {"name": f"RLS_{_hex()}", "secret_ref": str(uuid.uuid4()), **o}),
        mutate={"name": "HIJACKED"},
    ),
    OwnedTable(
        "deploy_runs", "project_id",
        lambda w, o: _p(w, {"status": "success", "target_name": w.tag, **o}),
        mutate={"status": "failed"},
    ),
    OwnedTable(
        "project_notifications", "project_id",
        # 'dismissed': an OPEN notification is unique per (project, kind), so an attack row must never be 'open' — a
        # unique-index refusal would hide a missing RLS check behind a different error.
        lambda w, o: _p(w, {"kind": "other", "source": "manual", "title": w.tag, "body": "body", "status": "dismissed", **o}),
        mutate={"title": "hijacked"},
        cross_refs={"deploy_run_id": "deploy_runs"},
    ),
    OwnedTable(
        "project_workspaces", "project_id",
        lambda w, o: _p(w, {"sprite_handle": f"{w.tag}-{_hex(6)}", **o}),
        mutate={"billing_state": "cold"},
        pk=("project_id",),
    ),
]

BY_NAME: dict[str, OwnedTable] = {t.name: t for t in TABLES}
assert len(BY_NAME) == len(TABLES), "duplicate table in TABLES"

# Columns that hold vault secret ids. No foreign key, client-writable — the one known gap (docs/PHASE6_NOTES.md).
VAULT_REF_COLUMNS: dict[str, tuple[str, ...]] = {
    "llm_credentials": ("api_key_ref",),
    "github_credentials": ("token_ref",),
    "mcp_servers": ("auth_token_ref", "oauth_client_secret_ref", "oauth_session_ref"),
    "preview_secrets": ("secret_ref",),
    "project_secrets": ("secret_ref",),
}

# Tables that are in `public` but deliberately not user-owned. Empty: every table here belongs to an account.
EXEMPT_TABLES: frozenset[str] = frozenset()

# The only functions in `public` a signed-in or anonymous caller may be able to execute (trigger functions excluded —
# PostgREST does not expose those). Anything else showing up here is a new RPC surface and needs a decision.
CLIENT_CALLABLE_FUNCTIONS: frozenset[str] = frozenset({"rls_audit"})
