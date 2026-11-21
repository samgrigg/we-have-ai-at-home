from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    household_password: SecretStr = Field(min_length=12)
    openai_api_key: SecretStr | None = None
    model_name: str = "gpt-4.1-mini"
    # Set these to your provider's current rates to enable cost estimates.
    input_usd_per_million: float | None = Field(default=None, ge=0)
    output_usd_per_million: float | None = Field(default=None, ge=0)
    worker_poll_seconds: float = Field(default=1.0, gt=0)
    progress_log_seconds: float = Field(default=5.0, gt=0)
    slow_stage_seconds: float = Field(default=10.0, gt=0)
