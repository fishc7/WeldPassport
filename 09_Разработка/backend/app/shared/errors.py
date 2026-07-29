from typing import Any
from uuid import UUID

from fastapi import HTTPException


class NotFoundError(HTTPException):
    def __init__(self, entity: str, entity_id: int | UUID) -> None:
        super().__init__(status_code=404, detail=f"{entity} с id={entity_id} не найден")


class ConflictError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=409, detail=detail)


class ValidationError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=422, detail=detail)


class DomainError(HTTPException):
    """Доменная ошибка с машинным кодом (Task 5B, §13 задания / §16 ADR-011).

    `detail` — словарь `{"code", "message", ...}`, чтобы клиент мог реагировать
    программно (в т.ч. при конфликте версий передать expected/current). Отдельные
    подклассы фиксируют HTTP-семантику и обязательный набор полей.
    """

    def __init__(
        self, status_code: int, code: str, message: str, **extra: Any
    ) -> None:
        detail: dict[str, Any] = {"code": code, "message": message}
        detail.update(extra)
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


class VersionConflictError(DomainError):
    """409: несовпадение ожидаемой и текущей версии (§16 ADR-011).

    Возвращает какая именно версия конфликтует (через `code`), ожидаемое и
    текущее значения. Автоповтор команды клиентом запрещён (§16).
    """

    def __init__(
        self, code: str, *, expected_version: int | None, current_version: int
    ) -> None:
        super().__init__(
            409,
            code,
            "Конфликт версии: перечитайте Joint и повторите вручную",
            expected_version=expected_version,
            current_version=current_version,
        )


class RoleDeniedError(DomainError):
    """403: у актора нет требуемой активной роли."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(403, code, message)


class InvalidStateError(DomainError):
    """409: недопустимый переход / состояние ресурса."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(409, code, message)
