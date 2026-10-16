"""Plain-script test of the whole email system, with no network and no real
sends: the layout and every template (app/email_layout.py,
app/email_templates.py), delivery (app/email_service.py, driven against a
fake HTTP client), the signup / forgot-password / resend-confirmation logic
(app/auth_email.py, driven against fakes of supabase_client and
email_service), the rate-limit additions (app/rate_limit.py), and the
account-event emails (app/account_emails.py, app/admin.py hooks).

Run: python test_email_system.py   (needs the normal backend requirements
installed; dummy env vars are filled in below). Prints ALL CHECKS PASSED.

To look at the emails instead of testing them, run
render_email_previews.py.
"""
import asyncio, contextlib, io, os, sys
from decimal import Decimal

for k in ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_ANON_KEY", "API_KEY_PEPPER", "OPENROUTER_API_KEY", "RESEND_API_KEY", "FRONTEND_URL"]:
    os.environ.setdefault(k, "x" if k != "FRONTEND_URL" else "https://platform.quancis.space")
os.environ["SUPABASE_URL"] = "http://x"
os.environ["FRONTEND_URL"] = "https://platform.quancis.space"

from fastapi import HTTPException
from app import balance_alerts, billing, config, email_layout as el, email_templates as et, email_service, auth_email, rate_limit, account_emails, admin as admin_module
from app import supabase_client as sc
import render_email_previews as previews

fails = 0


def check(name, cond):
    global fails
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails += 1


def code_of(exc):
    return exc.status_code if isinstance(exc, HTTPException) else None


async def raises(coro):
    try:
        await coro
        return None
    except HTTPException as e:
        return e
    except Exception as e:  # noqa: BLE001
        return e


PAYLOADS = [
    '<img src=x onerror=alert(1)>',
    '"><a href="//evil.example">x</a>',
    '&lt;b&gt;already escaped&lt;/b&gt;',
    "A" * 5000,
    "line one\nline two",
]

# ---------------------------------------------------------------------
# 1. Layout + every template
# ---------------------------------------------------------------------
LEGACY = ["#0f172a", "#475569", "#94a3b8", "border-radius:12px", ">QUANCIS<"]
for name, build in previews.SAMPLES.items():
    e = build()
    h = e.html
    check(f"{name}: has subject + html", bool(e.subject) and bool(h))
    check(f"{name}: doctype, lang, viewport, color-scheme", h.startswith("<!DOCTYPE html>") and 'lang="en"' in h and 'name="viewport"' in h and 'name="color-scheme"' in h)
    check(f"{name}: hidden preheader present", "display:none" in h and "mso-hide:all" in h)
    check(f"{name}: platform ink colour, no legacy palette", "#16181A" in h and not any(x in h for x in LEGACY))
    check(f"{name}: site fonts requested (Inter + JetBrains Mono)", "family=Inter" in h and "JetBrains+Mono" in h)
    check(f"{name}: brand mark + 'uancis' wordmark", 'aria-label="Quancis"' in h and ">uancis<" in h and "#E4002B" in h)
    check(f"{name}: footer has Terms, Privacy, support, and NO company-description line", "Terms of Service" in h and "Privacy Policy" in h and "support@quancis.space" in h and "Limpopo" not in h and "sole proprietorship" not in h and "trading name" not in h)
    check(f"{name}: no script/form/remote image", not any(x in h.lower() for x in ("<script", "javascript:", "<form", "<img")))
    txt = el.html_to_text(h)
    check(f"{name}: plain text says Quancis, no markup/debris", txt.startswith("Quancis") and "<" not in txt.replace("<-", "") or "&lt;" in h)
    check(f"{name}: subject has no angle brackets", "<" not in e.subject)

# escaping: user-controlled values never reach the markup raw
for payload in PAYLOADS:
    for tpl_name, build in [
        ("confirm_signup", lambda p=payload: et.confirm_signup("https://x.test/a?b=1&c=2", p)),
        ("welcome", lambda p=payload: et.welcome(p)),
        ("low_balance", lambda p=payload: et.low_balance(p, "4.20", "5.00")),
        ("account_suspended", lambda p=payload: et.account_suspended(p)),
        ("api_key_created", lambda p=payload: et.api_key_created("Ann", p, "now")),
        ("admin_check_failed", lambda p=payload: et.admin_check_failed(p)),
    ]:
        h = build().html
        check(f"escape {tpl_name} vs {payload[:18]!r}: no raw <img / evil anchor", "<img" not in h.lower() and 'href="//evil' not in h)
