from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.hr.repository import HrRepo
from app.shared.errors import ConflictError, NotFoundError
from app.welding.models import Welder
from app.welding.repository import WeldingRepo
from app.welding.schemas import WelderCreate, WelderUpdate

WELDER_ROLE_CODE = "WELDER"


class WeldingService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._hr = HrRepo(db)
        self._repo = WeldingRepo(db)

    def list_welders(self, *, skip: int = 0, limit: int = 100) -> list[Welder]:
        return self._repo.list_welders(skip=skip, limit=limit)

    def get_welder(self, welder_id: UUID) -> Welder:
        welder = self._repo.get_welder(welder_id)
        if welder is None:
            raise NotFoundError("Сварщик", welder_id)
        return welder

    def create_welder(self, data: WelderCreate) -> Welder:
        worker = self._hr.get_worker(data.worker_id)
        if worker is None:
            raise NotFoundError("Работник", data.worker_id)

        if not self._hr.has_active_worker_role(data.worker_id, WELDER_ROLE_CODE):
            raise ConflictError("У работника нет активной роли WELDER")

        if self._repo.get_welder_by_worker_id(data.worker_id) is not None:
            raise ConflictError("Сварочный профиль для этого worker_id уже оформлен")

        if self._repo.get_welder_by_stamp_code(data.stamp_code) is not None:
            raise ConflictError("Клеймо stamp_code уже занято")

        welder = Welder(
            worker_id=data.worker_id,
            stamp_code=data.stamp_code.strip(),
            status=data.status,
            notes=data.notes,
        )
        try:
            return self._repo.create_welder(welder)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Нарушено ограничение уникальности worker_id или stamp_code"
            ) from exc

    def update_welder(self, welder_id: UUID, data: WelderUpdate) -> Welder:
        welder = self.get_welder(welder_id)
        payload = data.model_dump(exclude_unset=True)

        if "stamp_code" in payload and payload["stamp_code"] is not None:
            stamp_code = payload["stamp_code"].strip()
            existing = self._repo.get_welder_by_stamp_code(stamp_code)
            if existing is not None and existing.id != welder.id:
                raise ConflictError("Клеймо stamp_code уже занято")
            payload["stamp_code"] = stamp_code

        for field, value in payload.items():
            setattr(welder, field, value)

        try:
            return self._repo.save_welder(welder)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError("Клеймо stamp_code уже занято") from exc
