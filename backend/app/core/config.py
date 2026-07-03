"""Application settings.

All configuration — including every secret — is loaded exclusively from
environment variables via ``pydantic-settings``. There are deliberately
**no hardcoded defaults** for any secret-bearing field: if a required
variable is missing, application startup fails fast with a clear
validation error rather than silently falling back to an insecure or
incorrect value.

See CLAUDE.md `secrets_location` and the technical spec §8 (Security &
privacy) / §10 (Phase 0 hard prerequisites) for the rationale.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide configuration, populated entirely from the environment.

    Every field below is a *required* dependency of chatspace v1 per the
    technical spec (§8) and database design — there is no "development
    default" for a secret. Local/dev/test environments must supply their
    own `.env` (never committed) or real environment variables; docker
    compose wires these for the local stack.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App / environment -------------------------------------------------
    app_env: str = Field(
        default="development",
        description="Deployment environment name (development/staging/production).",
    )
    log_level: str = Field(default="INFO")

    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description=(
            "Explicit allowlist of frontend origins for CORS. No wildcard in production "
            "(CLAUDE.md security requirements)."
        ),
    )

    # --- Postgres (durable state; asyncpg pool) -----------------------------
    database_url: SecretStr = Field(
        ...,
        description="Postgres connection string (asyncpg driver), e.g. "
        "postgresql+asyncpg://user:pass@host:5432/chatspace",
    )
    db_pool_size: int = Field(
        default=10,
        ge=1,
        description=(
            "Per-instance asyncpg pool size (SQLAlchemy `pool_size`). Config-driven per "
            "the technical spec's connection-pooling-per-instance design (no PgBouncer "
            "at 1,000-user scale)."
        ),
    )
    db_max_overflow: int = Field(
        default=5,
        ge=0,
        description="Extra connections allowed above `db_pool_size` under burst load.",
    )
    db_pool_timeout_seconds: float = Field(
        default=5.0,
        gt=0,
        description="Max seconds to wait for a connection from the pool before failing fast.",
    )
    db_statement_timeout_ms: int = Field(
        default=5000,
        gt=0,
        description=(
            "Bounded Postgres `statement_timeout` (ms) applied to every connection, so a "
            "slow/hung query fails fast instead of piling up requests (technical spec: "
            "'PostgreSQL down/slow' risk mitigation)."
        ),
    )
    db_connect_timeout_seconds: float = Field(
        default=3.0,
        gt=0,
        description=(
            "Max seconds to wait when establishing a new asyncpg connection (e.g. "
            "Postgres unreachable) before failing fast — bounds the readyz probe."
        ),
    )

    # --- Redis (pub/sub fan-out, presence, rate limiting, session cache) ----
    redis_url: SecretStr = Field(
        ...,
        description="Redis connection string, e.g. redis://host:6379/0",
    )

    # --- JWT / session signing (ADR-0006) -----------------------------------
    jwt_signing_key: SecretStr = Field(
        ...,
        description="Symmetric signing key for short-lived access JWTs. Never logged.",
    )
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_token_ttl_minutes: int = Field(default=15)

    # --- SMTP / transactional email (ADR-0010) ------------------------------
    smtp_host: str = Field(..., description="SMTP server host.")
    smtp_port: int = Field(..., description="SMTP server port.")
    smtp_username: str = Field(..., description="SMTP auth username.")
    smtp_password: SecretStr = Field(..., description="SMTP auth password. Never logged.")
    smtp_from_address: str = Field(..., description="From: address for invite/reset emails.")
    smtp_use_tls: bool = Field(default=True)

    # --- S3-compatible object storage (ADR-0007) ----------------------------
    s3_endpoint_url: str = Field(
        ..., description="S3-compatible endpoint (e.g. MinIO local, R2, S3, Spaces)."
    )
    s3_bucket_name: str = Field(..., description="Bucket used for media object storage.")
    s3_access_key_id: SecretStr = Field(..., description="S3 access key id. Never logged.")
    s3_secret_access_key: SecretStr = Field(..., description="S3 secret key. Never logged.")
    s3_region: str = Field(default="auto")

    # --- Bootstrap System Admin (ADR-0009; non-skippable first-run) --------
    bootstrap_admin_email: str = Field(
        ..., description="Email of the env-seeded first-run System Admin account."
    )
    bootstrap_admin_password: SecretStr = Field(
        ..., description="Initial password for the bootstrap System Admin. Never logged."
    )
    bootstrap_admin_username: str = Field(
        ..., description="Username of the env-seeded first-run System Admin account."
    )

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_allowed_origins")
    @classmethod
    def _reject_wildcard_origin_in_production(
        cls, value: list[str], info: ValidationInfo
    ) -> list[str]:
        """Forbid a wildcard CORS origin in production.

        `allow_credentials=True` combined with a `*` origin lets any site
        make credentialed cross-origin requests — a credential-theft/CSRF
        vector once auth ships. `app_env` is declared before this field, so
        it is available in `info.data`. (CLAUDE.md SECURITY REQUIREMENTS:
        "no wildcard origins in production".)
        """

        if info.data.get("app_env") == "production" and "*" in value:
            raise ValueError("CORS wildcard '*' origin is not allowed in production")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached Settings instance.

    Cached so validation (and the fail-fast behavior on missing/invalid
    env vars) runs once per process, at first access — typically at
    application startup.
    """

    return Settings()  # type: ignore[call-arg]
