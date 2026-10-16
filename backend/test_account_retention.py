"""Offline tests for account deletion and diagnostic-record retention (2026-10-13).

Covers, against the REAL module code:

  * app/account.py: the typed confirmation, the order of the deletion steps,
    what happens when a step fails (the account must survive, nothing half-done
    is reported as done), the admin refusal, the confirmation email;
  * app/supabase_client.py: delete_user_rows (table allowlist, request shape,
    row count), delete_auth_user (hard delete, a 404 counts as done),
    purge_expired_chat_traces (the RPC and its body), and start_chat_trace
    (the conversation link is saved for Playground rows only, never for API
    rows, and is dropped cleanly when migration 0016 has not been applied);
  * the wiring: the Playground send route passes the conversation id, the API
    route cannot.

Offline: no fastapi/httpx install needed (small stand-ins below).

Run:  python test_account_retention.py
"""

import asyncio
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

os.environ["SUPABASE_URL"] = "https://sb.test"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "service-role-test"
os.environ.setdefault("OPENROUTER_API_KEY", "or-test")

# ---------------------------------------------------------------------
# Offline stand-ins for fastapi and httpx
# ---------------------------------------------------------------------
fa = types.ModuleType("fastapi")


class HTTPException(Exception):
    def __init__(self, status_code, detail=None, headers=None):
        self.status_code, self.detail = status_code, detail
        super().__init__(f"{status_code}: {detail}")


fa.HTTPException = HTTPException
fa.Request = type("Request", (), {})  # rate_limit.py (imported by account_emails) names it
sys.modules.setdefault("fastapi", fa)
HTTPException = sys.modules["fastapi"].HTTPException  # whichever is registered

hx = types.ModuleType("httpx")


class HTTPError(Exception):
    pass


class HTTPStatusError(HTTPError):
    def __init__(self, m, response=None):
        super().__init__(m)
        self.response = response


hx.HTTPError, hx.HTTPStatusError = HTTPError, HTTPStatusError


class FakeResponse:
    def __init__(self, status_code=200, body=None, headers=None, text=""):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        self.text = text or (str(body) if body is not None else "")

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise HTTPStatusError(f"HTTP {self.status_code}", response=self)


class FakeNet:
    """Records every request and answers from a queue of canned responses
    (or a function)."""

    def __init__(self):
        self.requests = []
        self.responder = lambda req: FakeResponse(200, [])

    def reset(self, responder=None):
        self.requests = []
        self.responder = responder or (lambda req: FakeResponse(200, []))


NET = FakeNet()


class FakeClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def _do(self, method, url, **kw):
        req = {"method": method, "url": url, **kw}
        NET.requests.append(req)
        return NET.responder(req)

    async def get(self, url, **kw):
        return await self._do("GET", url, **kw)

    async def post(self, url, **kw):
        return await self._do("POST", url, **kw)

    async def patch(self, url, **kw):
        return await self._do("PATCH", url, **kw)

    async def delete(self, url, **kw):
        return await self._do("DELETE", url, **kw)

    async def request(self, method, url, **kw):
        return await self._do(method, url, **kw)


hx.AsyncClient = FakeClient
sys.modules["httpx"] = hx

from app import account, supabase_client as sc  # noqa: E402

# ---------------------------------------------------------------------
fails = 0
passed = 0


def check(name, cond):
    global fails, passed
    if cond:
        passed += 1
    else:
        fails += 1
    print(("ok   " if cond else "FAIL ") + name)


def run(coro):
    return asyncio.run(coro)


def raises(coro):
    """Returns (status_code, error_code) of the HTTPException a coroutine raises, or None."""
    try:
        run(coro)
    except HTTPException as e:
        err = (e.detail or {}).get("error", {})
        return e.status_code, err.get("code")
    return None


