"""Malformed `model` values on the public API routes must be a clean 400, never a
500 (added 2026-10-06). Imports the REAL app/main.py against a permissive FastAPI
stand-in (decorators return the function unchanged), so the real route functions
run. Offline. Run:  python test_main_routes_input.py
"""
import asyncio
import os
import sys
import types

for k, v in {"SUPABASE_ANON_KEY": "x", "API_KEY_PEPPER": "x", "RESEND_API_KEY": "x", "FRONTEND_URL": "https://example.test"}.items():
    os.environ.setdefault(k, v)

import test_api_privacy as P  # fake httpx + fastapi base stubs

fa = sys.modules["fastapi"]


class _App:
    def __getattr__(self, name):
        return lambda *a, **k: (lambda f: f)


class JSONResponse:
    def __init__(self, content=None, status_code=200, headers=None):
        self.content, self.status_code = content, status_code


fa.FastAPI = lambda *a, **k: _App()
sys.modules["fastapi.responses"].JSONResponse = JSONResponse
sys.modules["fastapi.responses"].Response = JSONResponse  # main.py also imports Response (the picture route); any stub will do here
sys.modules["fastapi.middleware"] = types.ModuleType("fastapi.middleware")
cors = types.ModuleType("fastapi.middleware.cors")
cors.CORSMiddleware = object
sys.modules["fastapi.middleware.cors"] = cors

from app import main as m  # noqa: E402

failures = []


def check(label, got, expected):
    if got != expected:
        failures.append(f"FAIL {label}\n  got:      {got!r}\n  expected: {expected!r}")
    else:
        print(f"ok   {label}")


class Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


async def status_of(fn, body):
    try:
        r = await fn(Req(body), {"user_id": "u"})
        return getattr(r, "status_code", "returned")
    except Exception as e:  # a crash here is what became an HTTP 500
        return f"CRASH {type(e).__name__}"


async def main():
    for route in ("chat_generic", "responses_generic", "messages_generic"):
        fn = getattr(m, route)
        for bad in (["x"], {"a": 1}, 5, None, "nope", ""):
            check(f"{route}: model={bad!r} -> 400", await status_of(fn, {"model": bad, "messages": [], "input": "hi", "max_tokens": 5}), 400)

if __name__ == "__main__":
    asyncio.run(main())
    if failures:
        print("\n" + "\n".join(failures))
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")
