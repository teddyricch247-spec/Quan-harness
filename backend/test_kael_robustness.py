"""Kael robustness fixes (added 2026-10-06). Offline; reuses the fake network
from test_api_privacy.py.

  1. Upstream errors: callers never see the upstream body (host names, model
     ids, account links) and never get the upstream account's 401/402/403 as
     if it were their own; the operator still gets a loud log line.
  2. A failed balance deduction is logged (CHARGE_FAILED), not swallowed.
  3. Non-streaming Chat Completions keeps text written next to a tool call.
  4. Malformed input is a 400, not a 500: a non-object "reasoning" is tested
     here. The non-string "model" check lives in main.py's route functions,
     which need the real FastAPI to import (not available offline) — covered
     in test_chat_routes.py's environment instead.

Run:  python test_kael_robustness.py
"""
import asyncio
import contextlib
import io
import json
import sys

import test_api_privacy as P
from test_api_privacy import HTTPException, tpp, billing
from app import provider_routing as pr, response_api as ra, kael_pipeline as kp, config

failures = []


def check(label, got, expected):
    if got != expected:
        failures.append(f"FAIL {label}\n  got:      {got!r}\n  expected: {expected!r}")
    else:
        print(f"ok   {label}")


VENDOR_WORDS = ("deepseek", "glm", "z-ai", "openrouter", "together", "relace", "baseten", "provider returned")


async def pipeline_error(status, body, stream):
    P.reset()
    d, c = P.passes()
    P.UPSTREAM_QUEUE.append(("json", status, body))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            res = await tpp.run_pipeline(
                product="kael-beta", slug="kael-beta", system_identity="id", draft=d, critic=c,
                input_items=[{"role": "user", "content": "hi"}], tools=None, client_wants_stream=stream,
                caller_shape="chat_completions", requestor={"user_id": "u1"})
            if stream:
                out = ""
                async for chunk in res.body_iterator:
                    out += chunk if isinstance(chunk, str) else chunk.decode()
                await asyncio.sleep(0.1)
                return None, out, buf.getvalue()
        except HTTPException as e:
            return e.status_code, json.dumps(e.detail), buf.getvalue()
    return "no-error", "", buf.getvalue()



def prod_passes():
    """PassConfigs WITH the real routing objects from config — the bare
    passes() in test_api_privacy has none, which silently disables the
    backup-host retry and hid a bug once (2026-10-06)."""
    info = config.PRODUCTS["kael-beta"]
    mk = lambda m, r: tpp.PassConfig(provider="openrouter", base_url="https://fake.test", api_key="k", model=m,
                                     reasoning_effort="low", max_output_tokens=100, provider_routing=r)
    return mk(info["draft_model"], info.get("draft_provider_routing")), mk(info["critic_model"], info.get("critic_provider_routing"))


async def upstream_calls_for(status, stream):
    P.reset()
    d, c = prod_passes()
    reply = ("json", status, {"error": {"message": "x", "code": status}})
    P.UPSTREAM_QUEUE.extend([reply] * 4)
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            res = await tpp.run_pipeline(
                product="kael-beta", slug="kael-beta", system_identity="id", draft=d, critic=c,
                input_items=[{"role": "user", "content": "hi"}], tools=None, client_wants_stream=stream,
                caller_shape="chat_completions", requestor={"user_id": "u1"})
            if stream:
                async for _ in res.body_iterator:
                    pass
                await asyncio.sleep(0.1)
        except HTTPException:
            pass
    return 4 - len(P.UPSTREAM_QUEUE)



SECRET = "MY-SECRET-PROMPT-7731"


async def echoed_error_run(status, body, stream):
    """One API request whose upstream error QUOTES the prompt. Returns
    (everything sent to Supabase as text, everything printed, caller-visible text)."""
    P.reset()
    d, c = P.passes()
    P.UPSTREAM_QUEUE.append(("json", status, body))
    buf = io.StringIO()
    shown = ""
    with contextlib.redirect_stdout(buf):
        try:
            res = await tpp.run_pipeline(
                product="kael-beta", slug="kael-beta", system_identity="id", draft=d, critic=c,
                input_items=[{"role": "user", "content": f"{SECRET} please summarise my medical results"}], tools=None,
                client_wants_stream=stream, caller_shape="chat_completions",
                requestor={"user_id": "u1"}, source="api")
            if stream:
                async for chunk in res.body_iterator:
                    shown += chunk if isinstance(chunk, str) else chunk.decode()
                await asyncio.sleep(0.1)
        except HTTPException as e:
            shown = json.dumps(e.detail)
    db = json.dumps([b for (_m, _u, b) in P.SB_SENT], default=str)
    return db, buf.getvalue(), shown


