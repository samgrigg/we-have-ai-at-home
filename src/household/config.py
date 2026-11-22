import re
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    database_url: str
    family_allowed_emails: str = ""
    google_client_id: str = ""
    google_client_secret: SecretStr | None = None
    session_secret: SecretStr | None = None
    public_base_url: str = "http://localhost:8001"
    openai_api_key: SecretStr | None = None
    model_name: str = "gpt-4.1-mini"
    # Set these to your provider's current rates to enable cost estimates.
    input_usd_per_million: float | None = Field(default=None, ge=0)
    output_usd_per_million: float | None = Field(default=None, ge=0)
    worker_poll_seconds: float = Field(default=1.0, gt=0)
    progress_log_seconds: float = Field(default=5.0, gt=0)
    slow_stage_seconds: float = Field(default=10.0, gt=0)

    @field_validator("family_allowed_emails")
    @classmethod
    def validate_members(cls, value):
        if not value:
            return value
        emails = [e.strip().lower() for e in value.split(",")]
        if (
            len(emails) != 5
            or len(set(emails)) != 5
            or any(not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) for email in emails)
        ):
            raise ValueError("FAMILY_ALLOWED_EMAILS must contain five distinct email addresses")
        return ",".join(emails)

    @field_validator("public_base_url")
    @classmethod
    def validate_origin(cls, value):
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
        ):
            raise ValueError("PUBLIC_BASE_URL must be an origin without a path")
        if url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError("PUBLIC_BASE_URL requires HTTPS outside localhost")
        return value.rstrip("/")

    @property
    def family_emails(self):
        return set(self.family_allowed_emails.split(",")) if self.family_allowed_emails else set()

    @property
    def secure_cookies(self):
        return self.public_base_url.startswith("https://")

    def require_web_auth(self):
        if (
            len(self.family_emails) != 5
            or not self.google_client_id
            or not self.google_client_secret
            or not self.session_secret
            or len(self.session_secret.get_secret_value()) < 32
        ):
            raise ValueError(
                "Configure FAMILY_ALLOWED_EMAILS, GOOGLE_CLIENT_ID, "
                "GOOGLE_CLIENT_SECRET and SESSION_SECRET (32+ characters)"
            )
