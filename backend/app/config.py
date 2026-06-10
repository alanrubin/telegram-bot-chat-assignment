"""Application configuration.

Settings are loaded from environment variables (and an optional ``.env`` file) via
pydantic-settings. The bot token is **required**: if it is missing, constructing
``Settings`` raises a validation error, so the app fails fast at startup with a clear
message instead of running as a silently-dead bot (see D6/D8 in DECISIONS.md).

``get_settings()`` is cached and is the single accessor used by the rest of the app. It is
a function (rather than a module-level instance) so that importing this module never
requires a token — tests can construct ``Settings(...)`` directly with their own values.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Required: the bot token from BotFather. No default -> app refuses to start without it.
    telegram_bot_token: str

    # Optional: pin a specific chat as the only allowed participant. When None, the first
    # chat to message the bot claims the single slot (see D2 in DECISIONS.md).
    telegram_allowed_chat_id: int | None = None

    # Comma-separated allowed browser origins for CORS. Defaults cover local dev (Vite) and
    # the Dockerised frontend; tightened from the scaffold's wide-open "*".
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    # Logging verbosity for the app (INFO/WARNING/ERROR/DEBUG).
    log_level: str = "INFO"

    # Optional shared secret required to call POST /session/reset. When unset, the reset
    # endpoint is disabled entirely (it is an optional extension, see D2). Requiring a custom
    # header also defeats cross-site CSRF: a browser cannot send a custom header cross-origin
    # without a CORS preflight, which the origin allowlist rejects.
    session_reset_token: str | None = None

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse ``cors_origins`` into a clean list of origins."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings (constructed on first use)."""
    return Settings()
