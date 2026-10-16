"""12-month credit expiry (added 2026-10-13).

THE RULE (Terms of Service, "Credits and Billing"). Credits expire 12 months
after the day they are added to an account. Usage takes credits in the order
they were added (oldest first). Credits that are still unused when their 12
months end are removed from the balance. Credits are not money: they have no
cash value and cannot be withdrawn, transferred or exchanged.

HOW IT WORKS. The ledger (billing_ledger) is the record. For one account this
module replays it in time order:

  * a deposit (kind 'deposit', or a positive 'adjustment') starts a LOT: an
    amount with an expiry date, added_at + CREDIT_EXPIRY_MONTHS. If the account
    was overdrawn at that moment (see below) the deposit first pays the debt
    off and only the rest becomes a lot;
  * usage (kind 'usage', or a negative 'adjustment' that is not an expiry) uses
    up lots oldest-first. Usage with no lot left to take from is DEBT: balances
    may go slightly negative by design (app/billing.py), and the next deposit
    pays that off first;
  * an expiry row (kind 'adjustment', negative, description starting
    "Expired credits") removes whatever is left of every lot that was past its
    expiry date at that row's own time.

After the last row, any lot that is past its expiry date and still has credit is
DUE. The run writes ONE new expiry row for the total of the due lots
(public.expire_credits, migration 0017), which lowers the balance by the same
amount in the same transaction.

WHY A REPLAY, AND WHY IT USES RECORDED EXPIRIES. Expiry takes effect when the
daily run records it, not retroactively at the exact anniversary: usage in the
hours between an anniversary and the next run still used those credits, exactly
as the customer's ledger shows. The ledger is therefore the single source of
truth and a replay of it always reaches the same answer. Running the job twice
in a row is harmless: the second run finds nothing due.

SAFETY. Nothing is written unless all of these hold for the account:
  * the replay's balance equals billing_accounts.balance_usd (otherwise the
    account has drifted: the reconcile check reports that, and expiry skips it);
  * every earlier expiry row matches what the rules would have removed;
  * the ledger still has the row count the replay was computed from when the
    database function applies the expiry (expire_credits returns NULL
    otherwise; the next run recomputes). This keeps a calculation made a moment
    ago from removing credits that a request has just used.
Dry runs (POST /api/admin/expire-credits, the default) write nothing.

SCALE. The daily run only looks at accounts that have a deposit older than 12
months, and replays each one's whole ledger in pages of 1000. That is cheap now
(the first credits can only expire in late 2027). For an account with very many
usage rows it is still a handful of requests a day; if that ever becomes slow,
the replay can be moved into SQL without changing the rule.

Kill switch: config.CREDIT_EXPIRY_ENABLED (env CREDIT_EXPIRY_ENABLED=false).
Changing CREDIT_EXPIRY_MONTHS changes a legal promise: change the Terms first.
"""

import calendar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from . import billing, config

CREDIT_EXPIRY_MONTHS = 12

# Every expiry ledger row's description starts with this. The replay recognises
# expiry rows by it (together with kind 'adjustment' and a negative amount).
EXPIRY_DESCRIPTION_PREFIX = "Expired credits"

_PAGE_SIZE = 1000
_QUANT = Decimal("0.00001")
_ZERO = Decimal("0")

# Skip reasons (stable strings: the admin report and the tests use them).
SKIP_STALE = "ledger changed while the expiry was being computed; will retry on the next run"
SKIP_BALANCE_MISMATCH = "replayed balance differs from the account balance (drift); expiry skipped for this account"
SKIP_EXPIRY_MISMATCH = "an earlier expiry row does not match the expiry rules; expiry skipped for this account"
SKIP_NO_ACCOUNT = "no billing account row"