e = et.confirm_signup("https://x.test/a?b=1&c=2", "Ann Lee Smith")
check("action link '&' is &amp; in the href", 'href="https://x.test/a?b=1&amp;c=2"' in e.html)
check("action link verbatim in the plain text", "https://x.test/a?b=1&c=2" in el.html_to_text(e.html))
check("greeting uses FIRST name only", "Hi Ann," in el.html_to_text(e.html) and "Lee" not in el.html_to_text(e.html))
check("5,000-char name is truncated to 60", "A" * 61 not in et.welcome("A" * 5000).html)
check("missing name -> plain 'Hi,'", "Hi," in el.html_to_text(et.welcome(None).html))
bad = None
try:
    el.render(subject="s", preheader="p", title="t", blocks=[object()])
except TypeError as ex:
    bad = ex
check("unknown block type raises", bad is not None)
d = previews.SAMPLES["admin_drift"]().html
check("drift email keeps the account id and formatted drift (existing integration test relies on it)", "0b9f-sample-user-id" in d and "-$0.20000" in d)
check("credits email shows bonus row when given", "Promotional bonus" in et.credits_added("A", "25.00", "37.50", "now", bonus="12.50").html)
check("credits email omits bonus row when absent", "Promotional bonus" not in et.credits_added("A", "25.00", "25.00", "now").html)
check("every public template is in previews.SAMPLES", all(
    n in previews.SAMPLES for n in dir(et) if not n.startswith("_") and callable(getattr(et, n)) and getattr(getattr(et, n), "__module__", "") == et.__name__
))

# ---------------------------------------------------------------------
# 2. Delivery: send_email against a fake HTTP client
# ---------------------------------------------------------------------
import httpx  # noqa: E402

calls = []
script = []  # queue of ("resp", status, json) or ("raise", ExceptionInstance)


class FakeResp:
    def __init__(self, status, body):
        self.status_code, self._b = status, body

    def json(self):
        return self._b


class FakeClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        calls.append({"url": url, "headers": headers, "json": json})
        item = script.pop(0)
        if item[0] == "raise":
            raise item[1]
        return FakeResp(item[1], item[2])


_real_client, _real_sleep = httpx.AsyncClient, email_service.asyncio.sleep
httpx.AsyncClient = FakeClient


async def _nosleep(_):
    return None


email_service.asyncio.sleep = _nosleep
logs = []


config.RESEND_API_KEY = "re_test"
config.RESEND_FROM_EMAIL = "Quancis <noreply@quancis.space>"
config.RESEND_REPLY_TO = ""


async def delivery_tests():
    calls.clear(); script[:] = [("resp", 200, {"id": "abc"})]
    rid = await email_service.send_email("victim@example.com", "Subj", "<p>Hi</p>")
    check("3-arg send_email still works and returns the Resend id", rid == "abc" and len(calls) == 1)
    p = calls[0]["json"]
    check("payload carries a derived plain-text part", p["text"].strip() == "Hi" and p["html"] == "<p>Hi</p>")
    check("no reply_to when unset", "reply_to" not in p)

    config.RESEND_REPLY_TO = "support@quancis.space"
    calls.clear(); script[:] = [("resp", 200, {"id": "x"})]
    await email_service.send_email("a@example.com", "S", "<p>x</p>", tags={"category": "auth", "template": "t"}, idempotency_key="k1", text="plain")
    p = calls[0]["json"]
    check("reply_to from config is sent", p["reply_to"] == "support@quancis.space")
    check("explicit text wins over derived", p["text"] == "plain")
    check("tags sent as name/value pairs", p["tags"] == [{"name": "category", "value": "auth"}, {"name": "template", "value": "t"}])
    check("Idempotency-Key header sent", calls[0]["headers"]["Idempotency-Key"] == "k1")
    config.RESEND_REPLY_TO = ""

    calls.clear(); script[:] = [("resp", 429, {"name": "rate_limit_exceeded", "message": "slow down"}), ("resp", 200, {"id": "ok"})]
    check("429 then 200 is retried and succeeds", await email_service.send_email("a@example.com", "S", "<p>x</p>") == "ok" and len(calls) == 2)

    calls.clear(); script[:] = [("resp", 400, {"name": "validation_error", "message": "domain not verified"})]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        err = await raises(email_service.send_email("secret.person@example.com", "S", "<p>x</p>"))
    logs.clear(); logs.append(buf.getvalue())
    check("400 is NOT retried", len(calls) == 1)
    check("400 raises HTTPException 500", code_of(err) == 500)
    joined = " ".join(logs)
    check("failure log is non-empty and tagged [email]", joined.startswith("[email]"))
    check("failure log carries Resend's reason", "validation_error" in joined and "domain not verified" in joined)
    check("failure log never contains the recipient", "secret.person" not in joined and "example.com" not in joined)

    calls.clear(); script[:] = [("raise", httpx.TransportError("boom"))]
    err = await raises(email_service.send_email("a@example.com", "S", "<p>x</p>"))
    check("network error without idempotency key: no retry", code_of(err) == 500 and len(calls) == 1)
    calls.clear(); script[:] = [("raise", httpx.TransportError("boom")), ("resp", 200, {"id": "r"})]
    check("network error WITH idempotency key: retried", await email_service.send_email("a@example.com", "S", "<p>x</p>", idempotency_key="k") == "r" and len(calls) == 2)

    config.RESEND_API_KEY = ""
    err = await raises(email_service.send_email("a@example.com", "S", "<p>x</p>"))
    check("no RESEND_API_KEY -> HTTPException 500", code_of(err) == 500)
    config.RESEND_API_KEY = "re_test"


