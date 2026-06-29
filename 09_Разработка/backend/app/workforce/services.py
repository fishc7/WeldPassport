from sqlalchemy.orm import Session

from app.shared.errors import NotFoundError
from app.workforce.models import (
    AttestatsiyaSvarshchika,
    DokumentSvarshchika,
    DopuskKObektu,
    Rabotnik,
    Svarshchik,
    VnutrenniyDopuskSvarshchika,
)
from app.workforce.repository import RabotnikRepo, SvarshchikRepo
from app.workforce.schemas import (
    RabotnikCreate,
    RabotnikUpdate,
    SvarshchikCreate,
    SvarshchikUpdate,
)


class WorkforceService:
    def __init__(self, db: Session) -> None:
        self._workers = RabotnikRepo(db)
        self._welders = SvarshchikRepo(db)

    # --- Работники ---

    def list_workers(self, skip: int = 0, limit: int = 100) -> list[Rabotnik]:
        return self._workers.list(skip, limit)

    def get_worker(self, id: int) -> Rabotnik:
        obj = self._workers.get(id)
        if obj is None:
            raise NotFoundError("Работник", id)
        return obj

    def create_worker(self, data: RabotnikCreate) -> Rabotnik:
        return self._workers.create(data)

    def update_worker(self, id: int, data: RabotnikUpdate) -> Rabotnik:
        obj = self.get_worker(id)
        return self._workers.update(obj, data)

    # --- Сварщики ---

    def list_welders(self, skip: int = 0, limit: int = 100) -> list[Svarshchik]:
        return self._welders.list(skip, limit)

    def get_welder(self, id: int) -> Svarshchik:
        obj = self._welders.get(id)
        if obj is None:
            raise NotFoundError("Сварщик", id)
        return obj

    def create_welder(self, data: SvarshchikCreate) -> Svarshchik:
        self.get_worker(data.id_rabotnika)  # работник должен существовать
        return self._welders.create(data)

    def update_welder(self, id: int, data: SvarshchikUpdate) -> Svarshchik:
        obj = self.get_welder(id)
        return self._welders.update(obj, data)

    def get_welder_documents(self, id: int) -> list[DokumentSvarshchika]:
        self.get_welder(id)
        return self._welders.get_dokumenty(id)

    def get_welder_certifications(self, id: int) -> list[AttestatsiyaSvarshchika]:
        self.get_welder(id)
        return self._welders.get_attestatsii(id)

    def get_welder_internal_admissions(
        self, id: int
    ) -> list[VnutrenniyDopuskSvarshchika]:
        self.get_welder(id)
        return self._welders.get_vnutrennie_dopuski(id)

    def get_welder_site_admissions(self, id: int) -> list[DopuskKObektu]:
        self.get_welder(id)
        return self._welders.get_dopuski_k_obektu(id)
