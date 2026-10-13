from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    environment: str = Field(default="development", validation_alias=AliasChoices("APP_ENV", "ENVIRONMENT"))
    demo_mode: bool = True
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

    def assert_auth_ready(self) -> None:
        if self.environment == "production":
            raise RuntimeError(
                "Production is disabled: configure and implement verified OIDC/JWT authorization before deployment."
            )
        if not self.demo_mode:
            raise RuntimeError("This release requires local DEMO_MODE=true; OIDC is not implemented.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
