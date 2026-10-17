from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


def valid_url(value: str, *, origin_only: bool = False) -> bool:
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme in {"http", "https"} and bool(parsed.hostname)
            and parsed.username is None and parsed.password is None
            and not parsed.query and not parsed.fragment
            and not any(char.isspace() or ord(char) < 32 for char in value)
            and "%" not in parsed.path and "//" not in parsed.path
            and not any(segment in {".", ".."} for segment in parsed.path.split("/"))
            and "\\" not in value and (not origin_only or parsed.path in {"", "/"})
            and (parsed.port is None or 0 < parsed.port <= 65535)
        )
    except ValueError:
        return False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    environment: str = Field(default="development", validation_alias=AliasChoices("APP_ENV", "ENVIRONMENT"))
    auth_mode: str = "demo"
    demo_mode: bool = True
    oidc_issuer: str = ""
    oidc_internal_base_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = Field(default="", repr=False)
    auth_public_base_url: str = "http://localhost:3000"
    session_cookie_secure: bool = False
    session_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    oidc_flow_ttl_seconds: int = Field(default=600, ge=60, le=1800)
    database_url: str = "sqlite:///./capital_intelligence.db"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    allowed_hosts: str = "localhost,127.0.0.1,api,testserver"
    sec_user_agent: str = Field(default="", repr=False)
    coinbase_personal_use_accepted: bool = False
    request_limit_per_minute: int = 120
    ingestion_interval_seconds: int = 900
    provider_timeout_seconds: float = 20.0
    max_request_bytes: int = 65_536

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        if value not in {"development", "test", "production"}:
            raise ValueError("ENVIRONMENT must be development, test or production")
        return value

    @field_validator("auth_mode")
    @classmethod
    def validate_auth_mode(cls, value: str) -> str:
        if value not in {"demo", "oidc"}:
            raise ValueError("AUTH_MODE must be demo or oidc")
        return value

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def host_allowlist(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    @property
    def demo_available(self) -> bool:
        return self.auth_mode == "demo" and self.environment in {"development", "test"} and self.demo_mode

    @property
    def callback_url(self) -> str:
        return self.auth_public_base_url.rstrip("/") + "/api/v1/auth/callback"

    def assert_auth_ready(self) -> None:
        if self.auth_mode == "demo":
            if not self.demo_available:
                raise RuntimeError("Demo requires development/test and DEMO_MODE=true; production requires AUTH_MODE=oidc.")
            return
        if (
            not self.oidc_client_id.strip() or len(self.oidc_client_id) > 255
            or not valid_url(self.oidc_issuer) or len(self.oidc_issuer) > 500
            or not valid_url(self.auth_public_base_url, origin_only=True)
        ):
            raise RuntimeError("OIDC requires valid OIDC_ISSUER, OIDC_CLIENT_ID and AUTH_PUBLIC_BASE_URL.")
        if not self.allowed_origins or any(not valid_url(origin, origin_only=True) for origin in self.allowed_origins):
            raise RuntimeError("OIDC requires explicit valid CORS origins.")
        if self.auth_public_base_url.rstrip("/") not in self.allowed_origins:
            raise RuntimeError("AUTH_PUBLIC_BASE_URL must be an allowed CORS origin.")
        if self.oidc_internal_base_url and (self.environment == "production" or not valid_url(self.oidc_internal_base_url)):
            raise RuntimeError("OIDC_INTERNAL_BASE_URL is allowed only in development/test and must be valid.")
        for value in (self.oidc_issuer, self.auth_public_base_url):
            parsed = urlsplit(value)
            if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise RuntimeError("Unencrypted OIDC URLs are allowed only for loopback development.")
        if self.environment == "production":
            if self.demo_mode or not self.session_cookie_secure or not self.oidc_client_secret:
                raise RuntimeError("Production OIDC requires DEMO_MODE=false, a client secret and Secure session cookies.")
            if any(urlsplit(value).scheme != "https" for value in [self.oidc_issuer, self.auth_public_base_url, *self.allowed_origins]):
                raise RuntimeError("Production OIDC requires HTTPS URLs and explicit HTTPS CORS origins.")
            if (
                "allowed_hosts" not in self.model_fields_set or not self.host_allowlist
                or any("*" in host or "/" in host or ":" in host for host in self.host_allowlist)
            ):
                raise RuntimeError("Production requires explicit allowed hosts.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