asyncio.run(delivery_tests())
httpx.AsyncClient, email_service.asyncio.sleep = _real_client, _real_sleep

# ---------------------------------------------------------------------
# 3. auth_email flows against fakes
# ---------------------------------------------------------------------
sent = []
state = {"users": {}, "pw_updates": [], "created": [], "fail_send": False}


async def fake_send(to, subject, html, **kw):
    if state["fail_send"]:
        raise HTTPException(status_code=500, detail="x")
    sent.append({"to": to, "subject": subject, "html": html, **kw})
    return "id"


async def fake_find(email):
    return state["users"].get(email)


async def fake_create(email, password, name=None):
    u = {"id": "u-" + email, "email": email, "email_confirmed_at": None, "user_metadata": {"full_name": name}}
    state["users"][email] = u
    state["created"].append((email, name))
    return u


async def fake_update_pw(uid, pw):
    state["pw_updates"].append(uid)


async def fake_acceptance(*a, **k):
    return None


async def fake_link(kind, email, redirect_to=None):
    return {"action_link": f"https://proj.supabase.co/auth/v1/verify?token=T&type={kind}", "properties": {"hashed_token": "HASH123", "verification_type": kind}}


email_service.send_email = fake_send
sc.find_auth_user_by_email, sc.create_auth_user, sc.update_user_password = fake_find, fake_create, fake_update_pw
sc.record_legal_acceptance, sc.generate_action_link = fake_acceptance, fake_link
config.AUTH_EMAIL_HOURLY_CAP = 0
config.ADMIN_ALERT_EMAIL = ""
config.AUTH_LINK_MODE = "supabase"


async def signup(email="new@example.com", name="Ann Lee", password="password1"):
    return await auth_email.signup(email, password, name, terms_accepted=True)


