"""
§24: "Delete an account — Connections -> Account. Cascades to every project,
session, credential, and piece of memory owned by that account. Does not touch any
real GitHub resource or any connector's own platform. Requires typing 'DELETE' to
confirm." The typed-confirmation UI lives in the frontend; this route re-checks it
server-side too, since a confirmation the frontend enforces but the backend trusts
blindly isn't really a confirmation.
"""
from fastapi import APIRouter, Depends, HTTPException, status

from starlette.concurrency import run_in_threadpool

from app.core.security import AuthedUser
from app.db import get_service_client
from app.dependencies import current_user
from app.models.schemas import AccountDeleteRequest

router = APIRouter(prefix="/account", tags=["account"])


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(body: AccountDeleteRequest, user: AuthedUser = Depends(current_user)):
    if body.confirmation != "DELETE":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Type DELETE to confirm.")

    client = get_service_client()

    # audit_log.user_id references auth.users(id) on delete set null (§10.3) —
    # deliberately, so the trail of "an account was deleted" outlives the account.
    # That only works if the row is written *before* the user is gone: insert it
    # first (while the FK still resolves), then delete the account, then flip this
    # same row to success — updating success/output_summary afterward never touches
    # the user_id column, so it's unaffected by the FK having already been nulled
    # out by the cascade in between.
    def _insert_pending():
        return (
            client.table("audit_log")
            .insert(
                {
                    "user_id": user.user_id,
                    "tool": "account",
                    "action": "delete_account",
                    "success": False,
                    "output_summary": "pending",
                    "initiated_by": "user",
                }
            )
            .execute()
            .data[0]
        )

    audit_row = await run_in_threadpool(_insert_pending)

    def _mark(success: bool, summary: str):
        client.table("audit_log").update({"success": success, "output_summary": summary}).eq(
            "id", audit_row["id"]
        ).execute()

    try:
        # auth.users has `on delete cascade` on every table below it (§5), so this one
        # call removes every project/session/credential/memory row owned by the
        # account in the same operation.
        await run_in_threadpool(client.auth.admin.delete_user, user.user_id)
    except Exception as exc:  # noqa: BLE001
        await run_in_threadpool(_mark, False, str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    await run_in_threadpool(_mark, True, "completed")
