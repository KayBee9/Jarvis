from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-6"
    database_url: str | None = None
    frontend_origin: str = "http://localhost:3000"
    embedding_provider: str = "local"
    embedding_model: str = "all-MiniLM-L6-v2"
    piper_model_path: str = "models/piper/en_US-amy-medium.onnx"
    whisper_model: str = "base"



    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
