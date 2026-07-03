from uuid import UUID

from sqlalchemy.orm import Session

from app.welding.models import Welder


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