USER = {"id": "11111111-1111-4111-8111-111111111111", "email": "Person@Example.com", "app_metadata": {}}
ADMIN = {"id": "22222222-2222-4222-8222-222222222222", "email": "boss@example.com", "app_metadata": {"role": "admin"}}
NO_EMAIL = {"id": "33333333-3333-4333-8333-333333333333", "email": "", "app_metadata": {}}

# ---------------------------------------------------------------------
# 1. The typed confirmation
# ---------------------------------------------------------------------
check("confirmation asks for the account email", account.required_confirmation(USER) == "Person@Example.com")
check("confirmation falls back to DELETE when there is no email", account.required_confirmation(NO_EMAIL) == "DELETE")
check("email matches ignoring case and surrounding spaces", account.confirmation_matches(USER, "  person@example.COM "))
check("a different email does not match", not account.confirmation_matches(USER, "other@example.com"))
check("DELETE does not confirm an account that has an email", not account.confirmation_matches(USER, "DELETE"))
check("empty / missing / non-string confirmations never match", not any(account.confirmation_matches(USER, c) for c in ("", None, 5, ["Person@Example.com"], {})))
check("no-email account: DELETE matches, delete does not", account.confirmation_matches(NO_EMAIL, " DELETE ") and not account.confirmation_matches(NO_EMAIL, "delete"))
check("no-email account: an empty string never matches", not account.confirmation_matches(NO_EMAIL, ""))

# ---------------------------------------------------------------------
# 2. delete_account: order, failures, admin, email
# ---------------------------------------------------------------------
calls = []
emails = []
state = {"fail_at": None, "email_fails": False}


async def fake_revoke(user_id):
    calls.append(("revoke_keys", user_id))
    if state["fail_at"] == "revoke_keys":
        raise RuntimeError("db down https://secret-db-url")
    return 2


async def fake_delete_rows(table, user_id):
    calls.append(("delete_rows", table, user_id))
    if state["fail_at"] == f"rows:{table}":
        raise RuntimeError("db down https://secret-db-url")
    return 5


async def fake_delete_auth(user_id):
    calls.append(("delete_auth_user", user_id))
    if state["fail_at"] == "auth":
        raise RuntimeError("gotrue down https://secret-db-url")


async def fake_send_email(**kw):
    emails.append(kw)
    if state["email_fails"]:
        raise RuntimeError("resend down")


# account.py reaches these through module attributes; swap them for the duration
# of section 2 only (section 3 tests the real supabase_client functions).
_ORIGINALS = (
    account.api_keys.revoke_all_active_keys,
    sc.delete_user_rows,
    sc.delete_auth_user,
    account.email_service.send_email,
)
account.api_keys.revoke_all_active_keys = fake_revoke
sc.delete_user_rows = fake_delete_rows
sc.delete_auth_user = fake_delete_auth
account.email_service.send_email = fake_send_email
account.account_emails.config.RESEND_API_KEY = "re_test"  # emails only go out when a key is set


def fresh(**kw):
    calls.clear()
    emails.clear()
    state.update({"fail_at": None, "email_fails": False})
    state.update(kw)


fresh()
out = run(account.delete_account(USER, "person@example.com"))
check("a correct request deletes and answers {'deleted': True}", out == {"deleted": True})
check(
    "order: keys revoked, then the Playground records, then usage records, then the auth user LAST",
    [c[0] if c[0] != "delete_rows" else c[1] for c in calls]
    == ["revoke_keys", "chat_debug_traces", "usage_logs", "delete_auth_user"],
)
check("every step is for the signed-in user's id", all(c[-1] == USER["id"] for c in calls))
check("a confirmation email goes to the address on file, naming no content", len(emails) == 1 and emails[0]["to"] == "Person@Example.com" and "deleted" in emails[0]["subject"].lower())
check("the email says credits were forfeited and mentions the contact address", "forfeited" in emails[0]["html"] and "response@quancis.space" in emails[0]["html"])

