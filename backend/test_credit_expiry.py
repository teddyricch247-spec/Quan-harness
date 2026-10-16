"""Offline tests for the 12-month credit expiry (app/credit_expiry.py, 2026-10-13).

Two layers, both against the REAL module code:

  1. replay(): the pure rule engine. First-in-first-out use of credits, debt
     from overdrawn balances, recorded expiries, the "lenient until the daily run
     records it" rule, and detection of an expiry row that does not match the rules.
  2. run_expiry(): the whole run against an in-memory stand-in for Supabase that
     implements the same semantics as the public.expire_credits() database function
     (migration 0017): row lock, ledger row count check, balance update and ledger
     row written together. Proves idempotency, dry runs, the kill switch, the
     drift guard, a stale calculation being refused, and one bad account not
     stopping the others.

Offline: no fastapi/httpx install needed (small stand-ins below).

Run:  python test_credit_expiry.py
"""

import asyncio
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["SUPABASE_URL"] = "https://sb.test"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "service-role-test"
os.environ.setdefault("OPENROUTER_API_KEY", "or-test")

# ---------------------------------------------------------------------
# Offline stand-ins for httpx (an in-memory Supabase) and fastapi
# ---------------------------------------------------------------------
fa = types.ModuleType("fastapi")


class HTTPException(Exception):
    def __init__(self, status_code, detail=None, headers=None):
        self.status_code, self.detail = status_code, detail
        super().__init__(f"{status_code}: {detail}")


fa.HTTPException = HTTPException
sys.modules.setdefault("fastapi", fa)

hx = types.ModuleType("httpx")


class HTTPError(Exception):
    pass


class HTTPStatusError(HTTPError):
    def __init__(self, m, response=None):
        super().__init__(m)
        self.response = response


hx.HTTPError, hx.HTTPStatusError = HTTPError, HTTPStatusError


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class FakeDB:
    """billing_accounts + billing_ledger, with PostgREST-style reads and the
    expire_credits() function."""

    def __init__(self):
        self.balances: dict = {}
        self.ledger: list = []
        self.clock = datetime(2026, 2, 1, tzinfo=timezone.utc)
        self.requests: list = []
        self.fail_for_user: set = set()
        self.before_rpc = None  # hook(db, body) called before the function body runs
        self._next_id = 1

    def add_row(self, user, kind, amount, when, description=None):
        amount = Decimal(str(amount))
        self.ledger.append({
            "id": self._next_id, "user_id": user, "kind": kind, "amount_usd": str(amount),
            "created_at": when.isoformat(), "description": description,
        })
        self._next_id += 1
        self.balances[user] = self.balances.get(user, Decimal("0")) + amount

    def ledger_of(self, user):
        return [r for r in self.ledger if r["user_id"] == user]

    def drift(self, user):
        return self.balances[user] - sum((Decimal(r["amount_usd"]) for r in self.ledger_of(user)), Decimal("0"))

    # -- PostgREST-ish reads
    def select(self, table, params):
        rows = self.ledger if table == "billing_ledger" else [{"user_id": u, "balance_usd": str(b)} for u, b in self.balances.items()]
        for key, expr in params.items():
            if key in ("select", "order", "limit", "offset"):
                continue
            op, _, value = expr.partition(".")
            if op == "eq":
                rows = [r for r in rows if str(r.get(key)) == value]
            elif op == "in":
                allowed = value.strip("()").split(",")
                rows = [r for r in rows if r.get(key) in allowed]
            elif op in ("gt", "lt"):
                def val(r):
                    return _ts(r[key]) if key == "created_at" else Decimal(str(r[key]))
                bound = _ts(value) if key == "created_at" else Decimal(value)
                rows = [r for r in rows if (val(r) > bound if op == "gt" else val(r) < bound)]
        for spec in reversed([o for o in params.get("order", "").split(",") if o]):
            field, _, direction = spec.partition(".")
            rows = sorted(rows, key=lambda r, f=field: (_ts(r[f]) if f == "created_at" else r[f]), reverse=(direction == "desc"))
        offset, limit = int(params.get("offset", 0)), int(params.get("limit", 1000))
        rows = rows[offset:offset + limit]
        wanted = params.get("select", "*")
        if wanted != "*":
            cols = wanted.split(",")
            rows = [{c: r.get(c) for c in cols} for r in rows]
        return rows

    # -- public.expire_credits(), same steps as the SQL
    def expire_credits(self, body):
        if self.before_rpc:
            self.before_rpc(self, body)
        user, amount = body["p_user_id"], Decimal(str(body["p_amount"]))
        if amount <= 0:
            raise AssertionError("expire_credits: amount must be positive")
        if user not in self.balances:
            raise AssertionError("billing_accounts row not found")
        if len(self.ledger_of(user)) != body["p_ledger_rows"]:
            return None
        self.balances[user] -= amount
        self.ledger.append({
            "id": self._next_id, "user_id": user, "kind": "adjustment", "amount_usd": str(-amount),
            "created_at": self.clock.isoformat(), "description": body["p_description"],
        })
        self._next_id += 1
        return float(self.balances[user])