async def auth_tests():
    for bad_name, why in [("<b>x</b>", "angle brackets"), ("A" * 81, "81 chars"), ("", "empty"), ("   ", "blank"), ("ok\x00bad", "control char"), ("evil\u202eterces", "bidi override"), (123, "non-string")]:
        err = await raises(signup(name=bad_name))
        check(f"signup rejects name: {why}", code_of(err) == 400)
    check("no account was created by any rejected name", state["created"] == [])
    r = await signup(email="a@example.com", name="  Ann \n Lee  ")
    check("valid signup returns the generic message", r["message"] == auth_email.GENERIC_SIGNUP_MESSAGE)
    check("name whitespace collapsed before it is stored", state["created"][-1] == ("a@example.com", "Ann Lee"))
    check("confirmation email sent once, to the right address, with tags", len(sent) == 1 and sent[0]["to"] == "a@example.com" and sent[0]["tags"] == {"category": "auth", "template": "confirm_signup"})
    check("default link mode uses GoTrue's action_link (unchanged behaviour)", "proj.supabase.co/auth/v1/verify" in sent[0]["html"])

    sent.clear(); config.AUTH_LINK_MODE = "confirm_page"
    await signup(email="b@example.com")
    check("confirm_page mode links to the frontend origin", "https://platform.quancis.space/auth/confirm?token_hash=HASH123&amp;type=magiclink" in sent[0]["html"])
    check("confirm_page mode: no supabase.co host in the email", "supabase.co" not in sent[0]["html"])
    sent.clear()
    async def link_no_hash(kind, email, redirect_to=None):
        return {"action_link": "https://proj.supabase.co/v?t=1", "properties": {}}
    sc.generate_action_link = link_no_hash
    await signup(email="c@example.com")
    check("confirm_page mode falls back to the classic link when GoTrue omits the hash", "proj.supabase.co/v?t=1" in sent[0]["html"])
    sc.generate_action_link, config.AUTH_LINK_MODE = fake_link, "supabase"

    # forgot password
    sent.clear()
    state["users"]["d@example.com"] = {"id": "ud", "email": "d@example.com", "email_confirmed_at": "2026-01-01", "app_metadata": {}}
    await auth_email.forgot_password("d@example.com")
    check("reset email sent for a confirmed account", len(sent) == 1 and sent[0]["subject"] == "Reset your Quancis password" and sent[0]["tags"]["template"] == "reset_password")
    sent.clear(); await auth_email.forgot_password("nobody@example.com")
    check("no email for an unknown address", sent == [])

    # already registered / admin notices
    sent.clear(); await signup(email="d@example.com")
    check("signup on a confirmed address sends the already-registered notice", len(sent) == 1 and "someone tried" in sent[0]["subject"].lower())
    state["users"]["adm@example.com"] = {"id": "ua", "email": "adm@example.com", "email_confirmed_at": "2026-01-01", "app_metadata": {"role": "admin"}}
    sent.clear(); await signup(email="adm@example.com")
    check("signup on an admin address sends the admin notice only", len(sent) == 1 and "admin account" in sent[0]["subject"])
    state["fail_send"] = True
    r = await signup(email="adm@example.com")
    check("admin/already-registered notices are best-effort (send failure swallowed)", r["message"] == auth_email.GENERIC_SIGNUP_MESSAGE)
    state["fail_send"] = False

    # resend confirmation
    sent.clear(); state["pw_updates"].clear()
    state["users"]["e@example.com"] = {"id": "ue", "email": "e@example.com", "email_confirmed_at": None, "app_metadata": {}, "user_metadata": {"full_name": "Eve Adams"}}
    r = await auth_email.resend_confirmation("e@example.com")
    check("resend: unconfirmed account gets a fresh confirmation email", len(sent) == 1 and sent[0]["tags"]["template"] == "confirm_signup" and "Hi Eve," in el.html_to_text(sent[0]["html"]))
    check("resend: never touches the password", state["pw_updates"] == [])
    check("resend: generic message", r["message"] == auth_email.GENERIC_RESEND_MESSAGE)
    for who, expect in [("d@example.com", "confirmed"), ("adm@example.com", "admin"), ("ghost@example.com", "unknown")]:
        sent.clear(); r2 = await auth_email.resend_confirmation(who)
        check(f"resend: {expect} account -> same generic response, no email", sent == [] and r2 == r)
    state["fail_send"] = True
    r3 = await auth_email.resend_confirmation("e@example.com")
    check("resend: a failed send is swallowed (identical response)", r3 == r)
    state["fail_send"] = False

    # global budget
    config.AUTH_EMAIL_HOURLY_CAP = 2
    rate_limit._buckets.pop("auth-email:global", None)
    sent.clear(); state["users"].clear(); state["created"].clear()
    for i in range(4):
        r4 = await signup(email=f"cap{i}@example.com")
    check("budget: only the first 2 signups sent an email", len(sent) == 2)
    check("budget: after the cap, no junk accounts are created either", len(state["created"]) == 2)
    check("budget: response is still the generic message", r4["message"] == auth_email.GENERIC_SIGNUP_MESSAGE)
    config.AUTH_EMAIL_HOURLY_CAP = 0


asyncio.run(auth_tests())

# ---------------------------------------------------------------------
# 4. rate_limit additions
# ---------------------------------------------------------------------
k = rate_limit.canonical_email_key
check("gmail dots collapse", k("a.b.c@gmail.com") == k("abc@gmail.com") == "abc@gmail.com")
check("gmail +tag and googlemail alias collapse", k("ab+promo@googlemail.com") == "ab@gmail.com")
check("non-gmail keeps dots but drops +tag", k("a.b+x@Example.com") == "a.b@example.com")
check("different mailboxes stay different", k("a@gmail.com") != k("b@gmail.com"))
config.AUTH_EMAIL_HOURLY_CAP = 3
rate_limit._buckets.pop("auth-email:global", None)
check("budget allows up to the cap then refuses", [rate_limit.auth_email_budget_allows() for _ in range(5)] == [True, True, True, False, False])
config.AUTH_EMAIL_HOURLY_CAP = 0
check("cap of 0 disables the budget", all(rate_limit.auth_email_budget_allows() for _ in range(10)))

