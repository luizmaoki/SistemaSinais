"""Authorization-code login and revocable local sessions."""

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import (
    DEMO_TENANT_ID, DEMO_USER_ID, FLOW_COOKIE, OPAQUE_PATTERN, SESSION_COOKIE,
    Principal, get_principal, require_csrf, token_hash,
)
from app.config import Settings, get_settings
from app.database import get_db, utcnow
from app.models import AuthFlow, AuthSession, Tenant, User, new_id
from app.oidc import OIDCClient, OIDCError

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
SESSION_PATH = "/api/v1"
FLOW_PATH = "/api/v1/auth"


def clear_flow_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        FLOW_COOKIE, path=FLOW_PATH, secure=settings.session_cookie_secure, httponly=True, samesite="lax"
    )


def failed_login(settings: Settings) -> RedirectResponse:
    response = RedirectResponse("/login?auth_error=login_failed", status_code=302)
    clear_flow_cookie(response, settings)
    return response


@router.get("/config")
def auth_config(settings: Settings = Depends(get_settings)):
    try:
        settings.assert_auth_ready()
        configured = True
    except RuntimeError:
        configured = False
    return {
        "auth_mode": settings.auth_mode, "configured": configured,
        "demo_available": settings.demo_available, "login_path": "/api/v1/auth/login",
    }


@router.get("/session")
def auth_session(principal: Principal = Depends(get_principal)):
    return {
        "mode": "DEMO" if principal.auth_mode == "demo" else "AUTHENTICATED",
        "auth_mode": principal.auth_mode,
        "user": {"id": principal.user_id, "name": principal.name},
        "tenant_id": principal.tenant_id, "role": principal.role,
        "csrf_token": principal.csrf_token, "expires_at": principal.expires_at,
    }


