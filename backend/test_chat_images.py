"""Plain-script test of pictures in the playground (added 2026-10-11) and of the
admin self-credit change, with no network and no database: chat_history's picture
validation and history building, supabase_client's picture persistence against a
fake httpx client, the /api/chat routes against an in-memory fake store, and
admin.credit_user against a fake billing call.

Run: python test_chat_images.py   (needs the normal backend requirements; dummy
env vars are filled in below). Prints ALL CHECKS PASSED on success.
"""
import asyncio, base64, copy, datetime, json, os
for k in ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_ANON_KEY", "API_KEY_PEPPER", "OPENROUTER_API_KEY", "RESEND_API_KEY", "FRONTEND_URL"]:
    os.environ.setdefault(k, "x" if k != "FRONTEND_URL" else "http://localhost:3000")
os.environ["SUPABASE_URL"] = "http://x"
from decimal import Decimal
from app import main, supabase_client as sc, chat_history as ch, provider_routing as pr, admin, billing, config
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

fails = 0
def check(name, cond):
    global fails
    print(("ok   " if cond else "FAIL ") + name)
    if not cond: fails += 1

# Real, tiny, valid files (1x1).
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
GIF = b"GIF89a\x01\x00\x01\x00\x00\x00\x00;"
WEBP = b"RIFF\x1a\x00\x00\x00WEBPVP8 \x0e\x00\x00\x00\x10\x00\x00\x00"
def b64(raw): return base64.b64encode(raw).decode()
def img(raw=PNG): return {"data": b64(raw), "mime": "image/png"}

# ---------------------------------------------------------------- clean_images
check("no images -> []", ch.clean_images(None) == [] and ch.clean_images([]) == [])
out = ch.clean_images([img(PNG), img(JPEG), img(GIF), img(WEBP)])
check("png/jpeg/gif/webp accepted, mime sniffed from the bytes", [o["mime"] for o in out] == ["image/png", "image/jpeg", "image/gif", "image/webp"])
check("a lying mime is ignored", ch.clean_images([{"data": b64(JPEG), "mime": "image/png"}])[0]["mime"] == "image/jpeg")
check("a data: URL string is accepted", ch.clean_images(["data:image/png;base64," + b64(PNG)])[0]["data"] == b64(PNG))
check("whitespace inside base64 is tolerated", ch.clean_images([{"data": b64(PNG)[:10] + "\n" + b64(PNG)[10:]}])[0]["mime"] == "image/png")
def bad(raw, **kw):
    try:
        ch.clean_images(raw, **kw); return None
    except ValueError as e:
        return str(e)
check("not a list -> error", bad("x") is not None)
check("more than 4 -> error", "up to 4" in (bad([img()] * 5) or ""))
check("empty entry -> error", bad([{"data": ""}]) is not None and bad([{}]) is not None and bad([None]) is not None)
check("bad base64 -> error", "base64" in (bad([{"data": "!!!not-base64!!!"}]) or ""))
check("not an image (a text file) -> error", "Only JPEG" in (bad([{"data": b64(b"hello world, not a picture")}]) or ""))
check("svg is refused", "Only JPEG" in (bad([{"data": b64(b"<svg xmlns='http://www.w3.org/2000/svg'/>")}]) or ""))
big = b"\x89PNG\r\n\x1a\n" + b"0" * (ch.MAX_IMAGE_BYTES + 10)
check("one picture over the size limit -> error", "too large" in (bad([{"data": b64(big)}]) or ""))
mid = b"\x89PNG\r\n\x1a\n" + b"0" * (2_500_000)
check("pictures over the per-message total -> error", "in total" in (bad([{"data": b64(mid)}] * 4) or ""))
check("data: URL without base64 -> error", bad(["data:image/png,abc"]) is not None)