fresh()
check("wrong confirmation -> 400 confirmation_required, nothing touched", raises(account.delete_account(USER, "nope")) == (400, "confirmation_required") and calls == [])
fresh()
check("missing confirmation -> 400, nothing touched", raises(account.delete_account(USER, None)) == (400, "confirmation_required") and calls == [])
fresh()
check("admin account -> 403 admin_account, nothing touched", raises(account.delete_account(ADMIN, "boss@example.com")) == (403, "admin_account") and calls == [])
fresh()
check("no user id -> 400, nothing touched", raises(account.delete_account({"email": "a@b.c"}, "a@b.c")) == (400, "invalid_account") and calls == [])

for step, label in (("revoke_keys", "revoking keys"), ("rows:chat_debug_traces", "deleting diagnostic records"), ("rows:usage_logs", "deleting usage records")):
    fresh(fail_at=step)
    got = raises(account.delete_account(USER, "person@example.com"))
    check(f"failure while {label}: 502 delete_failed", got == (502, "delete_failed"))
    check(f"failure while {label}: the auth user is NOT deleted and no email is sent", not any(c[0] == "delete_auth_user" for c in calls) and emails == [])

fresh(fail_at="auth")
check("failure deleting the auth user: 502 delete_failed, no email", raises(account.delete_account(USER, "person@example.com")) == (502, "delete_failed") and emails == [])
try:
    fresh(fail_at="auth")
    run(account.delete_account(USER, "person@example.com"))
except HTTPException as e:
    check("the 502 message carries no internal URL or error text", "secret-db-url" not in str(e.detail) and "gotrue" not in str(e.detail))

fresh(email_fails=True)
check("a failed confirmation email never un-deletes or errors", run(account.delete_account(USER, "person@example.com")) == {"deleted": True})
fresh()
run(account.delete_account(NO_EMAIL, "DELETE"))
check("no email on file: deletes, sends no email", emails == [] and calls[-1][0] == "delete_auth_user")

fresh()
run(account.delete_account(USER, "person@example.com"))
retry_calls = list(calls)
fresh()
run(account.delete_account(USER, "person@example.com"))
check("running the deletion again repeats the same safe steps (retry after a failure)", [c[0] for c in calls] == [c[0] for c in retry_calls])

(
    account.api_keys.revoke_all_active_keys,
    sc.delete_user_rows,
    sc.delete_auth_user,
    account.email_service.send_email,
) = _ORIGINALS

# ---------------------------------------------------------------------
# 3. supabase_client: delete_user_rows / delete_auth_user / purge
# ---------------------------------------------------------------------
BASE = "https://sb.test"

NET.reset(lambda req: FakeResponse(204, None, {"content-range": "*/7"}))
n = run(sc.delete_user_rows("chat_debug_traces", USER["id"]))
req = NET.requests[-1]
check("delete_user_rows: a DELETE on the right table filtered by user_id", req["method"] == "DELETE" and req["url"] == f"{BASE}/rest/v1/chat_debug_traces" and req["params"] == {"user_id": f"eq.{USER['id']}"})
check("delete_user_rows: asks for a count, returns minimal", req["headers"]["Prefer"] == "return=minimal,count=exact")
check("delete_user_rows: returns the row count the database reports", n == 7)
check("delete_user_rows: sends the service-role key, not a user token", req["headers"]["apikey"] == "service-role-test")

NET.reset(lambda req: FakeResponse(204, None, {}))
check("delete_user_rows: no Content-Range -> None, still success", run(sc.delete_user_rows("usage_logs", USER["id"])) is None)

for bad_table in ("billing_accounts", "auth.users", "chat_sessions", "usage_logs; drop table x", ""):
    NET.reset()
    try:
        run(sc.delete_user_rows(bad_table, USER["id"]))
        refused = False
    except ValueError:
        refused = True
    check(f"delete_user_rows refuses table {bad_table!r} and sends nothing", refused and NET.requests == [])