def add_months(moment: datetime, months: int) -> datetime:
    """`moment` plus whole calendar months. A day that does not exist in the
    target month (Feb 29, the 31st) becomes that month's last day."""
    index = moment.month - 1 + months
    year = moment.year + index // 12
    month = index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def parse_ts(value) -> datetime:
    """A Supabase timestamptz string ("2026-10-02T08:15:30.123456+00:00", or
    with a trailing Z) as an aware UTC datetime. A naive value is taken as UTC."""
    if isinstance(value, datetime):
        moment = value
    else:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def is_expiry_row(row: dict) -> bool:
    """True for a ledger row written by this module."""
    return (
        row.get("kind") == "adjustment"
        and Decimal(str(row.get("amount_usd") or 0)) < 0
        and str(row.get("description") or "").startswith(EXPIRY_DESCRIPTION_PREFIX)
    )


@dataclass
class Lot:
    """Credit added at one moment, and how much of it is still unused."""

    added_at: datetime
    expires_at: datetime
    remaining: Decimal


@dataclass
class Replay:
    """What replaying one account's ledger found (see replay())."""

    lots: list = field(default_factory=list)  # lots that still hold credit
    debt: Decimal = _ZERO  # usage that had no credit to take from
    balance: Decimal = _ZERO  # sum of the lots minus the debt
    due: list = field(default_factory=list)  # lots past their expiry date with credit left
    due_total: Decimal = _ZERO
    expiry_rows_consistent: bool = True
    problem: str | None = None


def replay(rows: list, now: datetime) -> Replay:
    """Replays `rows` (one account's ledger: dicts with kind, amount_usd,
    created_at, description) in the order given, which must be oldest first,
    and returns the account's lots, debt and what is due at `now`. Pure: no
    I/O, no clock. See the module docstring for the rules."""
    lots: list[Lot] = []
    debt = _ZERO
    consistent = True
    problem = None

    for row in rows:
        amount = Decimal(str(row.get("amount_usd") or 0))
        moment = parse_ts(row["created_at"])

        if is_expiry_row(row):
            removed = _ZERO
            for lot in lots:
                if lot.remaining > 0 and lot.expires_at <= moment:
                    removed += lot.remaining
                    lot.remaining = _ZERO
            if removed.quantize(_QUANT) != (-amount).quantize(_QUANT):
                consistent = False
                problem = f"expiry row of {-amount} at {moment.isoformat()} but the rules remove {removed}"
        elif amount > 0:
            pays_debt = min(debt, amount)
            debt -= pays_debt
            rest = amount - pays_debt
            if rest > 0:
                lots.append(Lot(moment, add_months(moment, CREDIT_EXPIRY_MONTHS), rest))
        elif amount < 0:
            need = -amount
            for lot in lots:  # oldest first
                if need <= 0:
                    break
                if lot.remaining > 0:
                    take = min(lot.remaining, need)
                    lot.remaining -= take
                    need -= take
            debt += need

    live = [lot for lot in lots if lot.remaining > 0]
    due = [lot for lot in live if lot.expires_at <= now]
    return Replay(
        lots=live,
        debt=debt,
        balance=sum((lot.remaining for lot in live), _ZERO) - debt,
        due=due,
        due_total=sum((lot.remaining for lot in due), _ZERO),
        expiry_rows_consistent=consistent,
        problem=problem,
    )


def expiry_description(due: list) -> str:
    """The ledger text for one expiry row. Content-free and without any
    personal data: the months and the amount per lot only."""
    parts = [f"{lot.added_at:%Y-%m-%d} ({billing.format_usd(billing._quantize(lot.remaining))})" for lot in due]
    shown = ", ".join(parts[:5]) + (f" and {len(parts) - 5} more" if len(parts) > 5 else "")
    return f"{EXPIRY_DESCRIPTION_PREFIX} ({CREDIT_EXPIRY_MONTHS} months after they were added on {shown})"


# ---------------------------------------------------------------------------
# Database access
# ---------------------------------------------------------------------------

