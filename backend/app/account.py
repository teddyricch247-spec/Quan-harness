"""Account deletion (added 2026-10-13): DELETE /api/account.

WHAT IT DOES. Permanently deletes the signed-in user's account and everything
stored against it, which is what the Privacy Policy promises ("Your Rights" and
"Data Retention"). In order:

  1. checks the request (not an admin account; the typed confirmation matches);
  2. revokes every active API key, so API traffic on the account stops at once;
  3. deletes the rows that would otherwise outlive the account: the Playground
     diagnostic records (chat_debug_traces) and the usage records (usage_logs).
     Both reference the user ON DELETE SET NULL, so deleting the auth user
     alone would leave them behind, ownerless, with their text excerpts;
  4. deletes the Supabase Auth user (supabase_client.delete_auth_user). The
     database then cascades the rest: conversations, messages and pictures, API
     keys, the billing account and ledger, and the recorded acceptances of the
     Terms and Privacy Policy;
  5. sends a short confirmation email (best effort: a failed email never
     un-deletes anything or turns the answer into an error).

ORDER MATTERS. The auth user is deleted LAST, after steps 2 and 3 succeeded. If
step 2 or 3 fails the account still exists and the caller gets a 502 to retry;
every step is safe to repeat. If step 4 fails after 3 succeeded, the account is
still there (with its usage history gone) and a retry finishes the job.

NOT DELETED HERE, ON PURPOSE. Payment and tax records: payments are taken by
the Merchant of Record (Lemon Squeezy), which keeps its own records of them, and
the owner keeps the accounting records the law requires. Nothing in this
database is a payment record. Credits left on the account are forfeited: they
have no cash value (Terms of Service, "Credits and Billing").

ADMIN ACCOUNTS cannot be deleted here (403): the owner removes an admin account
in Supabase on purpose, so a stolen admin session cannot erase the admin
account. Same stance as admin.suspend_user.
"""

from fastapi import HTTPException

from . import account_emails, api_keys, email_service, supabase_client


def _error(status: int, message: str, code: str, type_: str = "invalid_request_error") -> HTTPException:
    return HTTPException(status_code=status, detail={"error": {"message": message, "type": type_, "code": code}})


def required_confirmation(user: dict) -> str:
    """What the user must type to confirm: their account email address, or, for
    the rare account with no email on file, the word DELETE."""
    return (user.get("email") or "").strip() or "DELETE"


def confirmation_matches(user: dict, confirm) -> bool:
    """True when `confirm` is exactly what required_confirmation() asks for. The
    email is compared ignoring case and surrounding spaces; DELETE must be typed
    in capitals."""
    if not isinstance(confirm, str):
        return False
    expected = required_confirmation(user)
    if (user.get("email") or "").strip():
        return confirm.strip().lower() == expected.lower()
    return confirm.strip() == "DELETE"


async def delete_account(user: dict, confirm) -> dict:
    """Deletes `user`'s account (see the module docstring). `user` is the
    verified Supabase user object from auth.require_login. Raises HTTPException:
    403 for an admin account, 400 for a wrong confirmation, 502 when a step fails
    and the caller should retry. Returns {"deleted": True}."""
    user_id = user.get("id")
    if not user_id:
        raise _error(400, "Could not tell which account to delete.", "invalid_account")
    if supabase_client.is_admin_user(user):
        raise _error(
            403,
            "Admin accounts can't be deleted from here. Remove an admin account directly in Supabase.",
            "admin_account",
            type_="forbidden",
        )
    if not confirmation_matches(user, confirm):
        raise _error(
            400,
            f"Type {required_confirmation(user)} to confirm that you want to delete your account.",
            "confirmation_required",
        )

    email = (user.get("email") or "").strip()

    try:
        await api_keys.revoke_all_active_keys(user_id)
        for table in ("chat_debug_traces", "usage_logs"):
            await supabase_client.delete_user_rows(table, user_id)
        await supabase_client.delete_auth_user(user_id)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 — any failure here means "not finished, retry"
        # The error text can carry a database URL; keep the type only.
        print(f"[account] ACCOUNT_DELETE_FAILED user={user_id} error={type(e).__name__}")
        raise _error(
            502,
            "We could not finish deleting your account. Nothing further was changed. Please try again, or write to response@quancis.space.",
            "delete_failed",
            type_="server_error",
        )

    print(f"[account] ACCOUNT_DELETED user={user_id}")
    if email:
        # The shared email system (account_emails.notify_account_deleted) sends it. It never
        # raises: a failed email cannot un-delete anything or turn the answer into an error.
        # `user` is the snapshot taken before the delete, which is all it needs.
        await account_emails.notify_account_deleted(user)
    return {"deleted": True}
