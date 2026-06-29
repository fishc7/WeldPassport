from fastapi import HTTPException


class NotFoundError(HTTPException):
    def __init__(self, entity: str, entity_id: int) -> None:
        super().__init__(status_code=404, detail=f"{entity} с id={entity_id} не найден")


class ConflictError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=409, detail=detail)