# ---------------------------------------------------------------------
# 5. account_emails + admin hooks
# ---------------------------------------------------------------------
async def account_tests():
    sent.clear()
    user = {"id": "u1", "email": "u1@example.com", "user_metadata": {"full_name": "Una Park"}}
    check("suspended notice sent", await account_emails.notify_suspended(user) and sent[-1]["subject"] == "Your Quancis account has been suspended" and sent[-1]["tags"]["category"] == "account")
    check("reactivated notice sent", await account_emails.notify_reactivated(user) and "reactivated" in sent[-1]["subject"])
    check("key-created notice sent, name only", await account_emails.notify_api_key_created(user, "prod") and "prod" in sent[-1]["html"])
    sent.clear()
    check("never raises on bad input", await account_emails.notify_api_key_created(user, 12345) is not None and await account_emails.notify_suspended(None) is False and await account_emails.notify_credits_added(user, "x", "y") is False)
    sent.clear(); state["fail_send"] = True
    check("send failure returns False instead of raising", await account_emails.notify_suspended(user) is False)
    state["fail_send"] = False
    config.RESEND_API_KEY = ""
    sent.clear()
    check("no-op when email delivery is not configured", await account_emails.notify_suspended(user) is False and sent == [])
    config.RESEND_API_KEY = "re_test"

    # admin hooks
    users = {"u-active": {"id": "u-active", "email": "act@example.com", "user_metadata": {"name": "Act"}, "banned_until": None, "app_metadata": {}},
             "u-susp": {"id": "u-susp", "email": "sus@example.com", "user_metadata": {}, "banned_until": "2999-01-01T00:00:00Z", "app_metadata": {}},
             "u-admin": {"id": "u-admin", "email": "adm@example.com", "app_metadata": {"role": "admin"}}}
    async def get_user(uid): return users.get(uid)
    async def set_ban(uid, d): return None
    async def revoke_all(uid): return 2
    async def admin_credit(uid, amount, desc): return Decimal("37.50")
    sc.get_auth_user, sc.set_user_ban = get_user, set_ban
    admin_module.api_keys.revoke_all_active_keys = revoke_all
    admin_module.billing.admin_credit_account = admin_credit

    sent.clear(); r = await admin_module.suspend_user("u-active")
    check("suspend: still returns the same result", r == {"user_id": "u-active", "status": "suspended", "api_keys_revoked": 2})
    check("suspend: emails the user once", len(sent) == 1 and sent[0]["to"] == "act@example.com" and "suspended" in sent[0]["subject"])
    sent.clear(); await admin_module.suspend_user("u-susp")
    check("suspend: already-suspended account is NOT emailed again", sent == [])
    err = await raises(admin_module.suspend_user("u-admin"))
    check("suspend: admin accounts still refused (403), no email", code_of(err) == 403 and sent == [])
    sent.clear(); await admin_module.activate_user("u-susp")
    check("activate: a suspended account gets the reactivation email", len(sent) == 1 and "reactivated" in sent[0]["subject"])
    sent.clear(); await admin_module.activate_user("u-active")
    check("activate: an already-active account gets nothing", sent == [])
    state["fail_send"] = True
    r = await admin_module.suspend_user("u-active")
    check("suspend still succeeds when the email send fails", r["status"] == "suspended")
    state["fail_send"] = False
    sent.clear(); r = await admin_module.credit_user("u-active", 25, "boss@example.com")
    check("credit: result shape unchanged", r == {"user_id": "u-active", "credited_usd": "25", "new_balance_usd": "37.50", "self_credit": False})
    check("credit: receipt emailed with amount and new balance", len(sent) == 1 and "+$25.00" in sent[0]["html"] and "$37.50" in sent[0]["html"])
    check("credit: no bonus row (the deposit-match promotion is gone)", "Promotional bonus" not in sent[0]["html"])


asyncio.run(account_tests())

