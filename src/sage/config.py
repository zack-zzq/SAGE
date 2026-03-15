"""Application configuration loaded from environment variables / .env file."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Global settings – values can be overridden per-request via the Web UI."""

    # LLM defaults (can be overridden at runtime)
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model_id: str = "gpt-4o"

    # Server
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
