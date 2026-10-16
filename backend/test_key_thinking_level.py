"""Per-key thinking level (added 2026-10-08): api_keys.thinking_level.

Some agents (Cursor and similar) cannot send reasoning_effort, so each API key
can pin a thinking tier from the dashboard. "sdk" (stored as NULL) means the
request decides, exactly as before.

Tested here against the REAL app/api_keys.py and the REAL proxy_kael_* entry
points (only the network and the heavy run_pipeline are faked):

  1. Validation: "sdk"/None/"" -> SDK, every real tier accepted (case-insensitive),
     "off", "medium", non-strings rejected with a 400.
  2. Create / list / update / verify round trip against an in-memory PostgREST
     stand-in: default is "sdk", a level can be set at creation, changed later,
     cleared back to "sdk"; another user's key cannot be edited; a revoked key
     cannot be edited; verify_api_key returns the level on every call.
  3. Precedence on all three wire shapes (chat completions, responses, messages):
     a pinned tier beats the request (even a request that would 400, even a
     malformed `reasoning`); "sdk" leaves today's behavior exactly intact
     (request decides, nothing named = default, bad value = 400); the in-app
     chat requestor (no key) is untouched; a stored value that is no longer a
     real tier acts as "sdk".
  4. Deploy order: if migration 0013 is not applied, verify_api_key still
     authenticates (this is the one that would take every customer down),
     listing works with every key "sdk", creating an "sdk" key works, and
     pinning a level fails with a clear 503 instead of a crash.

Offline, stdlib only.  Run:  python test_key_thinking_level.py
"""
import asyncio
import json
import types

import test_api_privacy as P          # installs the fastapi/httpx stand-ins and env vars
from test_api_privacy import HTTPException
from app import api_keys, config, kael_pipeline as kp

failures = []


def check(label, got, expected):
    if got != expected:
        failures.append(f"FAIL {label}\n  got:      {got!r}\n  expected: {expected!r}")
    else:
        print(f"ok   {label}")


def run(coro):
    return asyncio.run(coro)


def status_of(coro):
    try:
        run(coro)
        return None
    except HTTPException as e:
        return e.status_code


MODELS = list(config.PRODUCTS.values())          # kael-beta, kael-pro-beta
TIERS = api_keys.valid_thinking_levels()          # every tier of every model

# ---------------------------------------------------------------------
# In-memory PostgREST stand-in for the api_keys table
# ---------------------------------------------------------------------
ROWS: list[dict] = []
STATE = {"column_exists": True, "n": 0}


class _Resp:
    def __init__(self, status, payload):
        self.status_code, self._p = status, payload
        self.text = json.dumps(payload)

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise api_keys.httpx.HTTPError(self.text)


def _matches(row, params):
    for k, v in params.items():
        if k in ("select", "order", "limit"):
            continue
        if v.startswith("eq."):
            if str(row.get(k)) != v[3:]:
                return False
        elif v == "is.null":
            if row.get(k) is not None:
                return False
    return True


def _project(row, select):
    cols = select.split(",")
    return {c: row.get(c) for c in cols}


def _no_column():
    return _Resp(400, {"code": "42703", "message": "column api_keys.thinking_level does not exist"})


class _Client:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, params=None):
        params = dict(params or {})
        if "thinking_level" in params.get("select", "") and not STATE["column_exists"]:
            return _no_column()
        return _Resp(200, [_project(r, params["select"]) for r in ROWS if _matches(r, params)])

    async def post(self, url, headers=None, json=None):
        if "thinking_level" in json and not STATE["column_exists"]:
            return _no_column()
        STATE["n"] += 1
        row = {"id": f"k{STATE['n']}", "created_at": "2026-10-08T10:00:00Z", "last_used_at": None,
               "revoked_at": None, "thinking_level": None, **json}
        ROWS.append(row)
        return _Resp(201, [dict(row)])

    async def patch(self, url, headers=None, params=None, json=None):
        if "thinking_level" in json and not STATE["column_exists"]:
            return _no_column()
        hit = [r for r in ROWS if _matches(r, dict(params or {}))]
        for r in hit:
            r.update(json)
        return _Resp(200, [dict(r) for r in hit])


class _HttpxShim:
    AsyncClient = _Client
    HTTPError = P.HTTPError


api_keys.httpx = _HttpxShim


def reset(column_exists=True):
    ROWS.clear()
    STATE.update(column_exists=column_exists, n=0)


# ---------------------------------------------------------------------
# 1. Validation
# ---------------------------------------------------------------------
check("levels: the dropdown's pinnable values are exactly the tier table", api_keys.valid_thinking_levels(), TIERS)
for raw in (None, "", "  ", "sdk", "SDK", " Sdk "):
    check(f"normalize {raw!r} -> SDK (None)", api_keys.normalize_thinking_level(raw), None)
