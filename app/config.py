import os
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

class Settings(BaseModel):
    DATABASE_URL: str = Field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", "sqlite+aiosqlite:///data/liga_database.db"
        )
    )
    MAX_BOT_TOKEN: str = Field(
        default_factory=lambda: os.getenv("MAX_BOT_TOKEN", "")
    )
    MAX_BOT_API_SECRET: str = Field(
        default_factory=lambda: os.getenv("MAX_BOT_API_SECRET", "")
    )
    CURFEW_START_HOUR: int = Field(
        default_factory=lambda: int(os.getenv("CURFEW_START_HOUR", "22"))
    )
    CURFEW_END_HOUR: int = Field(
        default_factory=lambda: int(os.getenv("CURFEW_END_HOUR", "7"))
    )
    MAX_API_BASE_URL: str = Field(
        default_factory=lambda: os.getenv(
            "MAX_API_BASE_URL", "https://platform-api2.max.ru"
        )
    )
    MAX_SSL_VERIFY: bool = Field(
        default_factory=lambda: os.getenv("MAX_SSL_VERIFY", "false").lower() in ("true", "1", "yes")
    )

settings = Settings()

def get_settings() -> Settings:
    return settings
