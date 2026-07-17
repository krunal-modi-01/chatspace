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

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
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
    redis_connect_timeout_seconds: float = Field(
        default=2.0,
        gt=0,
        description=(
            "Max seconds the readyz probe waits for a Redis `PING` before "
            "reporting unavailable — bounds the probe so an unreachable/"
            "wedged Redis fails fast (degrade, not hang or crash; see T05)."
        ),
    )

    # --- JWT / session signing (ADR-0006) -----------------------------------
    jwt_signing_key: SecretStr = Field(
        ...,
        description="Symmetric signing key for short-lived access JWTs. Never logged.",
    )
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_token_ttl_minutes: int = Field(default=15)

    # --- Session store / revocation cache (T10, ADR-0006) -------------------
    session_ttl_days: int = Field(
        default=30,
        gt=0,
        description=(
            "Sliding refresh-token session lifetime in days (contract: 30-day "
            "sliding expiry). `sessions.expires_at` is set to now + this value "
            "on creation and recomputed on refresh."
        ),
    )
    session_revocation_cache_ttl_seconds: int = Field(
        default=30,
        gt=0,
        description=(
            "TTL for a cached session-revocation-check result in Redis "
            "(ADR-0006). Bounds how stale a positive ('active') cache hit "
            "can be for a *different* app instance than the one that revoked "
            "it — the instance that performs the revoke always busts its own "
            "cache entry immediately, and `require_auth` always re-checks "
            "`users.is_active` fresh against Postgres on every request "
            "regardless of this cache."
        ),
    )

    # --- WebSocket connection manager (T23, F52, ADR-0006) ------------------
    ws_heartbeat_timeout_seconds: float = Field(
        default=45.0,
        gt=0,
        description=(
            "Max seconds a `/v1/ws` connection may go without receiving any "
            "client frame before it is presumed dead and reaped with close "
            "code 4408 (heartbeat-timeout). Chosen as roughly 2x the client's "
            "expected ping interval (~20s) so ordinary network jitter never "
            "trips it, per ADR-0006's follow-up that the backend-engineer "
            "sets and records this interval — it also bounds the worst-case "
            "mid-connection revocation lag (a revoked/deactivated session is "
            "re-checked, at latest, on the next client `ping` within this "
            "window)."
        ),
    )
    ws_frame_rate_limit_max_frames: int = Field(
        default=30,
        gt=0,
        description=(
            "Max client frames (`join`/`leave`/`typing`/`ping`) accepted per "
            "`ws_frame_rate_limit_window_seconds` on a single WS connection "
            "before it is closed with code 4429 (rate-limited) — an abuse "
            "guard on the connection itself, independent of and in addition "
            "to the per-user REST message-send rate limit (T27)."
        ),
    )
    ws_frame_rate_limit_window_seconds: float = Field(
        default=10.0,
        gt=0,
        description="Sliding window (seconds) `ws_frame_rate_limit_max_frames` is measured over.",
    )

    # --- Presence (T25, F49-F50) --------------------------------------------
    presence_ttl_seconds: int = Field(
        default=120,
        gt=0,
        description=(
            "TTL (seconds) on a user's Redis presence ref-count key "
            "(`app.core.redis_keys.presence_connection_count_key`). Refreshed on "
            "every connect and client heartbeat, so a live connection's presence "
            "contribution never expires while pings keep arriving. Set "
            "comfortably above `ws_heartbeat_timeout_seconds` (default 45s) so "
            "the ordinary, orderly reap-with-4408-then-decrement path always "
            "wins the race, and TTL expiry is reserved for the one failure mode "
            "a graceful per-connection decrement cannot cover: the whole app "
            "instance crashing before its `finally`-block disconnect handler "
            "ever runs. This is also why a full Redis restart can never leave a "
            "user falsely `online` (F49/F50): the counter key does not survive "
            "the restart at all, let alone outlive this TTL."
        ),
    )

    # --- SMTP / transactional email (ADR-0010) ------------------------------
    smtp_host: str = Field(..., description="SMTP server host.")
    smtp_port: int = Field(..., gt=0, le=65535, description="SMTP server port.")
    smtp_username: str = Field(..., description="SMTP auth username.")
    smtp_password: SecretStr = Field(..., description="SMTP auth password. Never logged.")
    smtp_from_address: str = Field(..., description="From: address for invite/reset emails.")
    smtp_use_tls: bool = Field(
        default=False,
        description=(
            "Implicit TLS on connect (typically port 465). Mutually exclusive with "
            "`smtp_start_tls` — `aiosmtplib` supports only one TLS negotiation mode per "
            "send. Default is False because the common transactional relays "
            "(Postmark/SES/Mailgun on 587, local MailHog on 1025) use STARTTLS, not "
            "implicit TLS."
        ),
    )
    smtp_start_tls: bool = Field(
        default=True,
        description=(
            "Require STARTTLS upgrade after connecting in plaintext (typically port "
            "587). Mutually exclusive with `smtp_use_tls`. This is `True` (required, "
            "not opportunistic) by default so an on-path attacker cannot silently strip "
            "the upgrade; set to `False` only when `smtp_use_tls=True` (implicit TLS) "
            "or when pointed at a trusted local relay that does not support STARTTLS."
        ),
    )
    smtp_max_attempts: int = Field(
        default=3,
        ge=1,
        description=(
            "Bounded inline retry count for a single email send (ADR-0010: no queue, "
            "inline send with bounded retry, fail-loud after this many attempts)."
        ),
    )
    smtp_retry_backoff_seconds: float = Field(
        default=0.5,
        ge=0,
        description="Base backoff between bounded inline retry attempts (grows linearly).",
    )
    smtp_send_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        description=(
            "Max seconds to wait for a single SMTP send attempt before treating it as failed."
        ),
    )

    # --- Password reset (T16, F15-F17) --------------------------------------
    password_reset_url_base: str = Field(
        ...,
        description=(
            "Base URL of the frontend password-reset page. The raw single-use "
            "reset token is appended as a `?token=` query parameter to build "
            "the link emailed to the requester (T16); never logged. Required "
            "(no default) so a missing/misconfigured env var fails startup "
            "fast instead of emailing a broken reset link built from a "
            "placeholder domain."
        ),
    )

    # --- Invites (T13, F1) ---------------------------------------------------
    invite_url_base: str = Field(
        ...,
        description=(
            "Base URL of the frontend invite-acceptance page. The raw "
            "single-use invite token is appended as a `?token=` query "
            "parameter to build the link emailed to the invitee (T13); "
            "never logged. Required (no default) so a missing/misconfigured "
            "env var fails startup fast instead of emailing a broken invite "
            "link built from a placeholder domain."
        ),
    )

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
    bootstrap_admin_first_name: str = Field(
        ..., description="First name of the env-seeded first-run System Admin account."
    )
    bootstrap_admin_last_name: str = Field(
        ..., description="Last name of the env-seeded first-run System Admin account."
    )

    # --- Observability (T39, technical spec §9) ------------------------------
    error_monitor_dsn: SecretStr | None = Field(
        default=None,
        description=(
            "Sentry-class error/uptime monitor DSN (see app.core.error_monitor). "
            "Config-driven and OFF by default (unset/blank) -- most local/dev "
            "environments never set this. Requires the optional 'sentry-sdk' "
            "dependency (pyproject.toml's 'observability' extra); a configured "
            "DSN without the package installed degrades to a logged no-op, "
            "never a startup failure. Never logged."
        ),
    )
    error_monitor_traces_sample_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Fraction of transactions sampled for performance tracing when the "
            "error monitor is enabled. 0.0 (default) disables tracing entirely "
            "and only reports captured exceptions."
        ),
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

    @model_validator(mode="after")
    def _reject_conflicting_tls_modes(self) -> Settings:
        """Forbid requesting both TLS negotiation modes at once.

        `aiosmtplib.send` accepts `use_tls` (implicit TLS, e.g. port 465) and
        `start_tls` (STARTTLS upgrade, e.g. port 587) as mutually exclusive
        connection modes -- passing both `True` is a misconfiguration, not a
        valid "extra secure" combination, so it must fail fast at startup
        rather than surface as a confusing runtime SMTP error.
        """

        if self.smtp_use_tls and self.smtp_start_tls:
            raise ValueError(
                "smtp_use_tls and smtp_start_tls are mutually exclusive: set "
                "smtp_use_tls=True for implicit TLS (port 465) OR "
                "smtp_start_tls=True for STARTTLS (port 587), not both."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached Settings instance.

    Cached so validation (and the fail-fast behavior on missing/invalid
    env vars) runs once per process, at first access — typically at
    application startup.
    """

    return Settings()  # type: ignore[call-arg]
