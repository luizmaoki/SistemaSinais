import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import datetime

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db, utcnow
from app.errors import api_error
from app.models import AuthSession, User

DEMO_TENANT_ID = "00000000-0000-4000-8000-000000000001"
DEMO_USER_ID = "00000000-0000-4000-8000-000000000002"
SESSION_COOKIE = "ci_session"
FLOW_COOKIE = "ci_oidc_flow"
OPAQUE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    user_id: str
    role: str
    name: str = "Usuário demo"
    auth_mode: str = "demo"
    csrf_token: str | None = None
    expires_at: datetime | None = None
    session_hash: str | None = None


def get_principal(
    request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> Principal:
    settings.assert_auth_ready()
    if settings.demo_available:
        user = db.get(User, DEMO_USER_ID)
        if not user or not user.active:
            raise api_error(403, "ACCOUNT_INACTIVE", "Conta indisponível.")
        return Principal(DEMO_TENANT_ID, user.id, user.role, user.name)
    opaque_id = request.cookies.get(SESSION_COOKIE, "")
    if not OPAQUE_PATTERN.fullmatch(opaque_id):
        raise api_error(401, "AUTH_REQUIRED", "Entre para acessar este recurso.")
    session = db.get(AuthSession, token_hash(opaque_id))
    if session is None:
        raise api_error(401, "AUTH_REQUIRED", "Entre para acessar este recurso.")
    if session.expires_at <= utcnow():
        db.delete(session)
        db.commit()
        raise api_error(401, "SESSION_EXPIRED", "Sessão expirada; entre novamente.")
    user = db.get(User, session.user_id)
    if user is None or not user.active:
        raise api_error(403, "ACCOUNT_INACTIVE", "Conta indisponível.")
    if (
        user.oidc_issuer != settings.oidc_issuer or not user.oidc_subject
        or user.id == DEMO_USER_ID or user.tenant_id == DEMO_TENANT_ID
    ):
        raise api_error(401, "AUTH_REQUIRED", "Entre para acessar este recurso.")
    if user.role not in {"owner", "viewer"}:
        raise api_error(403, "ROLE_NOT_ALLOWED", "Permissão de conta inválida.")
    return Principal(
        user.tenant_id, user.id, user.role, user.name, "oidc",
        session.csrf_token, session.expires_at, session.id_hash,
    )


def require_csrf(
    request: Request, principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings),
) -> Principal:
    if principal.auth_mode == "oidc":
        supplied = request.headers.get("X-CSRF-Token", "")
        if not OPAQUE_PATTERN.fullmatch(supplied) or not hmac.compare_digest(supplied, principal.csrf_token or ""):
            raise api_error(403, "CSRF_INVALID", "Token CSRF ausente ou inválido.")
        origin = request.headers.get("Origin")
        if origin is not None and origin not in settings.allowed_origins:
            raise api_error(403, "INVALID_ORIGIN", "Origem não autorizada.")
    return principal


def require_writer(principal: Principal = Depends(require_csrf)) -> Principal:
    if principal.role != "owner":
        raise api_error(403, "FORBIDDEN", "Sua conta tem acesso somente para leitura.")
    return principal