for t in TIERS:
    check(f"normalize {t!r} -> itself", api_keys.normalize_thinking_level(t), t)
check("normalize is case-insensitive", api_keys.normalize_thinking_level(" Z-High "), "z-high")
for bad in ("off", "none", "medium", "minimal", "auto", "ultra", 3, ["low"], {"a": 1}):
    got = None
    try:
        api_keys.normalize_thinking_level(bad)
    except HTTPException as e:
        got = (e.status_code, e.detail["error"]["param"])
    check(f"normalize {bad!r} -> 400 on thinking_level", got, (400, "thinking_level"))

# ---------------------------------------------------------------------
# 2. Create / list / update / verify
# ---------------------------------------------------------------------
reset()
a = run(api_keys.create_api_key("alice", "Plain"))
check("create: default level is sdk", a["thinking_level"], "sdk")
check("create: nothing is written to the column for an sdk key", "thinking_level" in ROWS[0] and ROWS[0]["thinking_level"], None)
b = run(api_keys.create_api_key("alice", "Cursor", "high"))
check("create: a level can be set right away", b["thinking_level"], "high")
check("create: it is stored", [r["thinking_level"] for r in ROWS], [None, "high"])
check("create: an invalid level creates nothing", (status_of(api_keys.create_api_key("alice", "Bad", "medium")), len(ROWS)), (400, 2))

listed = {k["name"]: k for k in run(api_keys.list_api_keys("alice"))}
check("list: levels come back as sdk / tier", (listed["Plain"]["thinking_level"], listed["Cursor"]["thinking_level"]), ("sdk", "high"))

check("update: change to max", run(api_keys.update_thinking_level("alice", b["id"], "max")), "max")
check("update: stored", ROWS[1]["thinking_level"], "max")
check("update: z tiers are pinnable", run(api_keys.update_thinking_level("alice", b["id"], "z-low")), "z-low")
check("update: 'sdk' clears it back to NULL", (run(api_keys.update_thinking_level("alice", b["id"], "sdk")), ROWS[1]["thinking_level"]), ("sdk", None))
check("update: invalid level is a 400 and changes nothing", (status_of(api_keys.update_thinking_level("alice", b["id"], "off")), ROWS[1]["thinking_level"]), (400, None))
check("update: another user cannot edit it", (run(api_keys.update_thinking_level("mallory", a["id"], "max")), ROWS[0]["thinking_level"]), (None, None))
check("update: unknown key id -> None", run(api_keys.update_thinking_level("alice", "nope", "max")), None)
run(api_keys.revoke_api_key("alice", b["id"]))
check("update: a revoked key cannot be edited", (run(api_keys.update_thinking_level("alice", b["id"], "max")), ROWS[1]["thinking_level"]), (None, None))

reset()
c = run(api_keys.create_api_key("alice", "Pinned", "z-high"))
got = run(api_keys.verify_api_key(c["secret"]))
check("verify: returns the pinned level", (got["thinking_level"], got["user_id"], got["name"]), ("z-high", "alice", "Pinned"))
run(api_keys.update_thinking_level("alice", c["id"], "low"))
check("verify: a change is live on the very next call (no cache)", run(api_keys.verify_api_key(c["secret"]))["thinking_level"], "low")
run(api_keys.update_thinking_level("alice", c["id"], "sdk"))
check("verify: sdk -> None", run(api_keys.verify_api_key(c["secret"]))["thinking_level"], None)
ROWS[0]["thinking_level"] = "ultra"
check("verify: a stored value that is not a real tier acts as sdk", run(api_keys.verify_api_key(c["secret"]))["thinking_level"], None)
check("list: ... and shows as sdk", run(api_keys.list_api_keys("alice"))[0]["thinking_level"], "sdk")

# ---------------------------------------------------------------------
# 3. Precedence on every wire shape
# ---------------------------------------------------------------------
CAPTURED = {}


async def _fake_run_pipeline(**kw):
    CAPTURED.update(kw)
    return {"ok": True}


kp.run_pipeline = _fake_run_pipeline
CHAT = {"messages": [{"role": "user", "content": "hi"}]}
RESP = {"input": "hi"}
MSGS = {"max_tokens": 10, "messages": [{"role": "user", "content": "hi"}]}


def call(fn, body, level, model, **extra):
    CAPTURED.clear()
    requestor = {"user_id": "u", "key_id": "k", "name": "n", "thinking_level": level}
    try:
        run(fn({**body, **extra}, requestor, product=model["key"]))
        return CAPTURED.get("reasoning_tier")
    except HTTPException as e:
        return f"HTTP {e.status_code}"


SHAPES = [
    ("chat completions", kp.proxy_kael_chat_completion, CHAT, lambda v: {"reasoning_effort": v}),
    ("responses", kp.proxy_kael_response, RESP, lambda v: {"reasoning": {"effort": v}}),
    ("messages", kp.proxy_kael_messages, MSGS, lambda v: {"reasoning_effort": v}),
]
check("every tier of both models is pinnable, nothing else", TIERS, ["low", "high", "max", "z-low", "z-high"])