# ---------------------------------------------------------------------
# 6. Balance emails (app/balance_alerts.py) + the billing hook
# ---------------------------------------------------------------------
async def balance_tests():
    meta_on = {"full_name": "Una Park", "low_balance_alert_enabled": True, "low_balance_alert_threshold_usd": 10}
    store = {"user": {"id": "u1", "email": "u1@example.com", "user_metadata": dict(meta_on), "banned_until": None}}
    lookups, writes = [], []

    async def get_user(uid):
        lookups.append(uid)
        return store["user"]

    async def update_meta(uid, meta):
        writes.append((uid, meta))

    sc.get_auth_user, sc.update_user_metadata = get_user, update_meta
    config.LOW_BALANCE_ALERTS_ENABLED, config.RESEND_API_KEY = True, "re_test"

    def reset():
        sent.clear(); lookups.clear(); writes.clear(); balance_alerts._cache.clear()
        store["user"] = {"id": "u1", "email": "u1@example.com", "user_metadata": dict(meta_on), "banned_until": None}
        state["fail_send"] = False

    D = Decimal
    reset(); await balance_alerts.on_charge("u1", D("10.50"), D("9.80"))
    check("low balance: crossing the threshold sends one email", len(sent) == 1 and sent[0]["subject"] == "Your Quancis balance is running low" and sent[0]["to"] == "u1@example.com")
    check("low balance: email shows balance and threshold, greets by first name", "$9.80" in sent[0]["html"] and "$10.00" in sent[0]["html"] and "Hi Una," in el.html_to_text(sent[0]["html"]))
    check("low balance: tagged for Resend", sent[0]["tags"] == {"category": "billing", "template": "low_balance"})
    check("low balance: sent-flag written (so the daily scan does not duplicate), other metadata kept", len(writes) == 1 and "low_balance_alert_sent_at" in writes[0][1] and writes[0][1]["full_name"] == "Una Park")

    reset(); await balance_alerts.on_charge("u1", D("9.90"), D("9.80"))
    check("low balance: already below the threshold -> no email", sent == [])
    reset(); store["user"]["user_metadata"]["low_balance_alert_sent_at"] = "2026-10-01T00:00:00+00:00"
    await balance_alerts.on_charge("u1", D("10.50"), D("9.80"))
    check("low balance: a NEW crossing emails again even if an old sent-flag exists (topped up and dropped again)", len(sent) == 1)
    reset(); store["user"]["user_metadata"]["low_balance_alert_enabled"] = False
    await balance_alerts.on_charge("u1", D("10.50"), D("9.80"))
    check("low balance: alert switched off -> no email", sent == [])
    reset(); store["user"]["user_metadata"]["low_balance_alert_threshold_usd"] = True
    await balance_alerts.on_charge("u1", D("10.50"), D("9.80"))
    check("low balance: a boolean is not a threshold", sent == [])
    reset(); store["user"]["banned_until"] = "2999-01-01T00:00:00Z"
    await balance_alerts.on_charge("u1", D("10.50"), D("9.80"))
    check("low balance: suspended account -> no email", sent == [])
    reset(); state["fail_send"] = True
    await balance_alerts.on_charge("u1", D("10.50"), D("9.80"))
    check("low balance: send failure never raises and writes no sent-flag", sent == [] and writes == [])

    # the cached copy says "on" but the user has just switched it off
    reset(); await balance_alerts.on_charge("u1", D("10.50"), D("10.40"))  # warms the cache, no crossing
    store["user"]["user_metadata"]["low_balance_alert_enabled"] = False
    balance_alerts._cache["u1"] = (balance_alerts._cache["u1"][0], {**store["user"], "user_metadata": dict(meta_on)})
    await balance_alerts.on_charge("u1", D("10.50"), D("9.80"))
    check("low balance: the send is re-checked against a fresh read of the user's settings", sent == [])

    # depleted
    reset(); store["user"]["user_metadata"] = {"full_name": "Una Park"}  # no alert preferences at all
    await balance_alerts.on_charge("u1", D("0.50"), D("-0.20"))
    check("depleted: crossing to zero emails even a user with no alert preference", len(sent) == 1 and sent[0]["subject"] == "Your Quancis balance has run out" and sent[0]["tags"]["template"] == "balance_depleted")
    check("depleted: shows the balance", "-0.20" in sent[0]["html"])
    reset(); await balance_alerts.on_charge("u1", D("0.00"), D("-0.10"))
    check("depleted: already at/below zero before -> no repeat email", sent == [])

    # cost control + kill switch
    reset(); balance_alerts.schedule("u1", D("301"), D("300"))
    await asyncio.sleep(0)
    check("prefilter: a healthy balance costs no lookup and no task", lookups == [] and not balance_alerts._tasks)
    reset(); await balance_alerts.on_charge("u1", D("9.90"), D("9.80")); await balance_alerts.on_charge("u1", D("9.80"), D("9.70"))
    check("cache: repeated charges for one user look the user up once", lookups == ["u1"])
    reset(); config.LOW_BALANCE_ALERTS_ENABLED = False
    balance_alerts.schedule("u1", D("10.50"), D("9.80")); await balance_alerts.on_charge("u1", D("10.50"), D("9.80"))
    check("master switch off: nothing scheduled, nothing sent, no lookups", sent == [] and lookups == [] and not balance_alerts._tasks)
    config.LOW_BALANCE_ALERTS_ENABLED = True
    reset(); config.RESEND_API_KEY = ""
    await balance_alerts.on_charge("u1", D("10.50"), D("9.80"))
    check("email delivery not configured: nothing happens", sent == [] and lookups == [])
    config.RESEND_API_KEY = "re_test"

    # schedule() really runs on_charge in the background
    reset(); balance_alerts.schedule("u1", D("10.50"), D("9.80"))
    for _ in range(20):
        await asyncio.sleep(0)
    check("schedule: runs the check as a background task", len(sent) == 1)

    # the real charge_for_request passes (previous, new) to the hook
    class BResp:
        def __init__(self, body): self._b = body
        def raise_for_status(self): return None
        def json(self): return self._b
    class BClient(FakeClient):
        body = 9.8
        async def post(self, url, headers=None, json=None):
            calls.append({"url": url, "json": json})
            if isinstance(self.body, Exception):
                raise self.body
            return BResp(self.body)
    seen = []
    real_schedule = balance_alerts.schedule
    balance_alerts.schedule = lambda uid, prev, new: seen.append((uid, prev, new))
    config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY = "http://x", "k"
    billing.httpx.AsyncClient = BClient
    usage = {"prompt_tokens": 1000, "prompt_cache_hit_tokens": 0, "completion_tokens": 1000}
    BClient.body = 9.8
    calc = await billing.charge_for_request("u1", "kael-beta", usage, None)
    cost = calc["cost_usd"]
    check("billing hook: charge returns its normal result", calc is not None and cost > 0)
    check("billing hook: previous balance = returned new balance + this request's cost", len(seen) == 1 and seen[0][0] == "u1" and Decimal(str(seen[0][2])) == Decimal("9.8") and Decimal(str(seen[0][1])) == Decimal("9.8") + cost)
    seen.clear(); BClient.body = {"unexpected": "shape"}
    out = await billing.charge_for_request("u1", "kael-beta", usage, None)
    check("billing hook: an unexpected RPC response shape changes nothing about the charge", out is not None and seen == [])
    buf = io.StringIO()
    def boom(*a): raise RuntimeError("alerts exploded")
    balance_alerts.schedule = boom; BClient.body = 9.8
    with contextlib.redirect_stdout(buf):
        out = await billing.charge_for_request("u1", "kael-beta", usage, None)
    check("billing hook: an exception inside the alert hook never fails the charge or logs CHARGE_FAILED", out is not None and "CHARGE_FAILED" not in buf.getvalue())
    balance_alerts.schedule = real_schedule
    buf = io.StringIO(); BClient.body = httpx.TransportError("down")
    with contextlib.redirect_stdout(buf):
        out = await billing.charge_for_request("u1", "kael-beta", usage, None)
    check("billing: a genuine charge failure still reports CHARGE_FAILED and returns None (unchanged)", out is None and "CHARGE_FAILED" in buf.getvalue())
    billing.httpx.AsyncClient = _real_client


