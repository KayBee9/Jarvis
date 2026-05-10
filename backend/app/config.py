from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-6"
    database_url: str | None = None
    supabase_jwt_secret: str | None = None
    dev_user_id: str = "00000000-0000-0000-0000-000000000001"
    frontend_origin: str = "http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