for model in MODELS:
    own = list(model["reasoning_tiers"])           # this model's tiers
    other = [t for t in TIERS if t not in own]     # the other model's tiers
    top = own[-1]                                  # its highest tier ("max" / "z-high")
    low = own[0]
    for name, fn, body, field in SHAPES:
        tag = f"{model['slug']} / {name}"
        check(f"{tag}: sdk + nothing named -> its default tier", call(fn, body, None, model), model["default_reasoning_tier"])
        check(f"{tag}: sdk + request names {top} -> {top} (unchanged behavior)", call(fn, body, None, model, **field(top)), top)
        check(f"{tag}: sdk + request names a bad value -> still a 400", call(fn, body, None, model, **field("medium")), "HTTP 400")
        for t in own:
            check(f"{tag}: key pinned to {t} + nothing named -> {t}", call(fn, body, t, model), t)
        check(f"{tag}: pinned {low} beats the request's {top}", call(fn, body, low, model, **field(top)), low)
        check(f"{tag}: pinned beats a request value that would 400 (Cursor sending 'medium')", call(fn, body, top, model, **field("medium")), top)
        spec = model["reasoning_tiers"][top]
        check(f"{tag}: a pinned tier reaches the pipeline's per-pass config", (CAPTURED["draft"].reasoning_effort, CAPTURED["critic"].reasoning_effort, CAPTURED["draft_count"]), (spec["draft"], spec["critic"], spec.get("drafts", 1)))
        check(f"{tag}: a value that is no longer a real tier acts as sdk", call(fn, body, "ultra", model, **field(top)), top)
        # A pin that belongs to the OTHER model does not apply here: it acts as "sdk", never a 400 from the pin
        # and never this model running at the other model's tier.
        for t in other:
            check(f"{tag}: key pinned to {t} (the other model's tier) acts as sdk: default tier", call(fn, body, t, model), model["default_reasoning_tier"])
            check(f"{tag}: ... and the request still decides ({top})", call(fn, body, t, model, **field(top)), top)
            check(f"{tag}: ... and a bad request value is still a 400", call(fn, body, t, model, **field("medium")), "HTTP 400")

beta, pro_beta = MODELS
check("responses: pinned beats a malformed `reasoning` (a string)", call(kp.proxy_kael_response, RESP, "high", beta, reasoning="max"), "high")
check("responses: sdk + malformed `reasoning` -> still a 400", call(kp.proxy_kael_response, RESP, None, beta, reasoning="max"), "HTTP 400")
check("responses: a pin from the other model + malformed `reasoning` -> still a 400 (the pin does not apply)", call(kp.proxy_kael_response, RESP, "z-low", beta, reasoning="max"), "HTTP 400")

check("z-high pinned on kael-pro-beta reaches the pipeline as five calls (3 drafts + fusor)",
      (call(kp.proxy_kael_chat_completion, CHAT, "z-high", pro_beta), CAPTURED["draft_count"], CAPTURED["fusor"] is not None), ("z-high", 3, True))
check("the same key on kael-beta is a normal two-call run (pin does not apply)",
      (call(kp.proxy_kael_chat_completion, CHAT, "z-high", beta), CAPTURED["draft_count"], CAPTURED["fusor"] is None), ("low", 1, True))

# in-app chat (Playground): its requestor has no key and no level
CAPTURED.clear()
run(kp.proxy_kael_chat_completion({**CHAT, "reasoning_effort": "high"}, {"user_id": "u", "key_id": None, "name": "in-app chat"}, source="app_chat", product="kael-beta"))
check("in-app chat requestor (no key, no level) is untouched", CAPTURED["reasoning_tier"], "high")

# ---------------------------------------------------------------------
# 4. Deploy order: migration 0013 not applied yet
# ---------------------------------------------------------------------
reset(column_exists=False)
old = run(api_keys.create_api_key("alice", "Old style"))
check("no column: creating an sdk key still works", old["thinking_level"], "sdk")
got = run(api_keys.verify_api_key(old["secret"]))
check("no column: EVERY key still authenticates (this is the outage case)", (got is not None, got and got["thinking_level"]), (True, None))
check("no column: listing works, every key is sdk", [k["thinking_level"] for k in run(api_keys.list_api_keys("alice"))], ["sdk"])
check("no column: pinning at creation is a clear 503, not a crash", status_of(api_keys.create_api_key("alice", "Pinned", "high")), 503)
check("no column: pinning later is a clear 503, not a crash", status_of(api_keys.update_thinking_level("alice", old["id"], "high")), 503)

print()
if failures:
    print("\n".join(failures))
    raise SystemExit(f"\n{len(failures)} FAILED")
print("all passed")
