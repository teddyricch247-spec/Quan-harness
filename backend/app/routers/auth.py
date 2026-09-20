"""
§4: signup/login/reset are primarily a frontend-direct-to-Supabase flow (the
frontend holds the anon key and calls supabase-js itself — see
frontend/lib/supabaseClient.ts). These routes exist because §28's API surface
lists them explicitly as backend-proxied equivalents, using the anon client
(never service_role) so they carry exactly the privileges a browser calling
Supabase directly would have.
"""
from fastapi import APIRouter, HTTPException, status

from app.db import get_anon_client
from app.models.schemas import LoginRequest, PasswordResetRequest, SignupRequest

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest):
    client = get_anon_client()
    try:
        result = client.auth.sign_up({"email": body.email, "password": body.password})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {
        "user_id": result.user.id if result.user else None,
        "email_confirmation_sent": True,
    }


@router.post("/login")
def login(body: LoginRequest):
    client = get_anon_client()
    try:
        result = client.auth.sign_in_with_password({"email": body.email, "password": body.password})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    return {
        "access_token": result.session.access_token,
        "refresh_token": result.session.refresh_token,
        "user_id": result.user.id,
    }


@router.post("/request-password-reset")
def request_password_reset(body: PasswordResetRequest):
    client = get_anon_client()
    try:
        client.auth.reset_password_for_email(body.email)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {"sent": True}