async def _fetch_ledger(client: httpx.AsyncClient, user_id: str) -> list:
    """Every ledger row of one account, oldest first, in pages."""
    rows: list = []
    offset = 0
    while True:
        resp = await client.get(
            f"{config.SUPABASE_URL}/rest/v1/billing_ledger",
            headers=billing._headers(),
            params={
                "select": "kind,amount_usd,created_at,description",
                "user_id": f"eq.{user_id}",
                "order": "created_at.asc,id.asc",
                "limit": str(_PAGE_SIZE),
                "offset": str(offset),
            },
        )
        resp.raise_for_status()
        page = resp.json()
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            return rows
        offset += _PAGE_SIZE


async def _fetch_balance(client: httpx.AsyncClient, user_id: str) -> Decimal | None:
    resp = await client.get(
        f"{config.SUPABASE_URL}/rest/v1/billing_accounts",
        headers=billing._headers(),
        params={"select": "balance_usd", "user_id": f"eq.{user_id}", "limit": "1"},
    )
    resp.raise_for_status()
    found = resp.json()
    return Decimal(str(found[0]["balance_usd"])) if found else None


async def _candidate_users(client: httpx.AsyncClient, cutoff: datetime) -> list:
    """Accounts that have credit added before `cutoff`: the only ones that can
    have anything past its expiry date."""
    users: set = set()
    offset = 0
    while True:
        resp = await client.get(
            f"{config.SUPABASE_URL}/rest/v1/billing_ledger",
            headers=billing._headers(),
            params={
                "select": "user_id",
                "kind": "in.(deposit,adjustment)",
                "amount_usd": "gt.0",
                "created_at": f"lt.{cutoff.isoformat()}",
                "order": "user_id.asc,created_at.asc",
                "limit": str(_PAGE_SIZE),
                "offset": str(offset),
            },
        )
        resp.raise_for_status()
        page = resp.json()
        users.update(r["user_id"] for r in page if r.get("user_id"))
        if len(page) < _PAGE_SIZE:
            return sorted(users)
        offset += _PAGE_SIZE


async def _apply_expiry(client: httpx.AsyncClient, user_id: str, amount: Decimal, description: str, ledger_rows: int):
    """public.expire_credits (migration 0017). Returns the new balance, or None
    when the database found the ledger had changed since it was read."""
    resp = await client.post(
        f"{config.SUPABASE_URL}/rest/v1/rpc/expire_credits",
        headers=billing._headers(),
        json={
            "p_user_id": user_id,
            "p_amount": float(billing._quantize(amount)),
            "p_description": description,
            "p_ledger_rows": ledger_rows,
        },
    )
    resp.raise_for_status()
    value = resp.json()
    return None if value is None else Decimal(str(value))


# ---------------------------------------------------------------------------
# A run
# ---------------------------------------------------------------------------

@dataclass
class ExpiryOutcome:
    """Result of one expiry run.

    status: "ok" (the run happened; accounts it could not handle are in
    `skipped`), "disabled" (the kill switch is off and this was not a dry run) or
    "error" (the run could not start; see `error`)."""

    status: str
    checked_at: str
    dry_run: bool
    accounts_checked: int = 0
    expired: list = field(default_factory=list)  # {"user_id", "amount_usd", "lots": [{"added_at","amount_usd"}]}
    skipped: list = field(default_factory=list)  # {"user_id", "reason"}
    error: str | None = None

    @property
    def total_usd(self) -> Decimal:
        return sum((Decimal(e["amount_usd"]) for e in self.expired), _ZERO)

    @property
    def has_problems(self) -> bool:
        """A skip that needs a human (drift, or an expiry row that does not
        match the rules), as opposed to a harmless retry-next-run."""
        return any(s["reason"] != SKIP_STALE for s in self.skipped)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "checked_at": self.checked_at,
            "dry_run": self.dry_run,
            "expiry_months": CREDIT_EXPIRY_MONTHS,
            "accounts_checked": self.accounts_checked,
            "accounts_expired": len(self.expired),
            "total_expired_usd": str(self.total_usd),
            "expired": self.expired,
            "skipped": self.skipped,
            "error": self.error,
        }


def _log(message: str) -> None:
    print(f"[credit_expiry] {message}", flush=True)