DB = FakeDB()


class Resp:
    def __init__(self, status, payload):
        self.status_code, self._p, self.headers, self.text = status, payload, {}, str(payload)[:200]

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise HTTPStatusError("err", response=self)


class AsyncClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, params=None):
        params = dict(params or {})
        DB.requests.append(("GET", url, params))
        table = url.rsplit("/", 1)[1]
        if table == "billing_accounts" and params.get("user_id", "").removeprefix("eq.") in DB.fail_for_user:
            return Resp(500, {"message": "boom"})
        if table == "billing_ledger" and params.get("user_id", "").removeprefix("eq.") in DB.fail_for_user:
            return Resp(500, {"message": "boom"})
        return Resp(200, DB.select(table, params))

    async def post(self, url, headers=None, json=None):
        DB.requests.append(("POST", url, json))
        assert url.endswith("/rpc/expire_credits"), url
        try:
            return Resp(200, DB.expire_credits(json))
        except AssertionError as e:
            return Resp(400, {"message": str(e)})


hx.AsyncClient = AsyncClient
sys.modules["httpx"] = hx

from app import billing, config, credit_expiry as ce  # noqa: E402  (after the stand-ins)

D = Decimal
UTC = timezone.utc


def at(y, m, d, h=0):
    return datetime(y, m, d, h, tzinfo=UTC)


def row(kind, amount, when, description=None):
    return {"kind": kind, "amount_usd": str(amount), "created_at": when.isoformat(), "description": description}


checks = 0


def check(label, ok):
    global checks
    checks += 1
    print(("ok   " if ok else "FAIL ") + label)
    if not ok:
        raise SystemExit(f"FAILED: {label}")


# =====================================================================
# 1. The rule engine
# =====================================================================
check("add_months: plain", ce.add_months(at(2025, 10, 2, 8), 12) == at(2026, 10, 2, 8))
check("add_months: Feb 29 + 12 months -> Feb 28", ce.add_months(at(2028, 2, 29), 12) == at(2029, 2, 28))
check("add_months: Jan 31 + 1 month -> Feb 28", ce.add_months(at(2026, 1, 31), 1) == at(2026, 2, 28))
check("add_months: Aug 31 + 6 months -> Feb 28, next year", ce.add_months(at(2026, 8, 31), 6) == at(2027, 2, 28))
check("add_months: negative (the run's cutoff)", ce.add_months(at(2026, 2, 1), -12) == at(2025, 2, 1))
check("period is 12 months", ce.CREDIT_EXPIRY_MONTHS == 12)

# unused credit past 12 months is due
r = ce.replay([row("deposit", "10", at(2025, 1, 15))], at(2026, 2, 1))
check("a lot past 12 months is due in full", r.due_total == D("10") and r.balance == D("10") and len(r.due) == 1)

# not yet 12 months
r = ce.replay([row("deposit", "10", at(2025, 1, 15))], at(2026, 1, 14, 23))
check("a lot one hour short of 12 months is not due", r.due_total == 0)
r = ce.replay([row("deposit", "10", at(2025, 1, 15))], at(2026, 1, 15))
check("a lot exactly 12 months old is due", r.due_total == D("10"))

# usage takes the oldest credit first
r = ce.replay([
    row("deposit", "10", at(2025, 1, 15)),
    row("deposit", "20", at(2025, 6, 1)),
    row("usage", "-12", at(2025, 7, 1)),
], at(2026, 2, 1))
check("FIFO: 12 used = all of lot 1 and 2 of lot 2", r.due_total == 0 and [l.remaining for l in r.lots] == [D("18")] and r.balance == D("18"))

r = ce.replay([
    row("deposit", "10", at(2025, 1, 15)),
    row("deposit", "20", at(2025, 6, 1)),
    row("usage", "-4", at(2025, 7, 1)),
], at(2026, 2, 1))
check("FIFO: only the old lot's unused 6 is due", r.due_total == D("6") and r.balance == D("26"))

# several due lots
r = ce.replay([
    row("deposit", "5", at(2025, 1, 1)),
    row("deposit", "7", at(2025, 1, 20)),
    row("deposit", "9", at(2025, 5, 1)),
], at(2026, 2, 1))
check("two old lots are both due, the newer is not", r.due_total == D("12") and len(r.due) == 2 and r.balance == D("21"))

