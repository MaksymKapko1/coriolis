from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).parent.parent.parent


class Settings(BaseSettings):
    db_url: str
    db_echo: bool = False

    api_v1_prefix: str = "/api/v1"

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",  
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()