"""
Run: `pytest backend/tests/test_rls_isolation.py -v` with the env vars from
conftest.py set. Run this in CI on every PR that touches a table's schema or
policies (§5) — not as a one-time manual pass.

Each test: account A creates a row through its own authenticated client (so it's
a real row, created the way a real user would create it), then asserts account
B's client — querying the same table, same row id, through PostgREST with B's own
JWT — gets back zero rows. That's the actual guarantee RLS is supposed to provide;
this doesn't test the backend's own service_role-scoped repository functions
(app/repositories/), which is a separate, already-structural defense (§5).
"""
import pytest


def _user_id(client) -> str:
    return client.auth.get_user().user.id


class TestLlmCredentialsIsolation:
    def test_b_cannot_read_a_credential(self, client_a, client_b):
        created = (
            client_a.table("llm_credentials")
            .insert(
                {
                    "user_id": _user_id(client_a),
                    "label": "rls-test",
                    "provider": "anthropic",
                    "model": "claude-test",
                    "api_key_ref": "00000000-0000-0000-0000-000000000000",
                }
            )
            .execute()
            .data[0]
        )
        try:
            rows = client_b.table("llm_credentials").select("*").eq("id", created["id"]).execute().data
            assert rows == []

            all_visible_to_b = client_b.table("llm_credentials").select("id").execute().data
            assert created["id"] not in [r["id"] for r in all_visible_to_b]
        finally:
            client_a.table("llm_credentials").delete().eq("id", created["id"]).execute()


class TestProjectsIsolation:
    def test_b_cannot_read_or_modify_a_project(self, client_a, client_b):
        created = (
            client_a.table("projects")
            .insert({"user_id": _user_id(client_a), "name": "rls-test-project"})
            .execute()
            .data[0]
        )
        try:
            rows = client_b.table("projects").select("*").eq("id", created["id"]).execute().data
            assert rows == []

            # B attempting to rename A's project should affect zero rows, not error —
            # RLS turns "found and modified" into "not found," per §5.
            update_result = (
                client_b.table("projects").update({"name": "hijacked"}).eq("id", created["id"]).execute()
            )
            assert update_result.data == []

            # Same for delete — an invisible row must also be an unmodifiable one, per §5.
            delete_result = client_b.table("projects").delete().eq("id", created["id"]).execute()
            assert delete_result.data == []

            # Confirm A's project is genuinely untouched by either attempt.
            still_a_named = client_a.table("projects").select("name").eq("id", created["id"]).execute().data
            assert still_a_named[0]["name"] == "rls-test-project"
        finally:
            client_a.table("projects").delete().eq("id", created["id"]).execute()


class TestSessionsIsolation:
    def test_b_cannot_read_a_session_via_project_join(self, client_a, client_b):
        project = (
            client_a.table("projects")
            .insert({"user_id": _user_id(client_a), "name": "rls-test-project-for-session"})
            .execute()
            .data[0]
        )
        session = (
            client_a.table("sessions").insert({"project_id": project["id"], "title": "rls-test"}).execute().data[0]
        )
        try:
            rows = client_b.table("sessions").select("*").eq("id", session["id"]).execute().data
            assert rows == [], "account B must not see account A's session, even via the project join"
        finally:
            client_a.table("projects").delete().eq("id", project["id"]).execute()  # cascades to sessions


class TestGithubCredentialsIsolation:
    def test_b_cannot_read_a_github_credential(self, client_a, client_b):
        created = (
            client_a.table("github_credentials")
            .insert(
                {
                    "user_id": _user_id(client_a),
                    "credential_type": "pat",
                    "label": "rls-test",
                    "token_ref": "00000000-0000-0000-0000-000000000000",
                }
            )
            .execute()
            .data[0]
        )
        try:
            rows = client_b.table("github_credentials").select("*").eq("id", created["id"]).execute().data
            assert rows == []
        finally:
            client_a.table("github_credentials").delete().eq("id", created["id"]).execute()