# --------------------------------------------------------- build_model_messages
m = ch.build_model_messages([], "hi")
check("text only is still a plain string", m == [{"role": "user", "content": "hi"}])
imgs = ch.clean_images([img(PNG)])
m = ch.build_model_messages([], "what is this?", new_images=imgs)
parts = m[0]["content"]
check("a message with a picture is a parts list: text first, then image_url", isinstance(parts, list) and parts[0] == {"type": "text", "text": "what is this?"} and parts[1]["type"] == "image_url" and parts[1]["image_url"]["url"].startswith("data:image/png;base64,"))
m = ch.build_model_messages([], "", new_images=imgs)
check("a picture-only message has no empty text part", m[0]["content"] == [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + imgs[0]["data"]}}])
stored = [{"role": "user", "content": "look", "images": [{"mime": "image/png", "data": imgs[0]["data"]}]}, {"role": "assistant", "content": "a pixel"}]
m = ch.build_model_messages(stored, "and now?")
check("earlier pictures stay in the history", isinstance(m[0]["content"], list) and m[1] == {"role": "assistant", "content": "a pixel"} and m[2] == {"role": "user", "content": "and now?"})
m = ch.build_model_messages([{"role": "user", "content": "", "images": [{"mime": "image/png", "data": "AAAA"}]}], "q")
check("a stored picture-only row is kept and merged with the next user turn", len(m) == 1 and isinstance(m[0]["content"], list) and m[0]["content"][-1] == {"type": "text", "text": "q"} or len(m[0]["content"]) == 2)
many = [{"role": "user" if i % 2 == 0 else "assistant", "content": "x", "images": ([{"mime": "image/png", "data": "AAAA"}] if i % 2 == 0 else [])} for i in range(20)]
m = ch.build_model_messages(many, "last", max_chars=30_000)
check("pictures weigh against the history budget (oldest dropped first)", len(m) < 21 and m[-1]["content"] == "last")
check("assistant rows never carry pictures", ch.build_model_messages([{"role": "assistant", "content": "a", "images": [{"mime": "image/png", "data": "AAAA"}]}, {"role": "user", "content": "u"}], "n")[0]["role"] == "user")
check("auto_title: picture-only first message", ch.auto_title("", has_images=True) == ch.IMAGE_ONLY_TITLE and ch.auto_title("hello there", has_images=True) == "hello there" and ch.auto_title("") == ch.DEFAULT_TITLE)

