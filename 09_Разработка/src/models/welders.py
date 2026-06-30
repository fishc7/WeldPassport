from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import SCHEMA, Base

if TYPE_CHECKING:
    from models.projects import Obekt
    from models.workers import Svarshchik


class DokumentSvarshchika(Base):
    __tablename__ = "ДОКУМЕНТЫ_СВАРЩИКА"
    __table_args__ = {"schema": SCHEMA}

    id_dokumenta: Mapped[int] = mapped_column(
        "ID_Документа", Integer, primary_key=True, autoincrement=True
    )
    id_svarshchika: Mapped[int] = mapped_column(
        "ID_Сварщика",
        ForeignKey(f"{SCHEMA}.СВАРЩИКИ.ID_Сварщика"),
        nullable=False,
    )
    vid_dokumenta: Mapped[str | None] = mapped_column("Вид_Документа", String(100))
    nomer_dokumenta: Mapped[str | None] = mapped_column("Номер_Документа", String(100))
    kem_vydan: Mapped[str | None] = mapped_column("Кем_Выдан", String(255))
    data_vydachi: Mapped[date | None] = mapped_column("Дата_Выдачи", Date)
    data_okonchaniya: Mapped[date | None] = mapped_column("Дата_Окончания", Date)
    fayl_dokumenta: Mapped[str | None] = mapped_column("Файл_Документа", String(500))
    status_dokumenta: Mapped[str | None] = mapped_column(
        "Статус_Документа", String(50)
    )

    svarshchik: Mapped[Svarshchik] = relationship(back_populates="dokumenty")
    attestatsii: Mapped[list[AttestatsiyaSvarshchika]] = relationship(
        back_populates="dokument"
    )
    dopuski_k_obektu: Mapped[list[DopuskKObektu]] = relationship(
        back_populates="dokument"
    )


class AttestatsiyaSvarshchika(Base):
    __tablename__ = "АТТЕСТАЦИИ_СВАРЩИКОВ"
    __table_args__ = {"schema": SCHEMA}

    id_attestatsii: Mapped[int] = mapped_column(
        "ID_Аттестации", Integer, primary_key=True, autoincrement=True
    )
    id_svarshchika: Mapped[int] = mapped_column(
        "ID_Сварщика",
        ForeignKey(f"{SCHEMA}.СВАРЩИКИ.ID_Сварщика"),
        nullable=False,
    )
    id_dokumenta: Mapped[int | None] = mapped_column(
        "ID_Документа",
        ForeignKey(f"{SCHEMA}.ДОКУМЕНТЫ_СВАРЩИКА.ID_Документа"),
    )
    tip_attestatsii: Mapped[str | None] = mapped_column("Тип_Аттестации", String(100))
    sposob_svarки: Mapped[str | None] = mapped_column("Способ_Сварки", String(100))
    gruppa_materiala: Mapped[str | None] = mapped_column("Группа_Материала", String(100))
    diaapazon_diametrov: Mapped[str | None] = mapped_column(
        "Диапазон_Диаметров", String(100)
    )
    diaapazon_tolshchin: Mapped[str | None] = mapped_column(
        "Диапазон_Толщин", String(100)
    )
    polozhenie_svarки: Mapped[str | None] = mapped_column(
        "Положение_Сварки", String(100)
    )
    tip_soedineniya: Mapped[str | None] = mapped_column("Тип_Соединения", String(100))
    data_nachala: Mapped[date | None] = mapped_column("Дата_Начала", Date)
    data_okonchaniya: Mapped[date | None] = mapped_column("Дата_Окончания", Date)
    status: Mapped[str | None] = mapped_column("Статус", String(50))

    svarshchik: Mapped[Svarshchik] = relationship(back_populates="attestatsii")
    dokument: Mapped[DokumentSvarshchika | None] = relationship(
        back_populates="attestatsii"
    )


class VnutrenniyDopuskSvarshchika(Base):
    __tablename__ = "ВНУТРЕННИЕ_ДОПУСКИ_СВАРЩИКОВ"
    __table_args__ = {"schema": SCHEMA}

    id_vnutrennego_dopuskа: Mapped[int] = mapped_column(
        "ID_Внутреннего_Допуска", Integer, primary_key=True, autoincrement=True
    )
    id_svarshchika: Mapped[int] = mapped_column(
        "ID_Сварщика",
        ForeignKey(f"{SCHEMA}.СВАРЩИКИ.ID_Сварщика"),
        nullable=False,
    )
    data_proverki: Mapped[date | None] = mapped_column("Дата_Проверки", Date)
    sposob_svarки: Mapped[str | None] = mapped_column("Способ_Сварки", String(100))
    material: Mapped[str | None] = mapped_column("Материал", String(100))
    diametr: Mapped[str | None] = mapped_column("Диаметр", String(100))
    tolshchina: Mapped[str | None] = mapped_column("Толщина", String(100))
    rezultat: Mapped[str | None] = mapped_column("Результат", String(50))
    kto_proveril: Mapped[str | None] = mapped_column("Кто_Проверил", String(255))
    osnovanie: Mapped[str | None] = mapped_column("Основание", String(255))
    data_nachala_dopuskа: Mapped[date | None] = mapped_column(
        "Дата_Начала_Допуска", Date
    )
    data_okonchaniya_dopuskа: Mapped[date | None] = mapped_column(
        "Дата_Окончания_Допуска", Date
    )
    status: Mapped[str | None] = mapped_column("Статус", String(50))
    primechanie: Mapped[str | None] = mapped_column("Примечание", Text)

    svarshchik: Mapped[Svarshchik] = relationship(back_populates="vnutrennie_dopuski")


class DopuskKObektu(Base):
    __tablename__ = "ДОПУСКИ_К_ОБЪЕКТУ"
    __table_args__ = {"schema": SCHEMA}

    id_dopuskа: Mapped[int] = mapped_column(
        "ID_Допуска", Integer, primary_key=True, autoincrement=True
    )
    id_svarshchika: Mapped[int] = mapped_column(
        "ID_Сварщика",
        ForeignKey(f"{SCHEMA}.СВАРЩИКИ.ID_Сварщика"),
        nullable=False,
    )
    id_obekta: Mapped[int] = mapped_column(
        "ID_Объекта",
        ForeignKey(f"{SCHEMA}.ОБЪЕКТЫ.ID_Объекта"),
        nullable=False,
    )
    id_dokumenta: Mapped[int | None] = mapped_column(
        "ID_Документа",
        ForeignKey(f"{SCHEMA}.ДОКУМЕНТЫ_СВАРЩИКА.ID_Документа"),
    )
    data_nachala: Mapped[date | None] = mapped_column("Дата_Начала", Date)
    data_okonchaniya: Mapped[date | None] = mapped_column("Дата_Окончания", Date)
    status: Mapped[str | None] = mapped_column("Статус", String(50))
    kem_soglasovan: Mapped[str | None] = mapped_column("Кем_Согласован", String(255))

    svarshchik: Mapped[Svarshchik] = relationship(back_populates="dopuski_k_obektu")
    obekt: Mapped[Obekt] = relationship(back_populates="dopuski")
    dokument: Mapped[DokumentSvarshchika | None] = relationship(
        back_populates="dopuski_k_obektu"
    )