async def main():
    # ---- 1. upstream error mapping (pure) ---------------------------------
    expect = {400: 400, 422: 400, 413: 413, 429: 429, 408: 504, 504: 504, 401: 503, 402: 503, 403: 503, 500: 502, 502: 502, 409: 502}
    for up, want in expect.items():
        status, payload = pr.client_error_for_upstream_status(up)
        check(f"upstream {up} -> caller {want}", status, want)
        check(f"upstream {up}: envelope has message/type/code only", sorted(payload["error"]), ["code", "message", "type"])
        check(f"upstream {up}: no vendor words", [w for w in VENDOR_WORDS if w in json.dumps(payload).lower()], [])

    # ---- 1b. through the real pipeline, both transports -------------------
    hostile = {
        429: {"error": {"message": "Provider returned error", "code": 429, "metadata": {"raw": "deepseek/deepseek-v4.1-flash is rate-limited", "provider_name": "Together"}}},
        402: {"error": {"message": "Insufficient credits. Add more using https://openrouter.ai/settings/credits", "code": 402}},
        401: {"error": {"message": "No auth credentials found (OpenRouter)", "code": 401}},
        400: {"error": {"message": "deepseek/deepseek-v4.1-flash is not a valid model ID", "code": 400}},
    }
    for up, body in hostile.items():
        for stream in (False, True):
            kind = "stream" if stream else "non-stream"
            status, shown, logs = await pipeline_error(up, body, stream)
            check(f"{kind} upstream {up}: caller sees no vendor/model text", [w for w in VENDOR_WORDS if w in shown.lower()], [])
            if not stream:
                check(f"non-stream upstream {up}: status is Kael's, not upstream's", status, expect[up])
        if up in (401, 402):
            check(f"upstream {up}: operator log line is emitted", "UPSTREAM_CREDENTIALS_OR_CREDIT" in logs, True)


    # ---- 1c. backup-host retry only for "no provider", never for our own
    #          key/credit problems (same account: it would fail the same way)
    for stream in (False, True):
        kind = "stream" if stream else "non-stream"
        for up, want in ((503, 2), (404, 2), (401, 1), (402, 1), (403, 1), (429, 1), (500, 1), (400, 1)):
            check(f"{kind} upstream {up}: makes {want} upstream call(s)", await upstream_calls_for(up, stream), want)


    # ---- 1d. upstream errors that QUOTE the prompt must not be stored/logged
    echoing = {
        403: {"error": {"message": "Input flagged by moderation", "code": 403, "metadata": {"flagged_input": f"{SECRET} please summarise my med...", "provider_name": "Acme"}}},
        400: {"error": {"message": f"Invalid JSON near: {SECRET} please summarise", "code": 400}},
        502: {"error": {"message": "Provider returned error", "code": 502, "metadata": {"raw": f"upstream rejected: {SECRET}", "provider_name": "Acme"}}},
        402: {"error": {"message": f"Insufficient credits {SECRET}", "code": 402}},
    }
    for up, body in echoing.items():
        for stream in (False, True):
            kind = "stream" if stream else "non-stream"
            db, logs, shown = await echoed_error_run(up, body, stream)
            check(f"{kind} upstream {up} quoting the prompt: not stored in the database", SECRET in db, False)
            check(f"{kind} upstream {up} quoting the prompt: not printed to logs", SECRET in logs, False)
            check(f"{kind} upstream {up} quoting the prompt: not shown to the caller", SECRET in shown, False)
    db, logs, _ = await echoed_error_run(403, echoing[403], False)
    check("operator still gets status/code/host in the stored error", all(t in db for t in ("upstream HTTP 403", "code=403", "host=Acme")), True)

    # the summary itself: only short pattern-checked fields survive
    summ = pr.safe_upstream_summary(400, {"error": {"message": "free text " + SECRET, "code": "has spaces and prose", "type": "invalid_request_error",
                                                    "metadata": {"provider_name": "Bad <b>name</b>", "raw": SECRET}}})
    check("summary keeps a safe type, drops prose code / odd host / message / raw", summ, "upstream HTTP 400 type=invalid_request_error")
    check("summary of a non-JSON body", pr.safe_upstream_summary(502, None), "upstream HTTP 502")


    # ---- 1e. "request too long" keeps a useful, vendor-free answer ----------
    overflow = {"error": {"message": "This endpoint's maximum context length is 131072 tokens. However, you requested about 200000 tokens (deepseek/deepseek-v4.1-flash)", "code": 400}}
    for stream in (False, True):
        kind = "stream" if stream else "non-stream"
        db, logs, shown = await echoed_error_run(400, overflow, stream)
        check(f"{kind} context overflow: caller told the request is too long", "too long" in shown.lower(), True)
        check(f"{kind} context overflow: real context size / model never shown", [w for w in ("131072", "200000", "deepseek") if w in shown.lower()], [])
        check(f"{kind} context overflow: upstream wording not stored", "131072" in db, False)
    status, _ = pr.CONTEXT_OVERFLOW_CLIENT_ERROR
    check("context overflow code is the one SDKs recognise", pr.CONTEXT_OVERFLOW_CLIENT_ERROR[1]["error"]["code"], "context_length_exceeded")
    check("an ordinary 400 is NOT mistaken for context overflow", pr.is_context_overflow(400, "messages[0].role invalid"), False)
    check("a 500 mentioning context is NOT mapped", pr.is_context_overflow(500, "context length"), False)

    # ---- 2. failed charge is logged ---------------------------------------
    # P replaced billing.charge_for_request with a no-op; load the real one.
    import importlib
    real_billing = importlib.reload(billing)
    class BoomClient(P.Client):
        async def post(self, url, headers=None, json=None, **k):
            raise P.HTTPError("db down")
    real_billing.httpx.AsyncClient = BoomClient
    usage = {"prompt_tokens": 1000, "completion_tokens": 500, "prompt_cache_hit_tokens": 0, "total_tokens": 1500}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = await real_billing.charge_for_request("user-42", "kael-beta", usage, usage)
    check("failed charge still fails open (returns None)", result, None)
    check("failed charge is logged with CHARGE_FAILED", "CHARGE_FAILED" in buf.getvalue(), True)
    check("charge log names the user and product", ("user=user-42" in buf.getvalue(), "product=kael-beta" in buf.getvalue()), (True, True))
    real_billing.httpx.AsyncClient = P.Client

    # ---- 3. text + tool call kept in non-stream chat completions ----------
    base = {"id": "r1", "created_at": 1, "status": "completed", "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}
    text_item = {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Let me check that."}]}
    call_item = {"type": "function_call", "call_id": "c1", "name": "lookup", "arguments": "{}"}
    both = ra.to_chat_completion({**base, "output": [text_item, call_item]}, "kael-beta")["choices"][0]["message"]
    check("text next to a tool call is kept", both["content"], "Let me check that.")
    check("tool call is still present", [t["function"]["name"] for t in both["tool_calls"]], ["lookup"])
    only = ra.to_chat_completion({**base, "output": [call_item]}, "kael-beta")["choices"][0]["message"]
    check("tool call with no text -> content null", only["content"], None)
    plain = ra.to_chat_completion({**base, "output": [text_item]}, "kael-beta")["choices"][0]["message"]
    check("plain text reply unchanged", plain["content"], "Let me check that.")

    # ---- 4. malformed input -> 400 ----------------------------------------
    for bad in ("high", ["x"], 5):
        try:
            await kp.proxy_kael_response({"model": "kael-beta", "input": "hi", "reasoning": bad}, {"user_id": "u"}, product="kael-beta")
            got = "returned"
        except HTTPException as e:
            got = e.status_code
        except Exception as e:
            got = f"CRASH {type(e).__name__}"
        check(f"reasoning={bad!r} -> 400", got, 400)



if __name__ == "__main__":
    asyncio.run(main())
    if failures:
        print("\n" + "\n".join(failures))
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")
