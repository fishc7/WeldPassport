from uuid import UUID

from sqlalchemy.orm import Session

from app.welding.models import Welder, WelderAdmission


class WeldingRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_welders(self, *, skip: int = 0, limit: int = 100) -> list[Welder]:
        return (
            self.db.query(Welder)
            .order_by(Welder.stamp_code)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_welder(self, welder_id: UUID) -> Welder | None:
        return self.db.query(Welder).filter(Welder.id == welder_id).first()

    def get_welder_by_worker_id(self, worker_id: int) -> Welder | None:
        return self.db.query(Welder).filter(Welder.worker_id == worker_id).first()

    def get_welder_by_stamp_code(self, stamp_code: str) -> Welder | None:
        return self.db.query(Welder).filter(Welder.stamp_code == stamp_code).first()

    def create_welder(self, welder: Welder) -> Welder:
        self.db.add(welder)
        self.db.commit()
        self.db.refresh(welder)
        return welder

    def save_welder(self, welder: Welder) -> Welder:
        self.db.commit()
        self.db.refresh(welder)
        return welder


class WelderAdmissionRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_admissions(
        self,
        *,
        worker_id: int | None = None,
        stamp_code: str | None = None,
        admission_status: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[WelderAdmission]:
        query = self.db.query(WelderAdmission)
        if worker_id is not None:
            query = query.filter(WelderAdmission.worker_id == worker_id)
        if stamp_code is not None:
            query = query.filter(WelderAdmission.stamp_code == stamp_code)
        if admission_status is not None:
            query = query.filter(WelderAdmission.admission_status == admission_status)
        return (
            query.order_by(WelderAdmission.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_admission(self, admission_id: UUID) -> WelderAdmission | None:
        return (
            self.db.query(WelderAdmission)
            .filter(WelderAdmission.id == admission_id)
            .first()
        )

    def create_admission(self, admission: WelderAdmission) -> WelderAdmission:
        self.db.add(admission)
        self.db.commit()
        self.db.refresh(admission)
        return admission

    def save_admission(self, admission: WelderAdmission) -> WelderAdmission:
        self.db.commit()
        self.db.refresh(admission)
        return admission
