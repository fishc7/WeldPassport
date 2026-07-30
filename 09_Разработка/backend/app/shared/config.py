from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "weldpassport"
    postgres_user: str = "postgres"
    postgres_password: str = ""
    postgres_schema: str = "test"
    runtime_profile: str | None = Field(
        default=None,
        validation_alias="WELDPASSPORT_RUNTIME_PROFILE",
    )
    legacy_schema: str | None = Field(
        default=None,
        validation_alias="WELDPASSPORT_LEGACY_SCHEMA",
    )

    # ── Импорт XLSX (Task 8E) ────────────────────────────────────────────────
    # Бэкенд файлового хранилища исходных XLSX: "local" (dev/тесты) или "s3".
    import_storage_backend: str = "local"
    import_storage_local_dir: str = ".import_storage"
    import_s3_bucket: str = ""
    import_s3_endpoint_url: str = ""
    import_s3_region: str = ""
    import_s3_prefix: str = "imports"
    # Серверное шифрование S3 (SSE): "AES256" | "aws:kms" | "" (по умолчанию AES256).
    import_s3_sse: str = "AES256"
    # Структурные лимиты (§4 задания): проверяются до создания staging-строк.
    import_max_file_size_bytes: int = 10 * 1024 * 1024
    import_max_rows: int = 5000
    import_max_groups: int = 2000

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
