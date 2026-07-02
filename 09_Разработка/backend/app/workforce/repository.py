from sqlalchemy.orm import Session, joinedload, selectinload

from app.workforce.models import (
    AttestatsiyaSvarshchika,
    DokumentSvarshchika,
    DopuskKObektu,
    Rabotnik,
    Svarshchik,
    VnutrenniyDopuskSvarshchika,
)
from app.workforce.schemas import (
    RabotnikCreate,
    RabotnikUpdate,
    SvarshchikCreate,
    SvarshchikUpdate,
)


class RabotnikRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, skip: int = 0, limit: int = 100) -> list[Rabotnik]:
        return (
            self.db.query(Rabotnik)
            .options(
                joinedload(Rabotnik.dolzhnost_ref),
                selectinload(Rabotnik.svarshchiki),
            )
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get(self, id: int) -> Rabotnik | None:
        return (
            self.db.query(Rabotnik)
            .options(
                joinedload(Rabotnik.dolzhnost_ref),
                selectinload(Rabotnik.svarshchiki),
            )
            .filter(Rabotnik.id_rabotnika == id)
            .first()
        )

    def create(self, data: RabotnikCreate) -> Rabotnik:
        obj = Rabotnik(**data.model_dump())
        self.db.add(obj)
        self.db.commit()
        result = self.get(obj.id_rabotnika)
        assert result is not None
        return result

    def update(self, obj: Rabotnik, data: RabotnikUpdate) -> Rabotnik:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(obj, field, value)
        self.db.commit()
        result = self.get(obj.id_rabotnika)
        assert result is not None
        return result


class SvarshchikRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, skip: int = 0, limit: int = 100) -> list[Svarshchik]:
        return (
            self.db.query(Svarshchik)
            .options(
                joinedload(Svarshchik.rabotnik).joinedload(Rabotnik.dolzhnost_ref)
            )
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get(self, id: int) -> Svarshchik | None:
        return (
            self.db.query(Svarshchik)
            .options(
                joinedload(Svarshchik.rabotnik).joinedload(Rabotnik.dolzhnost_ref)
            )
            .filter(Svarshchik.id_svarshchika == id)
            .first()
        )

    def get_dokumenty(self, id_svarshchika: int) -> list[DokumentSvarshchika]:
        return (
            self.db.query(DokumentSvarshchika)
            .filter(DokumentSvarshchika.id_svarshchika == id_svarshchika)
            .all()
        )

    def get_attestatsii(self, id_svarshchika: int) -> list[AttestatsiyaSvarshchika]:
        return (
            self.db.query(AttestatsiyaSvarshchika)
            .filter(AttestatsiyaSvarshchika.id_svarshchika == id_svarshchika)
            .all()
        )

    def get_vnutrennie_dopuski(
        self, id_svarshchika: int
    ) -> list[VnutrenniyDopuskSvarshchika]:
        return (
            self.db.query(VnutrenniyDopuskSvarshchika)
            .filter(VnutrenniyDopuskSvarshchika.id_svarshchika == id_svarshchika)
            .all()
        )

    def get_dopuski_k_obektu(self, id_svarshchika: int) -> list[DopuskKObektu]:
        return (
            self.db.query(DopuskKObektu)
            .filter(DopuskKObektu.id_svarshchika == id_svarshchika)
            .all()
        )

    def create(self, data: SvarshchikCreate) -> Svarshchik:
        obj = Svarshchik(**data.model_dump())
        self.db.add(obj)
        self.db.commit()
        result = self.get(obj.id_svarshchika)
        assert result is not None
        return result

    def update(self, obj: Svarshchik, data: SvarshchikUpdate) -> Svarshchik:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(obj, field, value)
        self.db.commit()
        result = self.get(obj.id_svarshchika)
        assert result is not None
        return result
