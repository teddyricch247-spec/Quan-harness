"""Render every email template to files so you can look at them. Sends
NOTHING and makes no network calls.

    cd backend
    python render_email_previews.py            # writes email_previews/*.html and *.txt
    python render_email_previews.py --png      # also light + dark screenshots
                                               # (needs: pip install playwright
                                               #  && playwright install chromium)

Open email_previews/index.html in a browser. The .txt files are the
plain-text part that real sends carry.

Add every new template to SAMPLES below; test_email_templates.py fails if a
public template function is missing from it.
"""

import html
import pathlib
import sys

from app import email_templates as t
from app.email_layout import html_to_text

OUT = pathlib.Path(__file__).parent / "email_previews"
LINK = "https://example-project.supabase.co/auth/v1/verify?token=SAMPLE&type=magiclink&redirect_to=https://platform.quancis.space"

SAMPLES = {
    "confirm_signup": lambda: t.confirm_signup(LINK, "Response"),
    "welcome": lambda: t.welcome("Response"),
    "reset_password": lambda: t.reset_password(LINK),
    "password_changed": lambda: t.password_changed("Response", "11 Oct 2026, 14:32 UTC"),
    "already_registered": lambda: t.already_registered(),
    "admin_account_touched": lambda: t.admin_account_touched("tried to sign up"),
    "api_key_created": lambda: t.api_key_created("Response", "Production backend", "11 Oct 2026, 14:32 UTC"),
    "low_balance": lambda: t.low_balance("Response", "4.20", "5.00"),
    "balance_depleted": lambda: t.balance_depleted("Response", "0.00"),
    "credits_added": lambda: t.credits_added("Response", "25.00", "29.20", "11 Oct 2026, 14:32 UTC", "ref_SAMPLE123", bonus="5.00"),
    "account_suspended": lambda: t.account_suspended("Response"),
    "account_reactivated": lambda: t.account_reactivated("Response"),
    "price_change": lambda: t.price_change(
        "Response",
        "1 November 2026",
        [
            ("Kael Beta", "Input", "$3.00", "$X.XX"),
            ("Kael Beta", "Output", "$10.00", "$X.XX"),
        ],
    ),
    "legal_update": lambda: t.legal_update(
        "Response", "1 November 2026", ["Playground and API data handling is now described separately.", "New contact addresses."]
    ),
    "admin_drift": lambda: t.admin_drift([("0b9f-sample-user-id", "$10.00000", "$9.80000", "-$0.20000")]),
    "admin_check_failed": lambda: t.admin_check_failed("Supabase unreachable (sample)"),
    "admin_email_cap_reached": lambda: t.admin_email_cap_reached(200),
    "account_deletion_requested": lambda: t.account_deletion_requested("Response", LINK, "12.50"),
    "account_deletion_scheduled": lambda: t.account_deletion_scheduled("Response", "20 October 2026", LINK),
    "account_deletion_cancelled": lambda: t.account_deletion_cancelled("Response"),
    "account_deleted": lambda: t.account_deleted("Response", "11 Oct 2026, 14:32 UTC", "12.50"),
}


def main() -> int:
    OUT.mkdir(exist_ok=True)
    rows = []
    for name, build in SAMPLES.items():
        email = build()
        (OUT / f"{name}.html").write_text(email.html, encoding="utf-8")
        (OUT / f"{name}.txt").write_text(f"Subject: {email.subject}\n\n{html_to_text(email.html)}", encoding="utf-8")
        rows.append((name, email.subject))
    items = "".join(
        f'<li><a href="{n}.html">{n}</a> <small>{html.escape(s)}</small> &middot; <a href="{n}.txt">text</a></li>'
        for n, s in rows
    )
    (OUT / "index.html").write_text(
        f"<!doctype html><meta charset=utf-8><title>Quancis email previews</title>"
        f"<body style='font:15px/1.8 system-ui;max-width:640px;margin:40px auto;padding:0 16px'>"
        f"<h1>Quancis email previews</h1><ul>{items}</ul>",
        encoding="utf-8",
    )
    print(f"Wrote {len(rows)} previews to {OUT}")

    if "--png" in sys.argv:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            for scheme in ("light", "dark"):
                ctx = browser.new_context(viewport={"width": 640, "height": 800}, color_scheme=scheme, device_scale_factor=2)
                page = ctx.new_page()
                for name, _ in rows:
                    page.goto((OUT / f"{name}.html").resolve().as_uri())
                    page.screenshot(path=str(OUT / f"{name}.{scheme}.png"), full_page=True)
                ctx.close()
            browser.close()
        print("Wrote light and dark PNGs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