# ------------------------------------------------------- the pipeline's inputs
from app import response_api as ra
items = ra.messages_to_input(ch.build_model_messages([], "what is this?", new_images=imgs))
prep = ra.prepare_input_items(items, datetime.datetime.now(datetime.timezone.utc), "abcd1234")
check("prepare_input_items passes a user picture through untouched", prep[0] == items[0] and prep[-1]["role"] == "system")
check("text_chars counts only the text of a parts list", ra.text_chars(items[0]["content"]) == len("what is this?"))
check("last_user_text reads the text of a parts list", sc.last_user_text(items) == "what is this?")
check("last_user_text of a picture-only message is None, not a crash", sc.last_user_text(ra.messages_to_input(ch.build_model_messages([], "", new_images=imgs))) is None)
a1 = pr.derive_session_id("u1", ra.messages_to_input(ch.build_model_messages([], "", new_images=ch.clean_images([img(PNG)]))))
a2 = pr.derive_session_id("u1", ra.messages_to_input(ch.build_model_messages([], "", new_images=ch.clean_images([img(JPEG)]))))
a3 = pr.derive_session_id("u1", ra.messages_to_input(ch.build_model_messages([], "", new_images=ch.clean_images([img(PNG)]))))
check("picture-only openers anchor the session id on the picture (same picture same id, different picture different id)", a1 == a3 and a1 != a2)
check("a text opener's session id is unchanged by this", pr.derive_session_id("u1", [{"role": "user", "content": "hi"}]) == pr.derive_session_id("u1", [{"role": "user", "content": [{"type": "text", "text": "hi"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}]))

# -------------------------------------------------- supabase_client persistence
class Resp:
    def __init__(self, status, body=None, text=""):
        self.status_code, self._body, self.text = status, body, text
    def json(self): return self._body
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")
log = []
db = {"images_table": True, "reject_images": False}
class FakeClient:
    def __init__(self, *a, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def post(self, url, headers=None, json=None, **k):
        json = copy.deepcopy(json)
        log.append(("POST", url.rsplit("/", 1)[-1], json))
        if url.endswith("chat_message_images"):
            if not db["images_table"]:
                return Resp(404, None, "PGRST205 Could not find the table 'public.chat_message_images' in the schema cache")
            if db["reject_images"]: return Resp(500, None, "boom")
            return Resp(201)
        if isinstance(json, list) and len({tuple(sorted(r)) for r in json}) > 1:
            return Resp(400, None, "All object keys must match")
        return Resp(201)
    async def get(self, url, headers=None, params=None, **k):
        log.append(("GET", url.rsplit("/", 1)[-1], dict(params)))
        if url.endswith("chat_message_images"):
            if not db["images_table"]:
                return Resp(404, None, "PGRST205 Could not find the table 'public.chat_message_images' in the schema cache")
            return Resp(200, [{"id": "i1", "message_id": "m1", "position": 0, "mime": "image/png"}])
        return Resp(200, [])
sc.httpx.AsyncClient = FakeClient
AT = datetime.datetime.now(datetime.timezone.utc)

async def persistence():
    ok = await sc.insert_chat_exchange("s", "q", "a", AT, images=imgs)
    posts = [(u, j) for m_, u, j in log if m_ == "POST"]
    check("exchange with pictures: two requests, messages first then pictures", ok is True and [u for u, _ in posts] == ["chat_messages", "chat_message_images"])
    msg_rows, img_rows = posts[0][1], posts[1][1]
    check("both message rows carry the same keys (PostgREST bulk rule) and an id", {tuple(sorted(r)) for r in msg_rows} == {tuple(sorted(msg_rows[0]))} and "id" in msg_rows[0])
    check("the picture row points at the user message, in order", img_rows[0]["message_id"] == msg_rows[0]["id"] and img_rows[0]["position"] == 0 and img_rows[0]["mime"] == "image/png" and img_rows[0]["session_id"] == "s" and img_rows[0]["byte_size"] == len(PNG))
    log.clear()
    await sc.insert_chat_exchange("s", "q", "a", AT)
    check("no pictures: one request, no ids added (as before)", [u for _, u, _ in log] == ["chat_messages"] and "id" not in log[0][2][0])
    log.clear()
    db["reject_images"] = True
    ok = await sc.insert_chat_exchange("s", "q", "a", AT, images=imgs)
    check("a failed picture save never fails the exchange", ok is True)
    db["reject_images"] = False
    log.clear()
    db["images_table"] = False
    ok = await sc.insert_chat_exchange("s", "q", "a", AT, images=imgs)
    check("migration 0015 not applied: the exchange is still saved", ok is True)
    log.clear()
    ok = await sc.insert_chat_exchange("s", "q", "a", AT, images=imgs)
    check("... and the table is not asked again for a while", ok is True and [u for _, u, _ in log] == ["chat_messages"])
    check("... reads return [] without a request", (await sc.list_chat_images("s")) == [] and (await sc.get_chat_image("s", "i1")) is None)
    sc._images_table_retry_at = 0.0
    db["images_table"] = True
    log.clear()
    rows = await sc.list_chat_images("s")
    check("list_chat_images without data does not select data", rows and "data" not in log[0][2]["select"])
    log.clear()
    await sc.list_chat_images("s", with_data=True)
    check("with_data selects it", "data" in log[0][2]["select"])
    log.clear()
    await sc.list_chat_messages("s", limit=5)
    check("message reads now include the row id", log[0][2]["select"].startswith("id,"))
asyncio.run(persistence())

# -------------------------------------------------------------------- the routes
SID = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
USER = {"id": "u1"}
class Req:
    def __init__(self, body): self._b = body
    async def json(self): return self._b
async def _async(v): return v
main._parse_json_body = lambda r: _async(r._b)

store = {"messages": [], "images": [], "titles": {}, "saved_images": None, "fail_image_reads": False}
async def get_chat_session(sid, uid):
    return {"id": sid, "model": "kael-beta", "title": "t"} if sid in (SID, OTHER) else None
async def list_chat_messages(sid, limit=None, with_thinking=False):
    return [dict(r) for r in store["messages"]]
async def list_chat_images(sid, with_data=False):
    if store["fail_image_reads"]: raise sc.ChatStoreError("down")
    return [{k: v for k, v in r.items() if with_data or k != "data"} for r in store["images"]]
async def get_chat_image(sid, iid):
    for r in store["images"]:
        if r["id"] == iid: return {"mime": r["mime"], "data": r["data"]}
    return None
async def insert_chat_exchange(sid, u, a, at, thinking=None, images=None):
    store["saved_images"] = images
    return True
async def touch_chat_session(sid, title=None):
    store["titles"][sid] = title
for name, fn in dict(get_chat_session=get_chat_session, list_chat_messages=list_chat_messages, list_chat_images=list_chat_images,
                     get_chat_image=get_chat_image, insert_chat_exchange=insert_chat_exchange, touch_chat_session=touch_chat_session).items():
    setattr(sc, name, fn)

seen = {}
def sse(obj): return ("data: " + json.dumps(obj) + "\n\n").encode()
def make_proxy():
    async def proxy(body, requestor, source="api", on_complete=None):
        seen["messages"] = body["messages"]
        async def gen():
            yield sse({"choices": [{"delta": {"content": "ok"}}]})
            if on_complete: await on_complete("a reply")
            yield b"data: [DONE]\n\n"
        return StreamingResponse(gen())
    return proxy
for key in main._PROXY_CHAT: main._PROXY_CHAT[key] = make_proxy()

async def drain(resp): return [c async for c in resp.body_iterator]
async def code(coro):
    try:
        await coro; return 200, None
    except HTTPException as e:
        return e.status_code, e.detail["error"].get("code")

async def routes():
    send = lambda body, sid=SID: main.send_chat_message(sid, Req(body), USER)
    check("no text and no pictures -> 400", (await code(send({"content": "  "}))) == (400, None))
    check("bad picture -> 400 invalid_images", (await code(send({"content": "x", "images": [{"data": b64(b"nope")}]}))) == (400, "invalid_images"))
    check("too many pictures -> 400", (await code(send({"content": "x", "images": [img()] * 5}))) == (400, "invalid_images"))

    resp = await send({"content": "what is this?", "images": [img()]})
    await drain(resp)
    last = seen["messages"][-1]
    check("the model gets text + image_url parts", isinstance(last["content"], list) and last["content"][0]["text"] == "what is this?" and last["content"][1]["type"] == "image_url")
    check("the pictures are handed to the saver, with the exchange", store["saved_images"] and store["saved_images"][0]["mime"] == "image/png")
    check("a text-first conversation is titled from the text", store["titles"][SID] == "what is this?")

    store["titles"].clear()
    resp = await send({"images": [img(JPEG)]})
    await drain(resp)
    check("a picture-only message is accepted (content may be absent)", seen["messages"][-1]["content"][0]["type"] == "image_url")
    check("... and titled 'Image' when it opens the conversation", store["titles"][SID] == ch.IMAGE_ONLY_TITLE)

    # history: an earlier picture comes back with the next turn
    store["messages"] = [{"id": "m1", "role": "user", "content": "look", "created_at": "2026-10-11T10:00:00+00:00"},
                         {"id": "m2", "role": "assistant", "content": "a pixel", "created_at": "2026-10-11T10:00:01+00:00"}]
    pic_id = "33333333-3333-4333-8333-333333333333"
    store["images"] = [{"id": pic_id, "message_id": "m1", "position": 0, "mime": "image/png", "data": b64(PNG)}]
    resp = await send({"content": "and now?"})
    await drain(resp)
    msgs = seen["messages"]
    check("the earlier picture is sent again with the next turn", isinstance(msgs[0]["content"], list) and msgs[0]["content"][0]["text"] == "look" and msgs[0]["content"][1]["type"] == "image_url" and msgs[-1]["content"] == "and now?")

    # per-conversation cap
    store["images"] = [{"id": f"{i:08d}-3333-4333-8333-333333333333", "message_id": "m1", "position": i, "mime": "image/png", "data": b64(PNG)} for i in range(19)]
    check("19 stored + 2 new -> 400 too_many_images", (await code(send({"content": "x", "images": [img(), img()]}))) == (400, "too_many_images"))
    check("... and the failed send leaves no job behind (the chat is not locked)", main._chat_jobs.get(SID) is None)
    resp = await send({"content": "x", "images": [img()]})
    await drain(resp)
    check("19 stored + 1 new is allowed", seen["messages"][-1]["content"][1]["type"] == "image_url")
    # per-conversation size cap: few pictures, but too many bytes
    big = ch.MAX_CONVERSATION_IMAGE_BYTES - 10
    store["images"] = [{"id": pic_id, "message_id": "m1", "position": 0, "mime": "image/png", "byte_size": big, "data": b64(PNG)}]
    check("stored bytes near the cap + a new picture -> 400 too_many_images", (await code(send({"content": "x", "images": [img()]}))) == (400, "too_many_images"))
    resp = await send({"content": "x"})
    await drain(resp)
    check("... a text-only message is still fine", seen["messages"][-1]["content"] == "x")
    store["images"] = [{"id": pic_id, "message_id": "m1", "position": 0, "mime": "image/png", "data": b64(PNG)}]

    store["fail_image_reads"] = True
    check("a failed picture read refuses the send (503) instead of answering without them", (await code(send({"content": "x"})))[0] == 503)
    store["fail_image_reads"] = False

    # a model that cannot read pictures
    config.PRODUCTS["kael-beta"]["supports_images"] = False
    check("a model without picture support -> 400 images_not_supported", (await code(send({"content": "x", "images": [img()]}))) == (400, "images_not_supported"))
    check("... but plain text is unaffected", (await code(send({"content": "x"}))) == (200, None))
    config.PRODUCTS["kael-beta"]["supports_images"] = True
    main._chat_jobs.discard(SID)

    # reading
    detail = await main.get_session(SID, USER)
    user_row = [m for m in detail["messages"] if m["id"] == "m1"][0]
    asst_row = [m for m in detail["messages"] if m["id"] == "m2"][0]
    check("GET session: the user message lists {id, mime} per picture, never the bytes", user_row["images"] == [{"id": pic_id, "mime": "image/png"}] and "images" not in asst_row)
    store["fail_image_reads"] = True
    detail = await main.get_session(SID, USER)
    check("GET session still opens if the pictures cannot be read", len(detail["messages"]) == 2 and "images" not in detail["messages"][0])
    store["fail_image_reads"] = False

    r = await main.get_session_image(SID, pic_id, USER)
    check("GET image: the bytes, with the right type", r.body == PNG and r.media_type == "image/png")
    check("GET image: private, immutable cache, nosniff", "private" in r.headers["cache-control"] and "immutable" in r.headers["cache-control"] and r.headers["x-content-type-options"] == "nosniff")
    check("GET image: malformed id -> 404", (await code(main.get_session_image(SID, "nope", USER)))[0] == 404)
    check("GET image: unknown id -> 404", (await code(main.get_session_image(SID, "44444444-4444-4444-8444-444444444444", USER)))[0] == 404)
    check("GET image: unknown conversation -> 404", (await code(main.get_session_image("55555555-5555-4555-8555-555555555555", pic_id, USER)))[0] == 404)

    # a reply still running shows how many pictures it was sent
    j = main._chat_jobs.try_start(SID, "q", AT, None, image_count=2)
    check("pending view carries image_count", j.view()["image_count"] == 2)
    main._chat_jobs.discard(SID)
asyncio.run(routes())

# ------------------------------------------------------------- admin credit
# Updated 2026-10-13: the deposit-match promotion was removed, so billing.admin_credit_account
# takes (user_id, amount, description) with no is_deposit flag, and ledger descriptions
# never contain an email address (customers can read them through GET /api/billing).
calls = []
async def fake_credit(user_id, amount, description):
    calls.append((user_id, amount, description)); return Decimal("1000.5")
billing.admin_credit_account = fake_credit
async def admin_tests():
    r = await admin.credit_user("admin1", 250, "boss@example.com", admin_id="admin1")
    check("self-credit: works, flagged, described as such, no email in the description", r["self_credit"] is True and r["credited_usd"] == "250" and r["new_balance_usd"] == "1000.5" and calls[-1][2] == "Admin self-credit")
    r = await admin.credit_user("user9", 50, "boss@example.com", admin_id="admin1")
    check("crediting someone else: not a self-credit, no email in the description", r["self_credit"] is False and calls[-1][2] == "Admin credit adjustment" and "@" not in calls[-1][2])
    r = await admin.credit_user("admin1", 123456789.5, "boss@example.com", admin_id="admin1")
    check("a large amount is accepted", r["credited_usd"] == "123456789.5")
    r = await admin.credit_user("admin1", 0.01, None, admin_id="admin1")
    check("a small amount and no email is accepted", calls[-1][2] == "Admin self-credit")
    async def bad(amount):
        try:
            await admin.credit_user("admin1", amount, "e", admin_id="admin1"); return None
        except HTTPException as e:
            return e.status_code
    check("zero, negative, bool, string, NaN are 400", [await bad(x) for x in (0, -5, True, "50", float("nan"))] == [400] * 5)
    check("above the balance column's range is a clear 400", await bad(1_000_000_000) == 400 and await bad(float("inf")) == 400)
    check("below the balance's precision is a 400", await bad(0.000001) == 400)
    before = len(calls)
    await bad(0)
    check("a refused credit never reaches billing", len(calls) == before)
    r = await admin.credit_user("admin1", 5, "e")
    check("without admin_id nothing is treated as a self-credit", r["self_credit"] is False)
    check("no ledger description ever carries an email address", all("@" not in c[2] for c in calls))
asyncio.run(admin_tests())

print("ALL CHECKS PASSED" if not fails else f"{fails} CHECK(S) FAILED")
raise SystemExit(1 if fails else 0)
