from fastapi import APIRouter, Depends

from app.core.security import AuthedUser
from app.dependencies import verified_user
from app.repositories import audit

router = APIRouter(prefix="/audit-log", tags=["audit"])


@router.get("")
async def list_audit_log(user: AuthedUser = Depends(verified_user)):
    """Always filtered to the caller's own user_id (§27) — no other account's rows
    are ever reachable through this route."""
    return await audit.list_for_user(user.user_id)