class TestMcpServersIsolation:
    def test_b_cannot_read_a_connector_or_its_overrides(self, client_a, client_b):
        server = (
            client_a.table("mcp_servers")
            .insert({"user_id": _user_id(client_a), "name": "rls-test-connector", "url": "https://example.com/mcp"})
            .execute()
            .data[0]
        )
        override = (
            client_a.table("mcp_tool_overrides")
            .insert({"mcp_server_id": server["id"], "tool_name": "test_tool", "permission_state": "on"})
            .execute()
            .data[0]
        )
        try:
            assert client_b.table("mcp_servers").select("*").eq("id", server["id"]).execute().data == []
            assert (
                client_b.table("mcp_tool_overrides").select("*").eq("id", override["id"]).execute().data == []
            )
        finally:
            client_a.table("mcp_servers").delete().eq("id", server["id"]).execute()  # cascades to overrides


class TestProjectMcpAccessIsolation:
    def test_b_cannot_read_as_grant_even_from_bs_own_project_row(self, client_a, client_b):
        """B querying project_mcp_access with no filter at all (the realistic case — a
        buggy or malicious query wouldn't know A's project id to filter it out) must
        never see A's grant rows, even though B has a project of their own generating
        legitimate rows in the same table."""
        a_project = client_a.table("projects").insert({"user_id": _user_id(client_a), "name": "rls-a-project"}).execute().data[0]
        a_server = (
            client_a.table("mcp_servers")
            .insert({"user_id": _user_id(client_a), "name": "rls-a-connector", "url": "https://example.com/mcp"})
            .execute()
            .data[0]
        )
        a_grant = (
            client_a.table("project_mcp_access")
            .insert({"project_id": a_project["id"], "mcp_server_id": a_server["id"]})
            .execute()
            .data[0]
        )

        b_project = client_b.table("projects").insert({"user_id": _user_id(client_b), "name": "rls-b-project"}).execute().data[0]
        b_server = (
            client_b.table("mcp_servers")
            .insert({"user_id": _user_id(client_b), "name": "rls-b-connector", "url": "https://example.com/mcp"})
            .execute()
            .data[0]
        )
        b_grant = (
            client_b.table("project_mcp_access")
            .insert({"project_id": b_project["id"], "mcp_server_id": b_server["id"]})
            .execute()
            .data[0]
        )

        try:
            visible_to_b = client_b.table("project_mcp_access").select("project_id,mcp_server_id").execute().data
            assert (a_grant["project_id"], a_grant["mcp_server_id"]) not in [
                (r["project_id"], r["mcp_server_id"]) for r in visible_to_b
            ]
            assert (b_grant["project_id"], b_grant["mcp_server_id"]) in [
                (r["project_id"], r["mcp_server_id"]) for r in visible_to_b
            ], "B should still see B's own grant — this is an isolation test, not a lockout test"
        finally:
            client_a.table("projects").delete().eq("id", a_project["id"]).execute()  # cascades project_mcp_access
            client_a.table("mcp_servers").delete().eq("id", a_server["id"]).execute()
            client_b.table("projects").delete().eq("id", b_project["id"]).execute()
            client_b.table("mcp_servers").delete().eq("id", b_server["id"]).execute()


