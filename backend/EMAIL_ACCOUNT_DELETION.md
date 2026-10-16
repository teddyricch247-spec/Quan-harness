# Account deletion emails: hand-off

The email side of account deletion is built and tested. **Update 2026-10-15:**
account deletion now exists (`DELETE /api/account`, `app/account.py`, with a
Delete Account card on the Account page: typed confirmation, deletes at once, no
waiting period). `app/account.py` calls `notify_account_deleted` after the
deletion succeeds. **The other three functions below are still not called by
anything**; they are only needed if the flow changes to "confirm by email link"
or "wait N days".

## What exists

| Function (`app/account_emails.py`) | Send it when | Template (`app/email_templates.py`) |
|---|---|---|
| `notify_deletion_requested(user, confirm_url, unused_balance=None)` | the person asks to delete and must confirm by email | `account_deletion_requested` |
| `notify_deletion_scheduled(user, deletion_date, cancel_url)` | *(only if you add a waiting period)* deletion is queued for a date | `account_deletion_scheduled` |
| `notify_deletion_cancelled(user)` | *(waiting period only)* they cancel | `account_deletion_cancelled` |
| `notify_account_deleted(user_snapshot, unused_balance=None)` | **after** the deletion has succeeded | `account_deleted` |

All four return `True` only if Resend accepted the email, `False` otherwise, and
**never raise**. All use the same layout, dark mode, plain-text part and Resend
tags as every other email. `user` is the Supabase Auth user dict (needs `id`,
`email`, optionally `user_metadata.full_name`). `unused_balance` is dollars as a
number (or `None`); a positive value is shown as "not refunded".

## Two flows, pick one

**A. Confirm, then delete now**
1. User asks to delete (signed in). Backend mints a confirmation link (see rule 3).
2. `ok = await notify_deletion_requested(user, confirm_url, balance)`. **If
   `ok` is `False`, tell the person the email could not be sent**; they cannot
   finish otherwise.
3. They click the link; backend verifies it, **snapshots** the user, deletes.
4. After success: `await notify_account_deleted(snapshot, balance)`.

**B. Confirm, wait N days, then delete** (A, plus:)
after step 3 call `notify_deletion_scheduled(user, "20 October 2026", cancel_url)`;
if they cancel, `notify_deletion_cancelled(user)`; when the date arrives, delete
and send `notify_account_deleted`.

## Rules (each one prevents a real problem)

1. **Snapshot before deleting.** After deletion the address no longer exists
   anywhere. Copy the user dict (and the balance) first, delete, then email from
   the copy. `notify_account_deleted` only needs `email` and, optionally,
   `user_metadata`.
2. **Send the final email only after the deletion succeeds**, and never let its
   failure undo or block the deletion (it returns `False`; the cause is logged).
3. **The confirmation link must be single-use, short-lived (about 1 hour), tied
   to that one user id, and unguessable.** Do not put the user id or email in it
   as the only secret. Opening it should show a page with a button; delete only on
   the button press, so email scanners that pre-fetch links cannot trigger a
   deletion (same reason as `/auth/confirm` for sign-up links).
4. **Links must be `http(s)://`.** `notify_deletion_*` refuse anything else and the
   layout never emits other schemes.
5. `notify_deletion_requested` is limited to 3 per user per hour (in-process).
6. Decide what happens to **admin accounts**: the other auth flows refuse to act
   on them through the app (`auth_email.py` docstring).
7. After the final email, send nothing more to that address about the account.
8. Do not put secrets or API keys in these emails. They contain none.

## Wording and legal anchors

The copy only restates what the published pages already say:
- Privacy Policy, *Data Retention*: on account deletion personal information is
  removed "except where retention is required by law (e.g., financial records,
  or evidence of a flagged violation under investigation)".
- Terms of Service: unused credits are not refunded on account deletion.

The emails also say deletion "ends your access" and "revokes your API keys".
Make sure the real deletion does that, or change the copy in
`email_templates.py`. The owner should have the final wording checked against the
legal pages.

## Preview and test

```
cd backend
python render_email_previews.py --png    # writes email_previews/account_deletion_*.html / .png (git-ignored)
python test_email_system.py              # ALL CHECKS PASSED
```
`test_email_system.py` already covers these functions (sending, bad links, rate
limit, failures, snapshot, escaping). When the flow is wired, add one test that the
route calls `notify_deletion_requested` and reports failure to the user, and one
that `notify_account_deleted` runs after, not before, the deletion.

## Not done (by design)

The deletion route, the confirmation-token mechanism, the frontend page and
button, data removal, a scheduler for flow B, and any change to the Privacy/Terms
text. A send log would let you prove each notice went out; it needs a migration
(see `Quancis_Email_System_Audit.md`).
