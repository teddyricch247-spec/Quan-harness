"""Plain-script test of the in-app chat routes in app/main.py, driven against an
in-memory fake of supabase_client and a fake model call (no network, no DB).

Run: python test_chat_routes.py   (needs the normal backend requirements
installed; dummy env vars are filled in below). The authoring sandbox had no
network, so it was first run against a stubbed FastAPI: run it once against
the real one.
"""
import asyncio, datetime, os, sys
for k in ["SUPABASE_URL","SUPABASE_SERVICE_ROLE_KEY","SUPABASE_ANON_KEY","API_KEY_PEPPER","OPENROUTER_API_KEY","RESEND_API_KEY","FRONTEND_URL"]:
    os.environ.setdefault(k, "x" if k != "FRONTEND_URL" else "http://localhost:3000")
os.environ["SUPABASE_URL"] = "http://x"
from app import main, supabase_client as sc, chat_history as ch
from fastapi import HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FAIL ") + name)
    if not cond: fails += 1

SID = "11111111-1111-4111-8111-111111111111"
SID2 = "22222222-2222-4222-8222-222222222222"
LEGACY = "33333333-3333-4333-8333-333333333333"
USER = {"id": "u1"}
class Req:
    def __init__(self, body): self._b = body
    async def json(self): return self._b
    headers = {}
main._parse_json_body = lambda r: _async(r._b)
async def _async(v): return v

state = {"sessions": {SID: {"id": SID, "model": "kael-beta", "title": "New chat"}, SID2: {"id": SID2, "model": "kael-pro-beta", "title": "x"},
                      LEGACY: {"id": LEGACY, "model": "deepseek-v4-flash", "title": "old"}},
         "messages": {SID: [], SID2: [{"role":"user","content":"orphan"}], LEGACY: []}, "fail_reads": False, "titles": {}}

async def get_chat_session(sid, uid):
    if state["fail_reads"]: raise sc.ChatStoreError("down")
    return dict(state["sessions"][sid]) if sid in state["sessions"] else None
async def list_chat_messages(sid, limit=None, with_thinking=False):
    if state["fail_reads"]: raise sc.ChatStoreError("down")
    rows = [dict(r) for r in state["messages"].get(sid, [])]
    if not with_thinking:
        for r in rows: r.pop("thinking", None)
    return rows[-limit:] if limit else rows
async def list_chat_sessions(uid, limit=100):
    if state["fail_reads"]: raise sc.ChatStoreError("down")
    return [dict(v) for v in state["sessions"].values()]
async def list_chat_images(sid, with_data=False):
    if state["fail_reads"]: raise sc.ChatStoreError("down")
    return []
async def insert_chat_exchange(sid, u, a, at, thinking=None, images=None):
    state["saved_thinking"] = thinking
    if state.get("fail_save"): return False
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    state["messages"][sid] += [{"role":"user","content":u,"created_at":at.isoformat()},
                               {"role":"assistant","content":a,"created_at":now,"thinking":thinking}]; return True
async def touch_chat_session(sid, title=None):
    if title is not None: state["titles"][sid] = title
async def rename_chat_session(sid, uid, title):
    state["titles"][sid] = title; return sid in state["sessions"]
sc.get_chat_session, sc.list_chat_messages, sc.list_chat_sessions = get_chat_session, list_chat_messages, list_chat_sessions
sc.insert_chat_exchange, sc.touch_chat_session, sc.rename_chat_session = insert_chat_exchange, touch_chat_session, rename_chat_session
sc.list_chat_images = list_chat_images

seen = {}
def sse(obj):
    import json
    return ("data: " + json.dumps(obj) + "\n\n").encode()
def think(t): return sse({"choices": [{"delta": {"reasoning_content": t}}]})
def text(t): return sse({"choices": [{"delta": {"content": t}}]})
hold = {}   # lets a test pause a fake reply mid-stream
def make_proxy(mode):
    async def proxy(body, requestor, source="api", on_complete=None):
        seen["messages"] = body["messages"]
        seen["body"] = body
        if mode == "slow":
            async def gen():
                yield think("Looking at the question")
                yield think("Looking at the question")      # filler repeat: stored once
                yield think("Checking the details")
                await hold["gate"].wait()
                yield text("slow ")
                if on_complete: await on_complete("slow reply")
                yield text("reply")
                yield b"data: [DONE]\n\n"
            return StreamingResponse(gen())
        if mode == "error_frame":
            async def gen():
                yield think("Working on it")
                yield sse({"error": {"message": "upstream went away", "type": "server_error"}})
                yield b"data: [DONE]\n\n"
            return StreamingResponse(gen())
        if mode == "fail":
            raise HTTPException(status_code=402, detail={"error": {"message": "no balance"}})
        if mode == "stream":
            async def gen():
                yield text("the ")
                if on_complete: await on_complete("the reply")
                yield b"data: [DONE]\n\n"
            return StreamingResponse(gen())
        if on_complete: await on_complete("json reply")
        return JSONResponse(content={"ok": True})
    return proxy

