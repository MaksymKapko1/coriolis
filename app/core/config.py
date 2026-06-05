from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).parent.parent.parent


class Settings(BaseSettings):
    db_url: str
    db_echo: bool = False
    encryption_master_key: str = ""
    privy_app_id: str = ""
    privy_app_secret: str = ""
    api_v1_prefix: str = "/api/v1"
    nado_network: str = "mainnet"
    cors_origins: str = (
        "http://localhost:5173,"
        "http://127.0.0.1:5173,"
        "https://coriolisxyz.xyz,"
        "https://www.coriolisxyz.xyz,"
        "https://coriolis-frontend-zeta.vercel.app"
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