class TestSessionLifecycleTablesIsolation:
    """checkpoints, session_events, and approval_requests exist in this phase's schema
    (§10.3 — "one standalone data model") with RLS enabled, but nothing writes real rows
    to them until the turn loop lands in Phase 3. That's not a reason to leave their
    policies unverified now: a policy written today and first exercised in Phase 3 is
    exactly the kind of thing that should already be known to work, not discovered broken
    once real conversation data is on the line."""

    def _make_project_and_session(self, client):
        project = client.table("projects").insert({"user_id": _user_id(client), "name": "rls-lifecycle-project"}).execute().data[0]
        session = client.table("sessions").insert({"project_id": project["id"], "title": "rls-lifecycle-session"}).execute().data[0]
        return project, session

    def test_checkpoints_isolated_via_project_and_session_join(self, client_a, client_b):
        project, session = self._make_project_and_session(client_a)
        checkpoint = (
            client_a.table("checkpoints")
            .insert(
                {
                    "project_id": project["id"],
                    "session_id": session["id"],
                    "git_commit_sha": "0" * 40,
                    "conversation_snapshot": {"events": []},
                }
            )
            .execute()
            .data[0]
        )
        try:
            assert client_b.table("checkpoints").select("*").eq("id", checkpoint["id"]).execute().data == []
        finally:
            client_a.table("projects").delete().eq("id", project["id"]).execute()  # cascades session + checkpoint

    def test_session_events_isolated_via_session_and_project_join(self, client_a, client_b):
        project, session = self._make_project_and_session(client_a)
        event = (
            client_a.table("session_events")
            .insert(
                {
                    "session_id": session["id"],
                    "role": "user",
                    "event_type": "message",
                    "content": {"text": "rls-test"},
                }
            )
            .execute()
            .data[0]
        )
        try:
            assert client_b.table("session_events").select("*").eq("id", event["id"]).execute().data == []
        finally:
            client_a.table("projects").delete().eq("id", project["id"]).execute()

    def test_approval_requests_isolated_via_session_and_project_join(self, client_a, client_b):
        project, session = self._make_project_and_session(client_a)
        approval = (
            client_a.table("approval_requests")
            .insert(
                {
                    "session_id": session["id"],
                    "action_type": "execute_bash_escalation",
                    "payload": {"command": "rls-test"},
                }
            )
            .execute()
            .data[0]
        )
        try:
            assert client_b.table("approval_requests").select("*").eq("id", approval["id"]).execute().data == []
        finally:
            client_a.table("projects").delete().eq("id", project["id"]).execute()


class TestAuditLogIsolation:
    def test_b_cannot_read_as_audit_row(self, client_a, client_b):
        """audit_log is scoped directly by user_id (§10.3), not through a project join —
        the one table in this file where that's the case, so it's worth its own test
        rather than assuming the join-based tests above cover it too."""
        row = (
            client_a.table("audit_log")
            .insert(
                {
                    "user_id": _user_id(client_a),
                    "tool": "llm_credential",
                    "action": "rls-test",
                    "success": True,
                    "initiated_by": "user",
                }
            )
            .execute()
            .data[0]
        )
        try:
            assert client_b.table("audit_log").select("*").eq("id", row["id"]).execute().data == []
        finally:
            client_a.table("audit_log").delete().eq("id", row["id"]).execute()


class TestBroadSelectNeverLeaksARowCount:
    """A second failure mode beyond direct-id lookups: an unfiltered `select * from
    projects` as account A must return exactly A's own rows, never more — this is what
    catches a policy that's present but too permissive (e.g. an accidental `using
    (true)`), which every test above would miss since they all filter by a specific id."""

    def test_projects_broad_select_matches_exactly_as_own_rows(self, client_a, client_b):
        a_project = client_a.table("projects").insert({"user_id": _user_id(client_a), "name": "rls-count-a"}).execute().data[0]
        b_project = client_b.table("projects").insert({"user_id": _user_id(client_b), "name": "rls-count-b"}).execute().data[0]
        try:
            visible_to_a = client_a.table("projects").select("id").execute().data
            visible_ids = {r["id"] for r in visible_to_a}
            assert a_project["id"] in visible_ids
            assert b_project["id"] not in visible_ids, (
                "projects: account A's broad select returned account B's row — "
                "a policy may be scoping too broadly."
            )
        finally:
            client_a.table("projects").delete().eq("id", a_project["id"]).execute()
            client_b.table("projects").delete().eq("id", b_project["id"]).execute()