async def expire_account(client: httpx.AsyncClient, user_id: str, now: datetime, dry_run: bool):
    """Expires one account's due credits. Returns ("expired", item) when credits
    were (or, in a dry run, would be) removed, ("nothing", None) when none were
    due, or ("skipped", reason). Raises on a database error."""
    ledger = await _fetch_ledger(client, user_id)
    actual = await _fetch_balance(client, user_id)
    if actual is None:
        return "skipped", SKIP_NO_ACCOUNT

    result = replay(ledger, now)
    if not result.expiry_rows_consistent:
        _log(f"SKIPPED user={user_id}: {result.problem}")
        return "skipped", SKIP_EXPIRY_MISMATCH
    if result.balance.quantize(_QUANT) != actual.quantize(_QUANT):
        _log(f"SKIPPED user={user_id}: replayed balance {result.balance} vs account balance {actual}")
        return "skipped", SKIP_BALANCE_MISMATCH
    if result.due_total <= 0:
        return "nothing", None

    item = {
        "user_id": user_id,
        "amount_usd": str(billing._quantize(result.due_total)),
        "lots": [{"added_at": lot.added_at.isoformat(), "amount_usd": str(billing._quantize(lot.remaining))} for lot in result.due],
    }
    if dry_run:
        return "expired", item
    new_balance = await _apply_expiry(client, user_id, result.due_total, expiry_description(result.due), len(ledger))
    if new_balance is None:
        return "skipped", SKIP_STALE
    _log(f"EXPIRED user={user_id} amount_usd={item['amount_usd']} lots={len(result.due)} new_balance_usd={new_balance}")
    return "expired", item


async def run_expiry(now: datetime | None = None, dry_run: bool = False) -> ExpiryOutcome:
    """The whole run: every account with credit older than the expiry period.
    Never raises (other than cancellation): a failure to start becomes
    status "error", a failure on one account becomes a `skipped` entry and the
    others still run."""
    now = now or datetime.now(timezone.utc)
    outcome = ExpiryOutcome(status="ok", checked_at=now.isoformat(), dry_run=dry_run)

    if not dry_run and not config.CREDIT_EXPIRY_ENABLED:
        outcome.status = "disabled"
        _log("disabled (CREDIT_EXPIRY_ENABLED is off); nothing done")
        return outcome
    if not billing._enabled():
        outcome.status = "error"
        outcome.error = "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not configured — nothing to expire."
        return outcome
    if billing.DEFAULT_STARTING_BALANCE != 0:
        # The replay assumes accounts start empty, as they do today. A starting
        # balance would need to become a lot dated at account creation.
        outcome.status = "error"
        outcome.error = "DEFAULT_STARTING_BALANCE is not zero; credit expiry does not handle a starting balance."
        return outcome

    cutoff = add_months(now, -CREDIT_EXPIRY_MONTHS)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            candidates = await _candidate_users(client, cutoff)
            outcome.accounts_checked = len(candidates)
            for user_id in candidates:
                try:
                    kind, detail = await expire_account(client, user_id, now, dry_run)
                except Exception as e:  # noqa: BLE001 — one bad account must not stop the others
                    _log(f"FAILED user={user_id}: {type(e).__name__}")
                    outcome.skipped.append({"user_id": user_id, "reason": f"database error ({type(e).__name__}); will retry on the next run"})
                    continue
                if kind == "expired":
                    outcome.expired.append(detail)
                elif kind == "skipped":
                    outcome.skipped.append({"user_id": user_id, "reason": detail})
    except Exception as e:  # noqa: BLE001 — could not even list the accounts
        outcome.status = "error"
        outcome.error = f"{type(e).__name__}: {str(e)[:200]}"
        _log(f"run failed: {outcome.error}")
        return outcome

    _log(
        f"{'DRY RUN ' if dry_run else ''}checked={outcome.accounts_checked} "
        f"expired={len(outcome.expired)} total_usd={outcome.total_usd} skipped={len(outcome.skipped)}"
    )
    return outcome
