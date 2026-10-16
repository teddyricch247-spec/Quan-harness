"""Privacy + public-naming rules for Kael (added 2026-10-06).

Two owner rules, both tested here against the REAL supabase_client and the
REAL pipeline (only the network is faked):

  1. Text from real API callers is NEVER stored. Only the in-app Playground
     and Chat (source="app_chat") keep prompt/answer text. For API traffic
     the database gets counts, timings and status — nothing readable.
  2. Customers never see upstream model ids. The dashboard's request table
     always says "kael-beta", whatever is stored in usage_logs.

How the proof works: a fake httpx records EVERY body the app sends to
Supabase, then the test searches those bodies for the secret prompt and
answer strings. Offline — no fastapi/httpx install needed.

Run:  python test_api_privacy.py
"""

import asyncio
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["SUPABASE_URL"] = "https://sb.test"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "service-role-test"
os.environ.setdefault("OPENROUTER_API_KEY", "or-test")

SB = "https://sb.test"

# ---------------------------------------------------------------------
# Offline stand-ins for fastapi and httpx
# ---------------------------------------------------------------------
fa = types.ModuleType("fastapi")


class HTTPException(Exception):
    def __init__(self, status_code, detail=None, headers=None):
        self.status_code, self.detail = status_code, detail
        super().__init__(f"{status_code}: {detail}")


fa.HTTPException = HTTPException
fa.Request = type("Request", (), {})
fa.Header = lambda default=None, alias=None: default
fa.Depends = lambda dependency=None: dependency
sys.modules["fastapi"] = fa
fr = types.ModuleType("fastapi.responses")


class StreamingResponse:
    def __init__(self, content=None, *a, **k):
        self.body_iterator = content


fr.StreamingResponse = StreamingResponse
sys.modules["fastapi.responses"] = fr

hx = types.ModuleType("httpx")


class TimeoutException(Exception):
    pass


class HTTPError(Exception):
    pass


class ConnectTimeout(TimeoutException):
    pass


class ConnectError(HTTPError):
    pass


class HTTPStatusError(HTTPError):
    def __init__(self, m, response=None):
        super().__init__(m)
        self.response = response


hx.TimeoutException, hx.HTTPError = TimeoutException, HTTPError
hx.ConnectTimeout, hx.ConnectError, hx.HTTPStatusError = ConnectTimeout, ConnectError, HTTPStatusError
hx.Timeout = lambda *a, **k: None

UPSTREAM_QUEUE: list = []   # replies for calls to the model provider
SB_SENT: list = []          # (method, url, json_body) for every Supabase call
SB_REPLY: dict = {}         # url-suffix -> (status, payload) override
_trace_counter = [0]


class Resp:
    def __init__(self, kind, status, payload):
        self.status_code, self._k, self._p = status, kind, payload
        self.text = (json.dumps(payload) if kind == "json" else "\n".join(payload))[:500]

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise HTTPStatusError("err", response=self)

    async def aread(self):
        return self.text.encode()

    async def aiter_lines(self):
        for line in (self._p if self._k == "lines" else []):
            yield line


class CM:
    def __init__(self, r):
        self.r = r

    async def __aenter__(self):
        return self.r

    async def __aexit__(self, *a):
        return False


def _sb(method, url, json_body, params=None):
    SB_SENT.append((method, url, json_body))
    if method == "POST" and url.endswith("/chat_debug_traces"):
        _trace_counter[0] += 1
        return Resp("json", 201, [{"id": f"trace-{_trace_counter[0]}"}])
    if method == "GET" and url.endswith("/usage_logs"):
        return Resp("json", 200, SB_REPLY["usage_rows"])
    return Resp("json", 201, [])


class Client:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def _go(self, method, url, json_body=None, params=None):
        if url.startswith(SB):
            return _sb(method, url, json_body, params)
        x = UPSTREAM_QUEUE.pop(0)
        if isinstance(x, Exception):
            raise x
        return Resp(*x)

    async def post(self, url, headers=None, json=None, **k):
        return await self._go("POST", url, json)

    async def patch(self, url, headers=None, json=None, params=None, **k):
        return await self._go("PATCH", url, json, params)

    async def get(self, url, headers=None, params=None, **k):
        return await self._go("GET", url, None, params)

    def stream(self, method, url, headers=None, json=None, **k):
        if url.startswith(SB):
            raise AssertionError("stream() to Supabase")
        x = UPSTREAM_QUEUE.pop(0)
        if isinstance(x, Exception):
            raise x
        return CM(Resp(*x))