NET.reset(lambda req: FakeResponse(500, None, {}, "boom"))
try:
    run(sc.delete_user_rows("usage_logs", USER["id"]))
    check("delete_user_rows: a server error raises (deletion must stop)", False)
except HTTPError:
    check("delete_user_rows: a server error raises (deletion must stop)", True)

NET.reset(lambda req: FakeResponse(200, {}))
run(sc.delete_auth_user(USER["id"]))
req = NET.requests[-1]
check("delete_auth_user: DELETE on the GoTrue admin endpoint for that user", req["method"] == "DELETE" and req["url"] == f"{BASE}/auth/v1/admin/users/{USER['id']}")
check("delete_auth_user: a hard delete, not a soft delete", req["json"] == {"should_soft_delete": False})

NET.reset(lambda req: FakeResponse(404, None, {}, "not found"))
run(sc.delete_auth_user(USER["id"]))
check("delete_auth_user: 404 (already gone) counts as done", True)

NET.reset(lambda req: FakeResponse(500, None, {}, "boom"))
try:
    run(sc.delete_auth_user(USER["id"]))
    check("delete_auth_user: any other failure raises", False)
except HTTPError:
    check("delete_auth_user: any other failure raises", True)

NET.reset(lambda req: FakeResponse(200, 12))
n = run(sc.purge_expired_chat_traces())
req = NET.requests[-1]
check("purge: POST to the purge_expired_chat_traces rpc", req["method"] == "POST" and req["url"] == f"{BASE}/rest/v1/rpc/purge_expired_chat_traces")
check("purge: retention is 30 days", sc.TRACE_RETENTION_DAYS == 30 and req["json"] == {"p_retention": "30 days"})
check("purge: returns the number of rows removed", n == 12)

NET.reset(lambda req: FakeResponse(200, None))
check("purge: an unexpected answer counts as 0, not a crash", run(sc.purge_expired_chat_traces()) == 0)
NET.reset(lambda req: FakeResponse(404, None, {}, "function not found"))
try:
    run(sc.purge_expired_chat_traces())
    check("purge: a missing function (migration not applied) raises so it is logged", False)
except HTTPError:
    check("purge: a missing function (migration not applied) raises so it is logged", True)

# ---------------------------------------------------------------------
# 4. start_chat_trace: the conversation link
# ---------------------------------------------------------------------
SID = "44444444-4444-4444-8444-444444444444"


def trace_ok(req):
    return FakeResponse(201, [{"id": "trace-1"}])


sc._trace_session_retry_at = 0.0
NET.reset(trace_ok)
tid = run(sc.start_chat_trace(user_id=USER["id"], source="app_chat", session_id=SID, last_user_message="hello", model="m"))
body = NET.requests[-1]["json"]
check("Playground row: saved with the conversation id", tid == "trace-1" and body.get("session_id") == SID)
check("Playground row: keeps the (truncated) message text", body.get("last_user_message") == "hello")

NET.reset(trace_ok)
run(sc.start_chat_trace(user_id=USER["id"], source="app_chat", last_user_message="hello", model="m"))
check("Playground row without a conversation id: no session_id sent", "session_id" not in NET.requests[-1]["json"])

NET.reset(trace_ok)
run(sc.start_chat_trace(user_id=USER["id"], source="api", session_id=SID, last_user_message="secret text", model="m"))
body = NET.requests[-1]["json"]
check("API row: never carries a conversation id", "session_id" not in body)
check("API row: never carries message text", "last_user_message" not in body and "secret text" not in str(body))

# migration 0016 not applied: the first insert is rejected, the retry (without the link) works
sc._trace_session_retry_at = 0.0
attempts = []


def missing_column(req):
    attempts.append(dict(req["json"]))
    if "session_id" in req["json"]:
        return FakeResponse(400, None, {}, '{"code":"PGRST204","message":"Could not find the \'session_id\' column of \'chat_debug_traces\' in the schema cache"}')
    return FakeResponse(201, [{"id": "trace-2"}])