asyncio.run(balance_tests())


async def password_notice_tests():
    sent.clear()
    u = {"id": "pw-user-1", "email": "pw@example.com", "user_metadata": {"full_name": "Pat Doe"}}
    results = [await account_emails.notify_password_changed(u) for _ in range(4)]
    check("password changed: 3 notices per user per hour, then silence", results == [True, True, True, False] and len(sent) == 3)
    check("password changed: goes to the user's own address with the right template", sent[0]["to"] == "pw@example.com" and sent[0]["tags"] == {"category": "security", "template": "password_changed"} and "Hi Pat," in el.html_to_text(sent[0]["html"]))
    check("password changed: no user / no id -> False, never raises", await account_emails.notify_password_changed(None) is False and await account_emails.notify_password_changed({"email": "x@y.z"}) is False)


asyncio.run(password_notice_tests())

# ---------------------------------------------------------------------
# 7. Account deletion emails, URL safety, and the input-hardening fixes
# ---------------------------------------------------------------------
async def deletion_tests():
    sent.clear(); state["fail_send"] = False
    config.RESEND_API_KEY = "re_test"
    u = {"id": "del-1", "email": "del@example.com", "user_metadata": {"full_name": "Dee Lee"}}
    URL = "https://platform.quancis.space/account/delete/confirm?t=abc&x=1"

    check("deletion requested: sent, returns True", await account_emails.notify_deletion_requested(u, URL, 12.5) is True and len(sent) == 1)
    h = sent[0]["html"]
    check("deletion requested: right subject, tags and recipient", sent[0]["subject"] == "Confirm deleting your Quancis account" and sent[0]["tags"] == {"category": "account", "template": "account_deletion_requested"} and sent[0]["to"] == "del@example.com")
    check("deletion requested: confirm link in the button (& escaped) and in plain text", 'href="https://platform.quancis.space/account/delete/confirm?t=abc&amp;x=1"' in h and URL in el.html_to_text(h))
    check("deletion requested: shows unused balance as not refunded", "$12.50 (not refunded)" in h)
    check("deletion requested: states it can't be undone and credits aren't refunded", "can't be undone" in el.html_to_text(h) and "Unused credits are not refunded" in h)
    sent.clear(); await account_emails.notify_deletion_requested({**u, "id": "del-2"}, URL, 0)
    check("deletion requested: zero balance -> no balance row", "Unused balance" not in sent[0]["html"])
    sent.clear(); await account_emails.notify_deletion_requested({**u, "id": "del-3"}, URL)
    check("deletion requested: no balance given -> no balance row", "Unused balance" not in sent[0]["html"])

    sent.clear()
    for bad in ["javascript:alert(1)", "platform.quancis.space/x", "", None, 5, "data:text/html,x"]:
        r = await account_emails.notify_deletion_requested({**u, "id": "del-bad"}, bad)
        check(f"deletion requested: refuses non-http(s) link {bad!r}", r is False)
    check("deletion requested: nothing was sent for bad links", sent == [])
    rs = [await account_emails.notify_deletion_requested({**u, "id": "del-rl"}, URL) for _ in range(4)]
    check("deletion requested: limited to 3 per user per hour", rs == [True, True, True, False])
    sent.clear(); state["fail_send"] = True
    check("deletion requested: a send failure returns False (caller can tell the person), never raises", await account_emails.notify_deletion_requested({**u, "id": "del-f"}, URL) is False)
    state["fail_send"] = False
    check("deletion requested: no user / no id -> False", await account_emails.notify_deletion_requested(None, URL) is False and await account_emails.notify_deletion_requested({"email": "a@b.c"}, URL) is False)

    sent.clear()
    check("scheduled: sent with the date", await account_emails.notify_deletion_scheduled(u, "20 October 2026", URL) is True and "20 October 2026" in sent[0]["html"] and "Keep my account" in sent[0]["html"])
    check("scheduled: bad link or empty date -> False, nothing sent", await account_emails.notify_deletion_scheduled(u, "20 Oct", "javascript:x") is False and await account_emails.notify_deletion_scheduled(u, "  ", URL) is False and len(sent) == 1)
    sent.clear()
    check("cancelled: sent", await account_emails.notify_deletion_cancelled(u) is True and "will not be deleted" in sent[0]["subject"])
    sent.clear(); snapshot = {"email": "gone@example.com", "user_metadata": {"full_name": "Gone Person"}}
    check("deleted: works from a snapshot with no id", await account_emails.notify_account_deleted(snapshot, 3) is True and sent[0]["to"] == "gone@example.com")
    check("deleted: says personal info removed except legally required records; shows balance", "except for records we are required by law to keep" in sent[0]["html"] and "$3.00 (not refunded)" in sent[0]["html"] and "Hi Gone," in el.html_to_text(sent[0]["html"]))
    sent.clear()
    check("deleted: no email address -> False, never raises", await account_emails.notify_account_deleted({"user_metadata": {}}) is False and await account_emails.notify_account_deleted(None) is False and sent == [])
    state["fail_send"] = True
    check("deleted: a send failure returns False (the deletion itself must not be undone)", await account_emails.notify_account_deleted(snapshot) is False)
    state["fail_send"] = False

    for payload in PAYLOADS:
        for build in (lambda p=payload: et.account_deletion_requested(p, "https://x.test/a", "1.00"), lambda p=payload: et.account_deletion_scheduled(p, p, "https://x.test/a"),
                      lambda p=payload: et.account_deletion_cancelled(p), lambda p=payload: et.account_deleted(p, p, p)):
            hh = build().html
            check(f"deletion templates escape {payload[:14]!r}", "<img" not in hh.lower() and 'href="//evil' not in hh)


