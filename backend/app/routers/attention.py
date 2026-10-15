"""
Phase Convert (C8.3) — GET /attention: does the *other* surface need the person?

The app shell shows a red dot on a tab when this says so (a session waiting on an approval, or a
turn that failed — see app/services/attention_rules.py for exactly what counts and for how long).
It is polled (about every 20 s, and on window focus), so it is deliberately cheap: two small queries
and no per-project work.

In Phase Convert only Code reports anything. `chat` is always zeros — Phase 8 (connector approvals
in Chat) fills it in — but the key is present now so the client contract doesn't change later.
"""
from fastapi import APIRouter, Depends

from app.core.security import AuthedUser
from app.dependencies import verified_user
from app.models.schemas import AttentionCounts, AttentionOut
from app.repositories import sessions as sessions_repo
from app.services import attention_rules

router = APIRouter(tags=["attention"])


@router.get("/attention", response_model=AttentionOut)
async def get_attention(user: AuthedUser = Depends(verified_user)):
    rows = await sessions_repo.attention_rows_for_user(user.user_id)
    return AttentionOut(code=AttentionCounts(**attention_rules.count_attention(rows)), chat=AttentionCounts())
