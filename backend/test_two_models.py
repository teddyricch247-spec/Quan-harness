"""Kael Beta and Kael Pro Beta: the two-model split (added 2026-10-08).

Offline. Run:  python test_two_models.py

Covers what test_z_tiers.py (tier tables, resolve, entry points) does not: the
registry, retired names, per-model billing, the generic routers, the routes
registered per model, and the public catalog. Imports the REAL app/main.py
against a recording FastAPI stand-in (like test_main_routes_input.py, but it
keeps each registered route so they can be listed).
"""
import asyncio
import os
import sys
import types
from decimal import Decimal

for k, v in {"SUPABASE_ANON_KEY": "x", "API_KEY_PEPPER": "x", "RESEND_API_KEY": "x", "FRONTEND_URL": "https://example.test"}.items():
    os.environ.setdefault(k, v)

import test_api_privacy as P  # fake httpx + fastapi base stubs

fa = sys.modules["fastapi"]
ROUTES = []   # (method, path)


class _App:
    def _reg(self, method):
        def deco_factory(path, *a, **k):
            def deco(f):
                ROUTES.append((method, path))
                return f
            return deco
        return deco_factory

    def __getattr__(self, name):
        if name in ("get", "post", "patch", "delete", "put", "api_route"):
            return self._reg(name)
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

from app import main as m, config, billing  # noqa: E402
from app import kael_pipeline as kp  # noqa: E402

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


# ---- registry -----------------------------------------------------------
check("PRODUCTS: exactly the two Kael models, in order", list(config.PRODUCTS), ["kael-beta", "kael-pro-beta"])
check("every model's key is its public slug", [(k, v["slug"]) for k, v in config.PRODUCTS.items()], [("kael-beta", "kael-beta"), ("kael-pro-beta", "kael-pro-beta")])
check("labels", [v["label"] for v in config.PRODUCTS.values()], ["Kael Beta", "Kael Pro Beta"])
check("both are public and billed", (sorted(config.PUBLIC_PRODUCTS), sorted(config.BILLED_PRODUCTS)), (["kael-beta", "kael-pro-beta"],) * 2)
check("MODEL_TO_PRODUCT maps each slug to itself and nothing else", config.MODEL_TO_PRODUCT, {"kael-beta": "kael-beta", "kael-pro-beta": "kael-pro-beta"})
for retired in ("pro", "quan-pro", "quan-4", "ultra", "flash", "kael", "Kael Beta"):
    check(f"retired or unknown name {retired!r} resolves to no model", config.MODEL_TO_PRODUCT.get(retired), None)
check("the two models share every upstream setting (only identity, tiers, price differ)",
      sorted(k for k in config.PRODUCTS["kael-beta"] if config.PRODUCTS["kael-beta"][k] != config.PRODUCTS["kael-pro-beta"][k]),
      sorted(["key", "slug", "label", "tagline", "best_for", "aliases", "reasoning_tiers", "default_reasoning_tier", "customer_price_per_million"]))
check("same master prompt for both", config.PRODUCTS["kael-beta"]["system_identity"] == config.PRODUCTS["kael-pro-beta"]["system_identity"], True)

# ---- billing: each model at its own price ----------------------------------
one_m = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000, "prompt_cache_hit_tokens": 0}
cached = {"prompt_tokens": 1_000_000, "completion_tokens": 0, "prompt_cache_hit_tokens": 1_000_000}
mixed = {"prompt_tokens": 12_000, "completion_tokens": 1_500, "prompt_cache_hit_tokens": 2_000}
d = Decimal
check("kael-beta: 1M in + 1M out = $13.00", billing.calculate_cost("kael-beta", one_m, None)["cost_usd"], d("13.00000"))
check("kael-pro-beta: 1M in + 1M out = $33.00", billing.calculate_cost("kael-pro-beta", one_m, None)["cost_usd"], d("33.00000"))
check("kael-beta: 1M fully cached input = $0.60", billing.calculate_cost("kael-beta", cached, None)["cost_usd"], d("0.60000"))
check("kael-pro-beta: 1M fully cached input = $1.60", billing.calculate_cost("kael-pro-beta", cached, None)["cost_usd"], d("1.60000"))
# 12,000 in of which 2,000 cached, 1,500 out. Worked by hand:
#   kael-beta:     10,000 x $3/M + 2,000 x $0.60/M + 1,500 x $10/M = 0.03   + 0.0012 + 0.015  = $0.0462
#   kael-pro-beta: 10,000 x $8/M + 2,000 x $1.60/M + 1,500 x $25/M = 0.08   + 0.0032 + 0.0375 = $0.1207
check("kael-beta: 12,000 in (2,000 cached) + 1,500 out = $0.0462", billing.calculate_cost("kael-beta", mixed, None)["cost_usd"], d("0.04620"))
check("kael-pro-beta: the same request = $0.1207", billing.calculate_cost("kael-pro-beta", mixed, None)["cost_usd"], d("0.12070"))
check("current_customer_price per model", (config.current_customer_price("kael-beta")["output"], config.current_customer_price("kael-pro-beta")["output"]), (10.0, 25.0))
try:
    billing.calculate_cost("pro", one_m, None)
    got = "no error"
except KeyError:
    got = "KeyError"
check("a removed key ('pro') cannot be billed", got, "KeyError")