hx.AsyncClient = Client
sys.modules["httpx"] = hx

from app import billing, supabase_client as sbc, two_pass_pipeline as tpp  # noqa: E402

failures: list = []


def check(label, got, expected):
    if got != expected:
        failures.append(f"FAIL {label}\n  got:      {got!r}\n  expected: {expected!r}")
    else:
        print(f"ok   {label}")


# billing is not what is under test here (and does not store text)
async def _balance_ok(uid):
    return None


async def _no_charge(*a, **k):
    return None


billing.check_balance_or_raise = _balance_ok
billing.charge_for_request = _no_charge
tpp.secrets.token_hex = lambda n=8: "testboundary123"   # so the fake draft's tag parses

SECRET_PROMPT = "MY-SECRET-PROMPT-7731 please summarise my medical results"
SECRET_DRAFT = "SECRET-DRAFT-TEXT-5520 here is a first attempt"
SECRET_ANSWER = "SECRET-FINAL-ANSWER-9184 here is the polished reply"
TAG = "<task_difficulty_testboundary123>HARD</task_difficulty_testboundary123>"


def reset():
    SB_SENT.clear()
    UPSTREAM_QUEUE.clear()
    SB_REPLY.clear()


def sent_text() -> str:
    return json.dumps([b for (_m, _u, b) in SB_SENT], default=str)


def trace_bodies():
    return [(m, b) for (m, u, b) in SB_SENT if "/chat_debug_traces" in u]


def cc_json(text):
    return ("json", 200, {
        "id": "x", "model": "upstream/model",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    })


