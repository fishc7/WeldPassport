"""Абстракция файлового хранилища исходного XLSX (Task 8E, §5 задания).

`FileStorage` — интерфейс постоянного неизменяемого хранения артефакта
`ImportSession`. Для MVP есть два адаптера:

* `LocalFileStorage` — файловая система (dev/тесты); ключ = относительный путь;
* `S3FileStorage` — S3-совместимое приватное хранилище с серверным шифрованием
  (config-gated; boto3 импортируется лениво, чтобы тесты не требовали S3).

Хранилище не перезаписывает существующий ключ (файл внутри сессии неизменяем, §5).
Целостность гарантируется на уровне сервиса: при каждом чтении пересчитывается
SHA-256 и сравнивается с сохранённым (`verify_sha256`)."""

from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod
from uuid import uuid4

from app.shared.config import settings


def compute_sha256(data: bytes) -> str:
    """SHA-256 бинарного содержимого (hex)."""
    return hashlib.sha256(data).hexdigest()


class FileStorageError(RuntimeError):
    """Техническая ошибка хранилища (INFRASTRUCTURE-категория на уровне сервиса)."""


class FileStorage(ABC):
    """Интерфейс приватного хранилища исходных XLSX."""

    @abstractmethod
    def put(self, key: str, data: bytes, *, content_type: str) -> None:
        """Сохранить объект под ключом. Перезапись существующего ключа запрещена."""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Прочитать объект по ключу."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Есть ли объект под ключом."""

    @staticmethod
    def build_key(project_id: str, filename: str) -> str:
        """Стабильный уникальный ключ объекта: imports/<project>/<uuid>.xlsx.

        Имя не зависит от исходного имени файла (оно хранится в метаданных сессии)."""
        prefix = settings.import_s3_prefix.strip("/ ") or "imports"
        return f"{prefix}/{project_id}/{uuid4().hex}.xlsx"


class LocalFileStorage(FileStorage):
    """Файловое хранилище (dev/тесты). Базовая директория из конфига."""

    def __init__(self, base_dir: str | None = None) -> None:
        self._base = base_dir or settings.import_storage_local_dir

    def _path(self, key: str) -> str:
        # Ключ — относительный; не допускаем выхода за пределы базовой директории.
        safe = key.replace("\\", "/").lstrip("/")
        full = os.path.normpath(os.path.join(self._base, safe))
        base_abs = os.path.abspath(self._base)
        if not os.path.abspath(full).startswith(base_abs):
            raise FileStorageError("Недопустимый ключ объекта")
        return full

    def put(self, key: str, data: bytes, *, content_type: str) -> None:
        path = self._path(key)
        if os.path.exists(path):
            raise FileStorageError("Объект уже существует и не может быть перезаписан")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not os.path.exists(path):
            raise FileStorageError("Объект не найден в хранилище")
        with open(path, "rb") as fh:
            return fh.read()

    def exists(self, key: str) -> bool:
        return os.path.exists(self._path(key))


class S3FileStorage(FileStorage):
    """S3-совместимое приватное хранилище с серверным шифрованием (§5).

    boto3 импортируется лениво — модуль грузится в тестах без S3-зависимости."""

    def __init__(self) -> None:
        if not settings.import_s3_bucket:
            raise FileStorageError("Не задан import_s3_bucket для S3-хранилища")
        try:
            import boto3  # noqa: PLC0415 — ленивый импорт по решению Task 8E
        except ImportError as exc:  # pragma: no cover - зависит от окружения
            raise FileStorageError("boto3 не установлен для S3-хранилища") from exc
        kwargs: dict = {}
        if settings.import_s3_endpoint_url:
            kwargs["endpoint_url"] = settings.import_s3_endpoint_url
        if settings.import_s3_region:
            kwargs["region_name"] = settings.import_s3_region
        self._bucket = settings.import_s3_bucket
        self._sse = settings.import_s3_sse
        self._client = boto3.client("s3", **kwargs)

    def put(self, key: str, data: bytes, *, content_type: str) -> None:
        if self.exists(key):
            raise FileStorageError("Объект уже существует и не может быть перезаписан")
        extra: dict = {"ContentType": content_type}
        if self._sse:
            extra["ServerSideEncryption"] = self._sse
        try:
            self._client.put_object(
                Bucket=self._bucket, Key=key, Body=data, **extra
            )
        except Exception as exc:  # noqa: BLE001 - обёртка технической ошибки
            raise FileStorageError("Ошибка записи в S3") from exc

    def get(self, key: str) -> bytes:
        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=key)
            return resp["Body"].read()
        except Exception as exc:  # noqa: BLE001
            raise FileStorageError("Ошибка чтения из S3") from exc

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception:  # noqa: BLE001 - отсутствие объекта/ошибка → False
            return False


def get_file_storage() -> FileStorage:
    """Фабрика хранилища по конфигу приложения."""
    backend = (settings.import_storage_backend or "local").strip().lower()
    if backend == "s3":
        return S3FileStorage()
    return LocalFileStorage()