# overdrawn: usage with no credit is debt, the next deposit pays it first
r = ce.replay([
    row("deposit", "1", at(2025, 1, 1)),
    row("usage", "-1.50000", at(2025, 2, 1)),
    row("deposit", "10", at(2025, 3, 1)),
], at(2026, 6, 1))
check("debt is paid before a new lot starts (lot is 9.5, not 10)", r.balance == D("9.5") and r.due_total == D("9.5") and r.debt == 0)

r = ce.replay([row("deposit", "1", at(2025, 1, 1)), row("usage", "-1.50000", at(2025, 2, 1))], at(2026, 6, 1))
check("overdrawn account: balance is negative, nothing to expire", r.balance == D("-0.5") and r.debt == D("0.5") and r.due_total == 0)

# a recorded expiry removes the lot; the next replay finds nothing due
rows = [
    row("deposit", "10", at(2025, 1, 15)),
    row("usage", "-3", at(2025, 3, 1)),
    row("adjustment", "-7", at(2026, 1, 16), "Expired credits (12 months after they were added on 2025-01-15 ($7.00000))"),
]
r = ce.replay(rows, at(2026, 2, 1))
check("after a recorded expiry nothing is due and the balance is 0", r.due_total == 0 and r.balance == 0 and r.expiry_rows_consistent)

# lenient until the run records it: usage after the anniversary but before the run still used the credit
rows = [
    row("deposit", "10", at(2025, 1, 15)),
    row("usage", "-2", at(2026, 1, 15, 12)),  # a day after the anniversary, before any expiry row
]
r = ce.replay(rows, at(2026, 1, 16, 3))
check("usage between the anniversary and the run still takes the old credit", r.due_total == D("8") and r.balance == D("8"))

# an expiry row that does not match the rules is flagged
rows = [row("deposit", "10", at(2025, 1, 15)), row("adjustment", "-9", at(2026, 1, 16), "Expired credits (x)")]
r = ce.replay(rows, at(2026, 2, 1))
check("an expiry row that disagrees with the rules is flagged", not r.expiry_rows_consistent and r.problem)

# other adjustments behave like deposits/usage
r = ce.replay([row("adjustment", "5", at(2025, 1, 1), "Goodwill"), row("adjustment", "-2", at(2025, 2, 1), "Correction")], at(2026, 2, 1))
check("positive adjustment is a lot, negative (non-expiry) adjustment uses it", r.due_total == D("3"))
check("only expiry-prefixed negative adjustments count as expiry rows",
      ce.is_expiry_row(row("adjustment", "-2", at(2025, 2, 1), "Expired credits (...)")) and not ce.is_expiry_row(row("adjustment", "-2", at(2025, 2, 1), "Correction"))
      and not ce.is_expiry_row(row("usage", "-2", at(2025, 2, 1), "Expired credits")))

# exactness: 5 decimal places, no float noise
r = ce.replay([row("deposit", "0.10000", at(2025, 1, 1)), row("usage", "-0.03333", at(2025, 1, 2)), row("usage", "-0.03333", at(2025, 1, 3))], at(2026, 2, 1))
check("exact decimal arithmetic", r.due_total == D("0.03334"))

desc = ce.expiry_description(ce.replay([row("deposit", "10", at(2025, 1, 15))], at(2026, 2, 1)).due)
check("expiry description starts with the marker, has no @ and no personal data",
      desc.startswith(ce.EXPIRY_DESCRIPTION_PREFIX) and "@" not in desc and "2025-01-15" in desc)

# =====================================================================
# 2. A whole run against the in-memory database
# =====================================================================
NOW = at(2026, 2, 1)


def fresh():
    global DB
    DB = FakeDB()
    DB.clock = NOW
    config.CREDIT_EXPIRY_ENABLED = True
    return DB


def run(**kw):
    return asyncio.run(ce.run_expiry(now=NOW, **kw))


# A: 10 added 2025-01-15, 3 used -> 7 expires
fresh()
DB.balances["A"] = D("0")
DB.add_row("A", "deposit", "10", at(2025, 1, 15), "Admin credit adjustment")
DB.add_row("A", "usage", "-3", at(2025, 3, 1), "Kael Beta request")
# B: nothing due (FIFO consumed the old lot)
DB.balances["B"] = D("0")
DB.add_row("B", "deposit", "10", at(2025, 1, 15))
DB.add_row("B", "deposit", "20", at(2025, 6, 1))
DB.add_row("B", "usage", "-12", at(2025, 7, 1))
# C: young credit only: not even a candidate
DB.balances["C"] = D("0")
DB.add_row("C", "deposit", "50", at(2025, 12, 1))

