"""Plain-script test of the chat_messages.thinking fallback in
app/supabase_client.py, against a fake httpx client (no network, no DB).

Run: python test_chat_thinking_column.py
"""
import asyncio, os, sys, time
for k in ["SUPABASE_URL","SUPABASE_SERVICE_ROLE_KEY","SUPABASE_ANON_KEY","API_KEY_PEPPER","OPENROUTER_API_KEY","RESEND_API_KEY","FRONTEND_URL"]:
    os.environ.setdefault(k, "x" if k != "FRONTEND_URL" else "http://localhost:3000")
os.environ["SUPABASE_URL"] = "http://x"
import datetime
from app import supabase_client as sc

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FAIL ") + name)
    if not cond: fails += 1

class Resp:
    def __init__(self, status, body, text=""):
        self.status_code, self._body, self.text = status, body, text
    def json(self): return self._body
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")

log = []
db = {"has_column": False, "reject_thinking": False, "reject_all": False}

class FakeClient:
    def __init__(self, *a, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def post(self, url, headers=None, json=None, **k):
        import copy
        json = copy.deepcopy(json)   # the code under test mutates its rows between attempts
        log.append(("POST", json))
        # PostgREST refuses a bulk insert whose rows have different keys. This
        # is the exact failure that lost every reply with thinking titles in prod.
        if isinstance(json, list) and len({tuple(sorted(r)) for r in json}) > 1:
            return Resp(400, None, '{"code":"PGRST102","details":null,"hint":null,"message":"All object keys must match"}')
        if db["reject_all"]:
            return Resp(500, None, "boom")
        if db["reject_thinking"] and any("thinking" in r for r in json):
            return Resp(400, None, "some unrelated failure about the payload")
        if not db["has_column"] and any("thinking" in r for r in json):
            return Resp(400, None, 'PGRST204 Could not find the \'thinking\' column of \'chat_messages\' in the schema cache')
        return Resp(201, None)
    async def get(self, url, headers=None, params=None, **k):
        log.append(("GET", dict(params)))
        if not db["has_column"] and "thinking" in params["select"]:
            return Resp(400, None, 'column chat_messages.thinking does not exist')
        return Resp(200, [{"role": "user", "content": "q"}])
sc.httpx.AsyncClient = FakeClient

AT = datetime.datetime.now(datetime.timezone.utc)
async def run():
    # column missing: the save must still succeed, without thinking
    ok = await sc.insert_chat_exchange("s", "q", "a", AT, thinking=["Planning"])
    posts = [j for m, j in log if m == "POST"]
    check("save succeeds when the column is missing", ok is True)
    check("first attempt included thinking, retry did not", len(posts) == 2 and "thinking" in posts[0][1] and "thinking" not in posts[1][1])
    # shelved: next save doesn't even try
    log.clear()
    ok = await sc.insert_chat_exchange("s", "q", "a", AT, thinking=["Planning"])
    check("shelved column is not retried right away", ok is True and len([1 for m, _ in log if m == "POST"]) == 1 and "thinking" not in [j for m, j in log if m == "POST"][0][1])
    # read path while shelved
    log.clear()
    rows = await sc.list_chat_messages("s", limit=10, with_thinking=True)
    check("read skips the column while shelved", rows and "thinking" not in [p for m, p in log if m == "GET"][0]["select"])
    # no thinking given: plain save, no column touched
    sc._thinking_column_retry_at = 0.0; log.clear()
    await sc.insert_chat_exchange("s", "q", "a", AT, thinking=None)
    check("no thinking -> no thinking key", "thinking" not in [j for m, j in log if m == "POST"][0][1])
    # read path discovers the missing column by itself
    sc._thinking_column_retry_at = 0.0; log.clear()
    rows = await sc.list_chat_messages("s", limit=10, with_thinking=True)
    gets = [p for m, p in log if m == "GET"]
    check("read retries without the column when rejected", len(gets) == 2 and "thinking" in gets[0]["select"] and "thinking" not in gets[1]["select"] and rows)
    check("history read (no with_thinking) never asks for it", "thinking" not in (log.clear() or (await sc.list_chat_messages("s", limit=5) and [p for m, p in log if m == "GET"][0]["select"])))
    # column exists after the migration (and the shelf timer has run out)
    db["has_column"] = True; sc._thinking_column_retry_at = 0.0; log.clear()
    ok = await sc.insert_chat_exchange("s", "q", "a", AT, thinking=["Planning", " ", 3])
    posts = [j for m, j in log if m == "POST"]
    check("with the column, thinking is saved (cleaned) in one request", ok and len(posts) == 1 and posts[0][1]["thinking"] == ["Planning"])
    log.clear()
    await sc.list_chat_messages("s", limit=10, with_thinking=True)
    check("with the column, read asks for it once", len([1 for m, _ in log if m == "GET"]) == 1 and "thinking" in [p for m, p in log if m == "GET"][0]["select"])
    # regression: both rows carry the same keys (PGRST102 on 2026-10-05)
    log.clear()
    ok = await sc.insert_chat_exchange("s", "q", "a", AT, thinking=["Planning"])
    rows = [j for m, j in log if m == "POST"][0]
    check("every row in the bulk insert has the same keys", ok is True and len({tuple(sorted(r)) for r in rows}) == 1)
    check("thinking is on the reply row only (user row is null)", rows[0]["thinking"] is None and rows[1]["thinking"] == ["Planning"])
    # a failure caused by the thinking titles must not lose the reply
    db["reject_thinking"] = True; log.clear()
    ok = await sc.insert_chat_exchange("s", "q", "a", AT, thinking=["Planning"])
    posts = [j for m, j in log if m == "POST"]
    check("reply is saved without thinking when the thinking insert fails", ok is True and len(posts) == 2 and "thinking" not in posts[1][0] and "thinking" not in posts[1][1])
    db["reject_thinking"] = False
    # nothing works: reported as unsaved, not raised
    db["reject_all"] = True; log.clear()
    ok = await sc.insert_chat_exchange("s", "q", "a", AT, thinking=["Planning"])
    check("a total failure returns False", ok is False)
    check("a 500 is not retried (it may have committed; no duplicate turn)", len([1 for m, _ in log if m == "POST"]) == 1)
    db["reject_all"] = False
    # an unrelated failure is not mistaken for a missing column
    check("unrelated 400 is not a missing column", sc._note_thinking_column_missing(400, "invalid input syntax for type uuid") is False)
    check("unrelated 500 is not a missing column", sc._note_thinking_column_missing(500, "thinking is slow") is False)
    check("a 400 that merely echoes the word 'thinking' is not a missing column", sc._note_thinking_column_missing(400, 'new row violates check constraint; Failing row contains (thinking about it)') is False)

asyncio.run(run())
print("ALL CHECKS PASSED" if not fails else f"{fails} FAILED"); sys.exit(1 if fails else 0)
