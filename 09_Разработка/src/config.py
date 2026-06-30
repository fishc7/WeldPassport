from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    db_name: str
    db_user: str
    db_password: str
    db_schema: str

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            db_name=os.getenv("POSTGRES_DB", "WeldPassport"),
            db_user=os.getenv("POSTGRES_USER", "postgres"),
            db_password=os.getenv("POSTGRES_PASSWORD", ""),
            db_schema=os.getenv("POSTGRES_SCHEMA", "test"),
        )

    @property
    def conninfo(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.db_name,
            "user": self.db_user,
            "password": self.db_password,
        }

    @property
    def database_url(self) -> str:
        user = quote_plus(self.db_user)
        password = quote_plus(self.db_password)
        return (
            f"postgresql+psycopg://{user}:{password}"
            f"@{self.host}:{self.port}/{self.db_name}"
        )


settings = Settings.from_env()