out = run(dry_run=True)
check("dry run: reports A's 7 and writes nothing", out.status == "ok" and out.dry_run and out.total_usd == D("7") and DB.balances["A"] == D("7")
      and len(DB.ledger_of("A")) == 2 and not any(m == "POST" for m, *_ in DB.requests))
check("dry run: only accounts with credit older than 12 months are looked at (A and B, not C)", out.accounts_checked == 2)

out = run()
check("real run: A's unused 7 is removed", out.status == "ok" and [e["user_id"] for e in out.expired] == ["A"] and out.total_usd == D("7"))
check("real run: A's balance is 0 and the ledger still adds up", DB.balances["A"] == 0 and DB.drift("A") == 0)
last = DB.ledger_of("A")[-1]
check("real run: one 'adjustment' row, negative, marker description, no personal data",
      last["kind"] == "adjustment" and D(last["amount_usd"]) == D("-7") and last["description"].startswith("Expired credits") and "@" not in last["description"])
check("real run: B and C untouched", DB.balances["B"] == D("18") and DB.balances["C"] == D("50") and len(DB.ledger_of("B")) == 3)

before = (dict(DB.balances), len(DB.ledger))
out = run()
check("running it again is a no-op (idempotent)", out.total_usd == 0 and not out.expired and (DB.balances, len(DB.ledger)) == before)

# the day the next lot of B reaches 12 months, only that remainder expires
later = at(2026, 6, 2)
out = asyncio.run(ce.run_expiry(now=later))
check("B's second lot expires at its own anniversary, for what was left of it", D(out.expired[0]["amount_usd"]) == D("18") if out.expired else False)

# kill switch
fresh()
DB.balances["A"] = D("0")
DB.add_row("A", "deposit", "10", at(2025, 1, 15))
config.CREDIT_EXPIRY_ENABLED = False
out = run()
check("kill switch off: nothing happens and the status says so", out.status == "disabled" and DB.balances["A"] == D("10"))
out = run(dry_run=True)
check("kill switch off: a dry run still reports", out.status == "ok" and out.total_usd == D("10"))
config.CREDIT_EXPIRY_ENABLED = True

# drift guard
fresh()
DB.balances["D"] = D("0")
DB.add_row("D", "deposit", "10", at(2025, 1, 15))
DB.balances["D"] = D("12")  # someone edited the balance by hand
out = run()
check("drift: the account is skipped, nothing written, and it needs a human", not out.expired and out.skipped[0]["reason"] == ce.SKIP_BALANCE_MISMATCH
      and out.has_problems and DB.balances["D"] == D("12") and len(DB.ledger_of("D")) == 1)

# an earlier expiry row that disagrees with the rules
fresh()
DB.balances["E"] = D("0")
DB.add_row("E", "deposit", "10", at(2025, 1, 15))
DB.add_row("E", "adjustment", "-4", at(2026, 1, 16), "Expired credits (hand edited)")
out = run()
check("an expiry row that does not match the rules: skipped for a human", out.skipped and out.skipped[0]["reason"] == ce.SKIP_EXPIRY_MISMATCH and out.has_problems)

# stale: a charge lands between reading the ledger and the database function
fresh()
DB.balances["F"] = D("0")
DB.add_row("F", "deposit", "10", at(2025, 1, 15))
fired = []


def charge_arrives(db, body):
    if not fired:
        fired.append(1)
        db.add_row("F", "usage", "-1", db.clock, "Kael Beta request")


DB.before_rpc = charge_arrives
out = run()
check("stale ledger: the database function refuses, nothing is removed, a retry is expected", out.skipped and out.skipped[0]["reason"] == ce.SKIP_STALE
      and not out.has_problems and DB.balances["F"] == D("9") and DB.drift("F") == 0)
DB.before_rpc = None
out = run()
check("the next run recomputes and expires what is really left (9)", D(out.expired[0]["amount_usd"]) == D("9") and DB.balances["F"] == 0 and DB.drift("F") == 0)

# one failing account does not stop the others
fresh()
for u in ("G1", "G2"):
    DB.balances[u] = D("0")
    DB.add_row(u, "deposit", "4", at(2025, 1, 15))
DB.fail_for_user = {"G1"}
out = run()
check("a database error on one account is reported and the other still runs",
      [e["user_id"] for e in out.expired] == ["G2"] and out.skipped and out.skipped[0]["user_id"] == "G1" and DB.balances["G2"] == 0)

# the result is JSON-safe
import json  # noqa: E402
json.dumps(out.to_dict())
check("to_dict() is JSON-safe", True)

# not configured
real_enabled = billing._enabled
billing._enabled = lambda: False
out = run()
check("without Supabase configured the run reports an error and does nothing", out.status == "error")
billing._enabled = real_enabled

print(f"\nALL CHECKS PASSED ({checks})")
