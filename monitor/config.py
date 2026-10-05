from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_path: str = Field("./data/driftwatch.sqlite3", alias="DRIFTWATCH_DB_PATH")
    alert_threshold: float = Field(0.17, alias="DRIFTWATCH_ALERT_THRESHOLD")
    canary_interval_minutes: int = Field(15, alias="DRIFTWATCH_CANARY_INTERVAL_MINUTES")
    rate_limit_per_session: str = Field("30/minute", alias="DRIFTWATCH_RATE_LIMIT_PER_SESSION")
    daily_quota: int = Field(500, alias="DRIFTWATCH_DAILY_QUOTA")

    # Comma-separated browser origins allowed by CORS (the Vercel dashboard URL).
    cors_origins: str = Field("http://localhost:3000", alias="DRIFTWATCH_CORS_ORIGINS")

    # Forces SimulatedLLMClient even when provider keys are set. Use for
    # e2e/smoke runs so they never spend real provider quota (D-035).
    force_simulated: bool = Field(False, alias="DRIFTWATCH_FORCE_SIMULATED")

    # "sentence-transformers" (torch, default) or "onnx" (fastembed, same model,
    # ~5x less RAM - use on Render's 512 MB free tier).
    embedder: str = Field("sentence-transformers", alias="DRIFTWATCH_EMBEDDER")

    groq_api_key: str = Field("", alias="GROQ_API_KEY")
    google_api_key: str = Field("", alias="GOOGLE_API_KEY")

    # Cloud control plane (Spec_Upgrade.md section 6.5). Empty by default -
    # local-only mode must work with none of these set. supabase_jwt_secret
    # is the legacy HS256 project JWT secret used to verify a Supabase
    # Auth access token's signature without a network round-trip per
    # request; never logged, never sent to the frontend.
    supabase_url: str = Field("", alias="SUPABASE_URL")
    supabase_anon_key: str = Field("", alias="SUPABASE_ANON_KEY")
    supabase_jwt_secret: str = Field("", alias="SUPABASE_JWT_SECRET")

    # Platform operators (Spec_Upgrade.md section 5.4). Explicit allowlist of
    # auth user ids, comma-separated. Never derived from email domain or
    # user-controlled metadata; org owner/admin roles do not grant this.
    platform_admin_user_ids: str = Field("", alias="PLATFORM_ADMIN_USER_IDS")


settings = Settings()