def sse(text):
    def ev(d):
        return "data: " + json.dumps(d)
    return ("lines", 200, [
        ev({"id": "x", "model": "upstream/model", "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}),
        ev({"id": "x", "model": "upstream/model", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}),
        ev({"id": "x", "model": "upstream/model", "choices": [],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}),
        "data: [DONE]",
    ])


def passes():
    mk = lambda m: tpp.PassConfig(provider="openrouter", base_url="https://fake.test", api_key="k", model=m,
                                  reasoning_effort="low", max_output_tokens=100)
    return mk("deepseek/deepseek-v4.1-flash"), mk("deepseek/deepseek-v4.1-flash")


async def run_request(source: str, stream: bool):
    reset()
    draft, critic = passes()
    if stream:
        UPSTREAM_QUEUE.extend([sse(TAG + SECRET_DRAFT), sse(SECRET_ANSWER)])
    else:
        UPSTREAM_QUEUE.extend([cc_json(TAG + SECRET_DRAFT), cc_json(SECRET_ANSWER)])
    tpp.last_user_text = sbc.last_user_text  # the REAL function, not a fake
    result = await tpp.run_pipeline(
        product="kael-beta", slug="kael-beta", system_identity="id", draft=draft, critic=critic,
        input_items=[{"role": "user", "content": SECRET_PROMPT}], tools=None,
        client_wants_stream=stream, caller_shape="chat_completions",
        requestor={"user_id": "user-1"}, source=source,
    )
    if stream:
        async for _ in result.body_iterator:
            pass
        await asyncio.sleep(0.2)
        pending = [t for t in getattr(tpp, "_background_tasks", set()) if not t.done()]
        if pending:
            await asyncio.wait(pending, timeout=5)
    return result


async def main():
    # ---- Group 1: the storage rule itself --------------------------------
    reset()
    tid = await sbc.start_chat_trace(source="api", product="kael-beta", last_user_message=SECRET_PROMPT, status="started", user_id="u")
    await sbc.update_chat_trace(tid, status="done", content_preview=SECRET_ANSWER, draft_content_preview=SECRET_DRAFT, content_char_count=42)
    check("api trace: prompt never sent to the database", SECRET_PROMPT in sent_text(), False)
    check("api trace: answer never sent to the database", SECRET_ANSWER in sent_text(), False)
    check("api trace: draft never sent to the database", SECRET_DRAFT in sent_text(), False)
    m, last = trace_bodies()[-1]
    check("api trace: counts/status are still recorded", (last.get("status"), last.get("content_char_count")), ("done", 42))

    reset()
    tid = await sbc.start_chat_trace(source="app_chat", product="kael-beta", last_user_message=SECRET_PROMPT, status="started", user_id="u")
    await sbc.update_chat_trace(tid, status="done", content_preview=SECRET_ANSWER, draft_content_preview=SECRET_DRAFT)
    check("app_chat trace: prompt IS kept (Playground/Chat)", SECRET_PROMPT in sent_text(), True)
    check("app_chat trace: answer IS kept", SECRET_ANSWER in sent_text(), True)

    reset()
    tid = await sbc.start_chat_trace(source="some_future_source", product="kael-beta", last_user_message=SECRET_PROMPT, status="started")
    await sbc.update_chat_trace(tid, content_preview=SECRET_ANSWER)
    check("unknown source defaults to NOT storing text", (SECRET_PROMPT in sent_text(), SECRET_ANSWER in sent_text()), (False, False))

    reset()
    await sbc.update_chat_trace("trace-never-opened", content_preview=SECRET_ANSWER, status="done")
    check("update on an unknown trace id never stores text", SECRET_ANSWER in sent_text(), False)

    # ---- Group 2: whole requests through the real pipeline ---------------
    for stream in (False, True):
        kind = "streaming" if stream else "non-streaming"
        await run_request("api", stream)
        blob = sent_text()
        check(f"API {kind}: NOTHING sent to Supabase contains the prompt", SECRET_PROMPT in blob or "SECRET-PROMPT-7731" in blob, False)
        check(f"API {kind}: nothing contains the draft", "SECRET-DRAFT-TEXT-5520" in blob, False)
        check(f"API {kind}: nothing contains the answer", "SECRET-FINAL-ANSWER-9184" in blob, False)
        check(f"API {kind}: usage was still logged (token counts only)", any("/usage_logs" in u for (_m, u, _b) in SB_SENT), True)
        check(f"API {kind}: a trace row was still written", len(trace_bodies()) >= 2, True)

        await run_request("app_chat", stream)
        blob = sent_text()
        check(f"app_chat {kind}: prompt IS kept for Playground/Chat", "SECRET-PROMPT-7731" in blob, True)
        check(f"app_chat {kind}: answer IS kept", "SECRET-FINAL-ANSWER-9184" in blob, True)

    # ---- Group 3: dashboard model name -----------------------------------
    reset()
    base = {"id": "1", "created_at": "2026-10-06T10:00:00+00:00", "product": "kael-beta", "api_key_label": "k",
            "prompt_tokens": 10, "completion_tokens": 5, "cached_tokens": 0, "total_tokens": 15,
            "status": "success", "latency_ms": 100}
    SB_REPLY["usage_rows"] = [
        {**base, "id": "1", "model": "deepseek/deepseek-v4.1-flash+deepseek/deepseek-v4.1-flash"},
        {**base, "id": "2", "model": "z-ai/glm-5.3-flash"},
        {**base, "id": "3", "model": "z-ai/glm-5.3-flash+deepseek/deepseek-v4.1-flash"},
        {**base, "id": "4", "model": None},
        {**base, "id": "5", "model": "deepseek-v4-flash", "product": "ultra"},
        {**base, "id": "6", "model": "deepseek/deepseek-v4.1-flash+deepseek/deepseek-v4.1-flash", "product": "kael-pro-beta"},
    ]
    stats = await sbc.fetch_stats("user-1")
    check("dashboard: each row shows its own model's public name (an unknown old product shows the default)", [r["model"] for r in stats["recent"]], ["kael-beta"] * 5 + ["kael-pro-beta"])
    check("dashboard: a retired product falls back to the generic route; a current model gets its own", [r["endpoint"] for r in stats["recent"]][-2:], ["/v1/chat/completions", "/kael-pro-beta/v1/chat/completions"])
    out = json.dumps(stats).lower()
    check("dashboard: no vendor or upstream model name anywhere in the payload",
          [w for w in ("deepseek", "glm", "z-ai", "openrouter", "relace", "baseten") if w in out], [])


if __name__ == "__main__":
    asyncio.run(main())
    if failures:
        print("\n" + "\n".join(failures))
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")
