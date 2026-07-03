from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.hr.repository import HrRepo
from app.shared.errors import ConflictError, NotFoundError, ValidationError
from app.welding.models import Welder, WelderAdmission
from app.welding.repository import WeldingRepo, WelderAdmissionRepo
from app.welding.schemas import (
    WelderAdmissionCreate,
    WelderAdmissionUpdate,
    WelderCreate,
    WelderUpdate,
    check_admission_ranges,
)

WELDER_ROLE_CODE = "WELDER"


class WeldingService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._hr = HrRepo(db)
        self._repo = WeldingRepo(db)
        self._admissions = WelderAdmissionRepo(db)

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

    def list_admissions(
        self,
        *,
        worker_id: int | None = None,
        stamp_code: str | None = None,
        admission_status: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[WelderAdmission]:
        return self._admissions.list_admissions(
            worker_id=worker_id,
            stamp_code=stamp_code,
            admission_status=admission_status,
            skip=skip,
            limit=limit,
        )

    def get_admission(self, admission_id: UUID) -> WelderAdmission:
        admission = self._admissions.get_admission(admission_id)
        if admission is None:
            raise NotFoundError("Допуск сварщика", admission_id)
        return admission

    def create_admission(self, data: WelderAdmissionCreate) -> WelderAdmission:
        worker = self._hr.get_worker(data.worker_id)
        if worker is None:
            raise NotFoundError("Работник", data.worker_id)

        admission = WelderAdmission(
            worker_id=data.worker_id,
            stamp_code=data.stamp_code.strip(),
            admission_status=data.admission_status,
            welding_methods=data.welding_methods,
            material_groups=data.material_groups,
            diameter_min=data.diameter_min,
            diameter_max=data.diameter_max,
            thickness_min=data.thickness_min,
            thickness_max=data.thickness_max,
            valid_from=data.valid_from,
            valid_until=data.valid_until,
            basis_document=data.basis_document,
            notes=data.notes,
            created_by=data.created_by,
        )
        try:
            return self._admissions.create_admission(admission)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Уже есть активный допуск с таким stamp_code"
            ) from exc

    def update_admission(
        self, admission_id: UUID, data: WelderAdmissionUpdate
    ) -> WelderAdmission:
        admission = self.get_admission(admission_id)
        payload = data.model_dump(exclude_unset=True)

        if "stamp_code" in payload and payload["stamp_code"] is not None:
            payload["stamp_code"] = payload["stamp_code"].strip()

        try:
            check_admission_ranges(
                payload.get("diameter_min", admission.diameter_min),
                payload.get("diameter_max", admission.diameter_max),
                payload.get("thickness_min", admission.thickness_min),
                payload.get("thickness_max", admission.thickness_max),
                payload.get("valid_from", admission.valid_from),
                payload.get("valid_until", admission.valid_until),
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        for field, value in payload.items():
            setattr(admission, field, value)

        try:
            return self._admissions.save_admission(admission)
        except IntegrityError as exc:
            self._db.rollback()
            raise ConflictError(
                "Уже есть активный допуск с таким stamp_code"
            ) from exc