@router.get("/login")
async def login(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    settings.assert_auth_ready()
    if settings.demo_available:
        return RedirectResponse("/dashboard", status_code=302)
    try:
        async with OIDCClient(settings) as provider:
            metadata = await provider.discovery()
    except OIDCError:
        return failed_login(settings)
    state, binding, nonce = (secrets.token_urlsafe(32) for _ in range(3))
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
    now = utcnow()
    db.execute(delete(AuthFlow).where(AuthFlow.expires_at <= now))
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
    previous_binding = request.cookies.get(FLOW_COOKIE, "")
    if OPAQUE_PATTERN.fullmatch(previous_binding):
        db.execute(delete(AuthFlow).where(AuthFlow.binding_hash == token_hash(previous_binding)))
    db.add(AuthFlow(
        state_hash=token_hash(state), binding_hash=token_hash(binding), nonce=nonce,
        code_verifier=verifier, expires_at=now + timedelta(seconds=settings.oidc_flow_ttl_seconds),
    ))
    db.commit()
    query = urlencode({
        "response_type": "code", "client_id": settings.oidc_client_id,
        "redirect_uri": settings.callback_url, "scope": "openid profile", "response_mode": "query",
        "state": state, "nonce": nonce, "code_challenge": challenge,
        "code_challenge_method": "S256", "prompt": "login",
    })
    response = RedirectResponse(metadata["authorization_endpoint"] + "?" + query, status_code=302)
    response.set_cookie(
        FLOW_COOKIE, binding, max_age=settings.oidc_flow_ttl_seconds, path=FLOW_PATH,
        secure=settings.session_cookie_secure, httponly=True, samesite="lax",
    )
    return response


def identity_user(db: Session, settings: Settings, claims: dict) -> User:
    identity = (User.oidc_issuer == settings.oidc_issuer, User.oidc_subject == claims["sub"])
    user = db.scalar(select(User).where(*identity))
    if user is None:
        name = claims.get("name") or claims.get("preferred_username")
        if not isinstance(name, str):
            name = "Usuário"
        name = "".join(char for char in name if ord(char) >= 32).strip()[:100] or "Usuário"
        # A concurrent first login may win the unique (issuer, subject) index.
        # A savepoint rolls back its tenant too, avoiding orphaned workspaces.
        try:
            with db.begin_nested():
                tenant_id = new_id()
                db.add(Tenant(id=tenant_id, name="Workspace pessoal"))
                db.flush()
                user = User(
                    id=new_id(), tenant_id=tenant_id, name=name, role="owner", active=True,
                    oidc_issuer=settings.oidc_issuer, oidc_subject=claims["sub"],
                )
                db.add(user)
                db.flush()
        except IntegrityError:
            user = db.scalar(select(User).where(*identity))
            if user is None:
                raise
    if (
        not user.active or user.role not in {"owner", "viewer"}
        or user.id == DEMO_USER_ID or user.tenant_id == DEMO_TENANT_ID
    ):
        raise OIDCError()
    return user


def consume_flow(db: Session, state: str, binding: str):
    # One SQL mutation consumes the browser-bound state across all API workers.
    # Commit before any provider request, so failures/replays cannot redeem twice.
    flow = db.execute(
        delete(AuthFlow).where(
            AuthFlow.state_hash == token_hash(state), AuthFlow.binding_hash == token_hash(binding),
            AuthFlow.expires_at > utcnow(),
        ).returning(AuthFlow.nonce, AuthFlow.code_verifier).execution_options(synchronize_session=False)
    ).mappings().first()
    db.commit()
    return flow


@router.get("/callback")
async def callback(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    settings.assert_auth_ready()
    if settings.auth_mode != "oidc":
        return failed_login(settings)
    query = request.query_params
    state, binding = query.get("state", ""), request.cookies.get(FLOW_COOKIE, "")
    if (
        not OPAQUE_PATTERN.fullmatch(state) or not OPAQUE_PATTERN.fullmatch(binding)
        or any(len(query.getlist(key)) > 1 for key in ("state", "code", "error", "iss"))
    ):
        return failed_login(settings)
    flow = consume_flow(db, state, binding)
    if not flow:
        return failed_login(settings)
    code = query.get("code", "")
    if (
        "error" in query or not 0 < len(code) <= 4096 or not code.isascii()
        or any(ord(char) < 33 or ord(char) > 126 for char in code)
        or ("iss" in query and query["iss"] != settings.oidc_issuer)
    ):
        return failed_login(settings)
    try:
        async with OIDCClient(settings) as provider:
            metadata = await provider.discovery()
            claims = await provider.exchange(metadata, code, flow["code_verifier"], flow["nonce"])
        user = identity_user(db, settings, claims)
        expires_at = min(
            utcnow() + timedelta(seconds=settings.session_ttl_seconds),
            datetime.fromtimestamp(claims["exp"], tz=timezone.utc),
        )
        max_age = int((expires_at - utcnow()).total_seconds())
        if max_age < 1:
            raise OIDCError()
        opaque_id = secrets.token_urlsafe(32)
        previous_session = request.cookies.get(SESSION_COOKIE, "")
        if OPAQUE_PATTERN.fullmatch(previous_session):
            db.execute(delete(AuthSession).where(AuthSession.id_hash == token_hash(previous_session)))
        db.add(AuthSession(
            id_hash=token_hash(opaque_id), user_id=user.id, csrf_token=secrets.token_urlsafe(32), expires_at=expires_at,
        ))
        db.commit()
    except (OIDCError, ValueError, OverflowError):
        db.rollback()
        return failed_login(settings)
    response = RedirectResponse("/dashboard", status_code=302)
    clear_flow_cookie(response, settings)
    response.set_cookie(
        SESSION_COOKIE, opaque_id, max_age=max_age, path=SESSION_PATH,
        secure=settings.session_cookie_secure, httponly=True, samesite="lax",
    )
    return response


@router.post("/logout")
def logout(
    request: Request, response: Response, db: Session = Depends(get_db),
    principal: Principal = Depends(require_csrf), settings: Settings = Depends(get_settings),
):
    if principal.session_hash:
        db.execute(delete(AuthSession).where(AuthSession.id_hash == principal.session_hash))
    binding = request.cookies.get(FLOW_COOKIE, "")
    if OPAQUE_PATTERN.fullmatch(binding):
        db.execute(delete(AuthFlow).where(AuthFlow.binding_hash == token_hash(binding)))
    db.commit()
    response.delete_cookie(
        SESSION_COOKIE, path=SESSION_PATH, secure=settings.session_cookie_secure, httponly=True, samesite="lax"
    )
    clear_flow_cookie(response, settings)
    return {"logged_out": True}