def set_proxy(mode):
    """Swap the fake reply in for BOTH models (the test conversations use both)."""
    for key in main._PROXY_CHAT:
        main._PROXY_CHAT[key] = make_proxy(mode)

async def code(coro):
    try:
        await coro; return 200
    except HTTPException as e:
        return e.status_code, e.detail["error"].get("code")

async def drain(resp):
    return [c async for c in resp.body_iterator]

async def main_test():
    send = lambda sid, body: main.send_chat_message(sid, Req(body), USER)
    # validation
    check("bad id -> 404", (await code(send("not-a-uuid", {"content": "hi"})))[0] == 404)
    check("blank content -> 400", (await code(send(SID, {"content": "   "})))[0] == 400)
    check("too long -> 400 message_too_long", await code(send(SID, {"content": "x" * 100_001})) == (400, "message_too_long"))
    check("legacy session -> 409", await code(send(LEGACY, {"content": "hi"})) == (409, "session_not_resumable"))
    # failed send leaves nothing behind and releases the gate
    set_proxy("fail")
    check("upstream failure propagates", (await code(send(SID, {"content": "hello"})))[0] == 402)
    check("failed send saved NOTHING", state["messages"][SID] == [] and SID not in state["titles"])
    check("job dropped after failure", main._chat_jobs.get(SID) is None)
    # streaming success: saved together, titled, gate held until stream ends
    set_proxy("stream")
    resp = await send(SID, {"content": "  first   question\nwith lines "})
    check("job held while streaming", main._chat_jobs.get(SID) is not None)
    check("second send while busy -> 409 session_busy", await code(send(SID, {"content": "again"})) == (409, "session_busy"))
    await drain(resp)
    check("job dropped after stream ends", main._chat_jobs.get(SID) is None)
    check("exchange saved in order", [m["role"] for m in state["messages"][SID]] == ["user", "assistant"] and state["messages"][SID][0]["content"].startswith("first"))
    check("title derived once, single line", state["titles"][SID] == "first question with lines")
    # second turn: history sent, no title change
    state["titles"].pop(SID)
    resp = await send(SID, {"content": "follow up"}); await drain(resp)
    check("history sent to model", [m["role"] for m in seen["messages"]] == ["user", "assistant", "user"])
    check("title not re-derived on later turns", SID not in state["titles"])
    # legacy orphan merged
    set_proxy("json")
    await send(SID2, {"content": "new q", "stream": False})
    check("orphaned user msg merged into the new turn", seen["messages"] == [{"role": "user", "content": "orphan\n\nnew q"}])
    check("non-stream leaves no job behind", main._chat_jobs.get(SID2) is None)
    # --- reasoning_effort ---
    set_proxy("stream")
    check("bad reasoning_effort -> 400", (await code(send(SID, {"content": "x", "reasoning_effort": "turbo"})))[0] == 400)
    check("non-string reasoning_effort -> 400", (await code(send(SID, {"content": "x", "reasoning_effort": 3})))[0] == 400)
    check("bad effort did not start a job", main._chat_jobs.get(SID) is None)
    await drain(await send(SID, {"content": "q", "reasoning_effort": " High "}))
    check("valid effort is normalised and passed through", seen["body"].get("reasoning_effort") == "high")
    # each model accepts only its own tiers
    check("kael-beta conversation refuses a z tier -> 400", (await code(send(SID, {"content": "x", "reasoning_effort": "z-low"})))[0] == 400)
    check("kael-pro-beta conversation refuses a standard tier -> 400", (await code(send(SID2, {"content": "x", "reasoning_effort": "low"})))[0] == 400)
    set_proxy("stream")
    await drain(await send(SID2, {"content": "pro q", "reasoning_effort": " Z-High "}))
    check("kael-pro-beta conversation accepts its own tier, normalised and passed through", seen["body"].get("reasoning_effort") == "z-high")
    await drain(await send(SID2, {"content": "pro q2"}))
    check("kael-pro-beta conversation with no effort sends none (the model defaults to z-low)", "reasoning_effort" not in seen["body"] or seen["body"].get("reasoning_effort") in (None, "z-low"))
    check("legacy model values are not resumable", [main._resolve_session_product(v) for v in ("pro", "quan-pro", "quan-4", "ultra", "deepseek-v4-flash", None, 5)] == [None] * 7)
    check("both current models resolve to themselves", [main._resolve_session_product(v) for v in ("kael-beta", "kael-pro-beta")] == ["kael-beta", "kael-pro-beta"])
    await drain(await send(SID, {"content": "q2"}))
    check("no effort sent -> field left out (Kael default applies)", "reasoning_effort" not in seen["body"])

    # --- reload / offline mid-reply ---
    state["messages"][SID] = []
    set_proxy("slow")
    hold["gate"] = asyncio.Event()
    resp = await send(SID, {"content": "long question", "reasoning_effort": "max"})
    it = resp.body_iterator
    first = await it.__anext__()            # the browser reads one chunk ...
    await it.aclose()                        # ... then goes offline
    await asyncio.sleep(0.05)
    check("lock survives the browser going away", await code(send(SID, {"content": "again"})) == (409, "session_busy"))
    d = await main.get_session(SID, USER)
    p = d["pending"]
    check("pending reported after reload", p is not None and p["status"] == "running" and p["content"] == "long question")
    check("pending carries thinking titles, repeats collapsed", p["thinking"] == ["Looking at the question", "Checking the details"])
    check("pending carries the effort used", p["reasoning_effort"] == "max")
    check("nothing saved yet", d["messages"] == [])
    hold["gate"].set()
    await asyncio.gather(*main._pump_tasks)
    check("reply finished and was saved with nobody attached", [m["role"] for m in state["messages"][SID]] == ["user", "assistant"] and state["messages"][SID][1]["content"] == "slow reply")
    check("thinking saved with the reply", state["saved_thinking"] == ["Looking at the question", "Checking the details"])
    d = await main.get_session(SID, USER)
    check("pending gone once saved", d["pending"] is None)
    check("assistant message carries its thinking", d["messages"][1]["thinking"] == ["Looking at the question", "Checking the details"])
    check("user message has no thinking key", "thinking" not in d["messages"][0])
    check("job dropped after a saved reply", main._chat_jobs.get(SID) is None)

    # pending is hidden while the saved exchange and the job briefly coexist
    j = main._chat_jobs.try_start(SID2, "q", datetime.datetime.now(datetime.timezone.utc))
    state["messages"][SID2] = [{"role": "user", "content": "q", "created_at": j.started_at.isoformat()}]
    check("pending hidden when its exchange is already in the history", (await main.get_session(SID2, USER))["pending"] is None)
    state["messages"][SID2] = [{"role": "user", "content": "orphan"}]
    main._chat_jobs.discard(SID2)

    # failed reply: visible after reload, never blocks a new send
    state["messages"][SID] = []
    set_proxy("error_frame")
    await drain(await send(SID, {"content": "will fail"}))
    await asyncio.gather(*main._pump_tasks)
    p = (await main.get_session(SID, USER))["pending"]
    check("failed reply shows as pending error", p is not None and p["status"] == "error" and p["error"]["message"] == "upstream went away" and p["content"] == "will fail")
    check("nothing saved for a failed reply", state["messages"][SID] == [])
    set_proxy("stream")
    await drain(await send(SID, {"content": "second try"}))
    check("a failed job does not block a new send", [m["role"] for m in state["messages"][SID]] == ["user", "assistant"])
    check("new send replaces the failed job", (await main.get_session(SID, USER))["pending"] is None)

    # saved=False (database refused the write) is reported, not swallowed
    state["fail_save"] = True; state["messages"][SID] = []
    await drain(await send(SID, {"content": "unsaved"}))
    await asyncio.gather(*main._pump_tasks)
    p = (await main.get_session(SID, USER))["pending"]
    check("unsaved reply reported as an error", p is not None and p["status"] == "error" and p["error"]["code"] == "not_saved")
    state["fail_save"] = False; main._chat_jobs.discard(SID)

    # deleting a chat drops its job
    j = main._chat_jobs.try_start(SID2, "q", datetime.datetime.now(datetime.timezone.utc))
    async def fake_delete(sid, uid): return True
    sc.delete_chat_session = fake_delete
    await main.delete_session(SID2, USER)
    check("delete drops the job", main._chat_jobs.get(SID2) is None)

    # outage -> 503, model never called
    state["fail_reads"] = True; seen.clear()
    check("history read failure -> 503", await code(send(SID, {"content": "x"})) == (503, "storage_unavailable"))
    check("model NOT called without history", "messages" not in seen)
    check("session lookup failure -> 503 (not 404)", (await code(main.get_session(SID, USER)))[0] == 503)
    check("list failure -> 503", (await code(main.list_sessions(USER)))[0] == 503)
    state["fail_reads"] = False
    # resumable flag + rename
    d = await main.get_session(LEGACY, USER)
    check("GET legacy session says resumable=false", d["resumable"] is False)
    check("GET normal session says resumable=true", (await main.get_session(SID, USER))["resumable"] is True)
    lst = (await main.list_sessions(USER))["sessions"]
    check("list carries resumable per row", {s["id"]: s["resumable"] for s in lst} == {SID: True, SID2: True, LEGACY: False})
    check("rename blank -> 400", (await code(main.rename_session(SID, Req({"title": " \n "}), USER)))[0] == 400)
    r = await main.rename_session(SID, Req({"title": "  my\ntitle  "}), USER)
    check("rename cleans title", r == {"renamed": True, "title": "my title"})
    check("create_session non-string product -> 400", (await main.create_session(Req({"product": ["kael-beta"]}), USER)).status_code == 400)

asyncio.run(main_test())
print("ALL CHECKS PASSED" if not fails else f"{fails} FAILED"); sys.exit(1 if fails else 0)