asyncio.run(deletion_tests())

# URL safety in the layout
for bad in ["javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html;base64,AAAA", "platform.quancis.space/x", "//evil.example/x", ""]:
    hh = el.render(subject="s", preheader="p", title="t", blocks=[el.Button("Go", bad), el.LinkFallback(bad)]).html
    check(f"layout: unsafe link {bad[:22]!r} is never emitted as an href", 'href="#"' in hh and "javascript" not in hh.lower().replace("<script", "") and 'href="data:' not in hh and 'href="//evil' not in hh)
hh = el.render(subject="s", preheader="p", title="t", blocks=[el.Button("Go", "mailto:support@quancis.space"), el.Button("Go", "http://localhost:3000/x")]).html
check("layout: mailto and http(s) links are kept", 'href="mailto:support@quancis.space"' in hh and 'href="http://localhost:3000/x"' in hh)
sus = et.account_suspended("Dee").html
check("plain text keeps the address behind a mailto button", "support@quancis.space" in el.html_to_text(sus).split("Contact support")[1].split("\n")[0])

# non-string email input: 400, not a 500
check("rate-limit key: non-string email does not raise", all(isinstance(rate_limit.canonical_email_key(v), str) for v in (5, ["a"], {"x": 1}, None, 1.5, True)))
async def input_tests():
    for bad in (5, ["a@b.c"], {"x": 1}, True):
        err = await raises(auth_email.forgot_password(bad))
        check(f"forgot_password: non-string email {bad!r} -> 400", code_of(err) == 400)
        err = await raises(auth_email.resend_confirmation(bad))
        check(f"resend_confirmation: non-string email {bad!r} -> 400", code_of(err) == 400)
        err = await raises(auth_email.signup(bad, "password1", "Ann", terms_accepted=True))
        check(f"signup: non-string email {bad!r} -> 400", code_of(err) == 400)


asyncio.run(input_tests())

print("ALL CHECKS PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