NET.reset(missing_column)
tid = run(sc.start_chat_trace(user_id=USER["id"], source="app_chat", session_id=SID, last_user_message="hi", model="m"))
check("column missing: the row is still saved (second attempt, no link)", tid == "trace-2" and len(attempts) == 2 and "session_id" not in attempts[1])
check("column missing: other fields are preserved on the retry", attempts[1].get("user_id") == USER["id"] and attempts[1].get("last_user_message") == "hi")
attempts.clear()
tid = run(sc.start_chat_trace(user_id=USER["id"], source="app_chat", session_id=SID, last_user_message="again", model="m"))
check("column missing: later requests skip the link at once (one attempt, no wasted failure)", tid == "trace-2" and len(attempts) == 1 and "session_id" not in attempts[0])
sc._trace_session_retry_at = 0.0  # time passes; the migration may have been applied
NET.reset(trace_ok)
run(sc.start_chat_trace(user_id=USER["id"], source="app_chat", session_id=SID, last_user_message="x", model="m"))
check("after the retry window the link is tried again", NET.requests[-1]["json"].get("session_id") == SID)

# an unrelated 400 must not shelve the link
sc._trace_session_retry_at = 0.0
NET.reset(lambda req: FakeResponse(400, None, {}, '{"message":"invalid input syntax for type uuid"}'))
run(sc.start_chat_trace(user_id=USER["id"], source="app_chat", session_id="not-a-uuid", last_user_message="x", model="m"))
check("an unrelated rejection does not switch the link off", sc._trace_session_column_usable())

# a total failure never raises into the request
NET.reset(lambda req: (_ for _ in ()).throw(RuntimeError("network down")))
check("a network failure returns None instead of raising", run(sc.start_chat_trace(user_id=USER["id"], source="app_chat", session_id=SID, model="m")) is None)

# error messages are cut to 500 characters
sc._CONTENT_TRACE_IDS.clear()
NET.reset(lambda req: FakeResponse(200, []))
run(sc.update_chat_trace("trace-9", status="error", error_message="x" * 2000))
check("update_chat_trace: error_message is cut to 500 characters", len(NET.requests[-1]["json"]["error_message"]) == 500)

# ---------------------------------------------------------------------
# 5. Wiring (source-level guards)
# ---------------------------------------------------------------------
main_src = open(os.path.join(HERE, "app", "main.py"), encoding="utf-8").read()
check("main.py: DELETE /api/account is routed to account.delete_account", re.search(r'@app\.delete\("/api/account"\)', main_src) and "account.delete_account(" in main_src)
check("main.py: the Playground send route passes the conversation id", "_in_app_requestor(user, sid)" in main_src)
check("main.py: the API-key requestor never sets chat_session_id", main_src.count('["chat_session_id"]') == 1)
pipe_src = open(os.path.join(HERE, "app", "two_pass_pipeline.py"), encoding="utf-8").read()
check("pipeline: the trace is started with the conversation id from the requestor", 'session_id=requestor.get("chat_session_id")' in pipe_src)
sched_src = open(os.path.join(HERE, "app", "scheduled_checks.py"), encoding="utf-8").read()
check("scheduler: the daily cycle runs the trace purge", "purge_expired_chat_traces" in sched_src and "run_trace_purge" in sched_src)
mig = open(os.path.join(HERE, "supabase", "migrations", "0016_trace_session_link_and_retention.sql"), encoding="utf-8").read()
check("migration 0016: cascade FK from traces to chat_sessions and a service-role-only purge function",
      "on delete cascade" in mig and "purge_expired_chat_traces" in mig and "grant execute" in mig and "service_role" in mig)

print()
print(f"ALL CHECKS PASSED ({passed})" if not fails else f"{fails} CHECK(S) FAILED ({passed} passed)")
sys.exit(1 if fails else 0)
