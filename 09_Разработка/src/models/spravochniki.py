from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import SCHEMA, Base

if TYPE_CHECKING:
    from models.workers import Rabotnik


class DolzhnostETKS(Base):
    __tablename__ = "СПРАВОЧНИК_ДОЛЖНОСТЕЙ"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(
        "ID_Должности", Integer, primary_key=True, autoincrement=True
    )
    nazvanie: Mapped[str] = mapped_column(
        "Наименование", String(150), nullable=False, unique=True
    )
    professiya: Mapped[str] = mapped_column("Профессия", String(100), nullable=False)
    razryad: Mapped[int] = mapped_column("Разряд", SmallInteger, nullable=False)
    etks_kod: Mapped[str | None] = mapped_column("Код_ЕТКС", String(50))

    rabotniki: Mapped[list[Rabotnik]] = relationship("Rabotnik", back_populates="dolzhnost_ref")

    def __repr__(self) -> str:
        return f"<DolzhnostETKS {self.nazvanie}>"
