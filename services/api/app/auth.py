from dataclasses import dataclass

from fastapi import Depends

from app.config import Settings, get_settings

DEMO_TENANT_ID = "00000000-0000-4000-8000-000000000001"
DEMO_USER_ID = "00000000-0000-4000-8000-000000000002"


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    user_id: str
    role: str


def get_principal(settings: Settings = Depends(get_settings)) -> Principal:
    # Never derive either identifier from request headers, query parameters or body.
    settings.assert_auth_ready()
    return Principal(DEMO_TENANT_ID, DEMO_USER_ID, "owner")
