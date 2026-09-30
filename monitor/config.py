from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_path: str = Field("./data/driftwatch.sqlite3", alias="DRIFTWATCH_DB_PATH")
    alert_threshold: float = Field(0.17, alias="DRIFTWATCH_ALERT_THRESHOLD")
    canary_interval_minutes: int = Field(15, alias="DRIFTWATCH_CANARY_INTERVAL_MINUTES")
    rate_limit_per_session: str = Field("30/minute", alias="DRIFTWATCH_RATE_LIMIT_PER_SESSION")
    daily_quota: int = Field(500, alias="DRIFTWATCH_DAILY_QUOTA")

    groq_api_key: str = Field("", alias="GROQ_API_KEY")
    google_api_key: str = Field("", alias="GOOGLE_API_KEY")


settings = Settings()