# ---- routes registered per model ----------------------------------------------
want = {
    ("post", "/v1/chat/completions"), ("post", "/v1/responses"), ("post", "/v1/messages"), ("get", "/v1/models"),
}
for key in ("kael-beta", "kael-pro-beta"):
    want |= {("post", f"/{key}/v1/chat/completions"), ("post", f"/{key}/v1/responses"), ("post", f"/{key}/v1/messages"), ("get", f"/{key}/v1/models")}
have = set(ROUTES)
check("every model has chat, responses, messages and models routes; the generic routes remain", want <= have, True)
check("no /pro/ route and no /ultra/ route is registered", sorted(p for _m, p in have if p.startswith("/pro/") or p.startswith("/ultra/")), [])

# ---- generic routers and the 400s ---------------------------------------------
async def run(fn, body):
    try:
        r = await fn(Req(body), {"user_id": "u"})
        return r
    except Exception as e:
        return e


async def main():
    for route in ("chat_generic", "responses_generic"):
        fn = getattr(m, route)
        r = await run(fn, {"model": "quan-pro", "messages": [], "input": "hi"})
        check(f"{route}: the retired alias 'quan-pro' is a 400", getattr(r, "status_code", r), 400)
        msg = r.content["error"]["message"] if hasattr(r, "content") else ""
        check(f"{route}: the 400 lists both current models", msg, "Unknown model 'quan-pro'. Use 'kael-beta' or 'kael-pro-beta'.")
        check(f"{route}: the 400 carries code model_not_found", r.content["error"]["code"], "model_not_found")
    r = await run(m.messages_generic, {"model": "quan-4", "max_tokens": 5, "messages": []})
    check("messages_generic: a retired alias is a 400 in Anthropic's error shape", (r.status_code, r.content["type"], r.content["error"]["message"]), (400, "error", "Unknown model 'quan-4'. Use 'kael-beta' or 'kael-pro-beta'."))

    # dispatch: the right entry point gets the right product
    seen = []

    async def spy(body, requestor, source="api", on_complete=None, *, product):
        seen.append((product, body.get("reasoning_effort")))
        return "ok"

    from functools import partial
    for table in (m._PROXY_CHAT, m._PROXY_RESPONSES, m._PROXY_MESSAGES):
        check("each dispatch table has one entry per model", sorted(table), ["kael-beta", "kael-pro-beta"])
    real = dict(m._PROXY_CHAT)
    m._PROXY_CHAT["kael-beta"] = partial(spy, product="kael-beta")
    m._PROXY_CHAT["kael-pro-beta"] = partial(spy, product="kael-pro-beta")
    try:
        await m.chat_generic(Req({"model": "kael-pro-beta", "messages": [], "reasoning_effort": "z-high"}), {"user_id": "u"})
        await m.chat_generic(Req({"model": "kael-beta", "messages": [], "reasoning_effort": "max"}), {"user_id": "u"})
    finally:
        m._PROXY_CHAT.update(real)
    check("the generic router sends each model's name to that model", seen, [("kael-pro-beta", "z-high"), ("kael-beta", "max")])

    # public catalog
    cfg = await m.public_config()
    prods = {p["slug"]: p for p in cfg["products"]}
    check("GET /api/config lists both models", list(prods), ["kael-beta", "kael-pro-beta"])
    check("GET /api/config: each model's tiers and default", {k: (v["thinking_tiers"], v["default_thinking_tier"]) for k, v in prods.items()},
          {"kael-beta": (["low", "high", "max"], "low"), "kael-pro-beta": (["z-low", "z-high"], "z-low")})
    check("GET /api/config: each model's own price", {k: v["customer_price_per_million"]["standard"] for k, v in prods.items()},
          {"kael-beta": {"input": 3.0, "output": 10.0, "cached_input": 0.60}, "kael-pro-beta": {"input": 8.0, "output": 25.0, "cached_input": 1.60}})
    leaked = [k for p in cfg["products"] for k in p if "upstream" in k or k in ("key", "draft_model", "critic_model", "system_identity")]
    check("GET /api/config exposes no upstream or internal field", leaked, [])
    check("GET /api/models-style payload names each model by slug", [x["id"] for x in m._models_payload(list(config.PRODUCTS))["data"]], ["kael-beta", "kael-pro-beta"])
    check("_models_hint", m._models_hint(), "Use 'kael-beta' or 'kael-pro-beta'.")

    # playground session create: either model, nothing else
    class FakeSB:
        created = []

    async def fake_create(user_id, model, thinking_enabled=False, reasoning_effort=None):
        FakeSB.created.append((model, reasoning_effort))
        return {"id": "s", "model": model, "reasoning_effort": reasoning_effort}

    m.supabase_client.create_chat_session = fake_create
    for requested in ("kael-beta", "kael-pro-beta"):
        out = await m.create_session(Req({"product": requested}), {"id": "u"})
        check(f"create_session({requested!r}) stores that model with its own default tier", FakeSB.created[-1], (requested, config.PRODUCTS[requested]["default_reasoning_tier"]))
    for requested in ("pro", "quan-pro", "", None, ["kael-beta"]):
        r = await m.create_session(Req({"product": requested}), {"id": "u"})
        check(f"create_session({requested!r}) -> 400 naming both models", (r.status_code, r.content["error"]["message"].endswith("Use 'kael-beta' or 'kael-pro-beta'.")), (400, True))


asyncio.run(main())
if failures:
    print("\n" + "\n".join(failures))
    print(f"\n{len(failures)} FAILED")
    sys.exit(1)
print("\nALL CHECKS PASSED")
