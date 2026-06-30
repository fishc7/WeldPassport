from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import SCHEMA, Base

if TYPE_CHECKING:
    from models.spravochniki import DolzhnostETKS


class Rabotnik(Base):
    __tablename__ = "РАБОТНИКИ"
    __table_args__ = {"schema": SCHEMA}

    id_rabotnika: Mapped[int] = mapped_column(
        "ID_Работника", Integer, primary_key=True, autoincrement=True
    )
    fio: Mapped[str] = mapped_column("ФИО", String(255))
    tabelynyy_nomer: Mapped[str | None] = mapped_column("Табельный_Номер", String(50))
    dolzhnost: Mapped[str | None] = mapped_column("Должность", String(100))
    id_dolzhnosti: Mapped[int | None] = mapped_column(
        "ID_Должности",
        ForeignKey(f"{SCHEMA}.СПРАВОЧНИК_ДОЛЖНОСТЕЙ.ID_Должности"),
    )
    organizatsiya: Mapped[str | None] = mapped_column("Организация", String(255))
    data_priema: Mapped[date | None] = mapped_column("Дата_Приема", Date)
    data_uvolneniya: Mapped[date | None] = mapped_column("Дата_Увольнения", Date)
    status: Mapped[str | None] = mapped_column("Статус", String(50))

    dolzhnost_ref: Mapped[DolzhnostETKS | None] = relationship("DolzhnostETKS", back_populates="rabotniki")

    svarshchiki: Mapped[list[Svarshchik]] = relationship(back_populates="rabotnik")
    uchastniki_svarки: Mapped[list[UchastnikSvarки]] = relationship(
        back_populates="rabotnik"
    )


class Svarshchik(Base):
    __tablename__ = "СВАРЩИКИ"
    __table_args__ = {"schema": SCHEMA}

    id_svarshchika: Mapped[int] = mapped_column(
        "ID_Сварщика", Integer, primary_key=True, autoincrement=True
    )
    id_rabotnika: Mapped[int] = mapped_column(
        "ID_Работника",
        ForeignKey(f"{SCHEMA}.РАБОТНИКИ.ID_Работника"),
        nullable=False,
    )
    kleymo: Mapped[str | None] = mapped_column("Клеймо", String(50))
    razryad: Mapped[str | None] = mapped_column("Разряд", String(20))
    osnovnoy_sposob_svarки: Mapped[str | None] = mapped_column(
        "Основной_Способ_Сварки", String(100)
    )
    status_svarshchika: Mapped[str | None] = mapped_column(
        "Статус_Сварщика", String(50)
    )

    rabotnik: Mapped[Rabotnik] = relationship(back_populates="svarshchiki")
    dokumenty: Mapped[list[DokumentSvarshchika]] = relationship(
        back_populates="svarshchik"
    )
    attestatsii: Mapped[list[AttestatsiyaSvarshchika]] = relationship(
        back_populates="svarshchik"
    )
    vnutrennie_dopuski: Mapped[list[VnutrenniyDopuskSvarshchika]] = relationship(
        back_populates="svarshchik"
    )
    dopuski_k_obektu: Mapped[list[DopuskKObektu]] = relationship(
        back_populates="svarshchik"
    )
    uchastniki_svarки: Mapped[list[UchastnikSvarки]] = relationship(
        back_populates="svarshchik"
    )


from models.production import UchastnikSvarки  # noqa: E402, F401
from models.welders import (  # noqa: E402, F401
    AttestatsiyaSvarshchika,
    DokumentSvarshchika,
    DopuskKObektu,
    VnutrenniyDopuskSvarshchika,
)
