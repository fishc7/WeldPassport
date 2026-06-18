from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import SCHEMA, Base


class Proekt(Base):
    __tablename__ = "ПРОЕКТЫ"
    __table_args__ = {"schema": SCHEMA}

    id_proekta: Mapped[int] = mapped_column(
        "ID_Проекта", Integer, primary_key=True, autoincrement=True
    )
    nazvanie: Mapped[str] = mapped_column("Название", String(255))
    zakazchik: Mapped[str | None] = mapped_column("Заказчик", String(255))
    podryadchik: Mapped[str | None] = mapped_column("Подрядчик", String(255))
    data_nachala: Mapped[date | None] = mapped_column("Дата_Начала", Date)
    data_okonchaniya: Mapped[date | None] = mapped_column("Дата_Окончания", Date)
    status: Mapped[str | None] = mapped_column("Статус", String(50))

    obekty: Mapped[list[Obekt]] = relationship(back_populates="proekt")


class Obekt(Base):
    __tablename__ = "ОБЪЕКТЫ"
    __table_args__ = {"schema": SCHEMA}

    id_obekta: Mapped[int] = mapped_column(
        "ID_Объекта", Integer, primary_key=True, autoincrement=True
    )
    id_proekta: Mapped[int] = mapped_column(
        "ID_Проекта",
        ForeignKey(f"{SCHEMA}.ПРОЕКТЫ.ID_Проекта"),
        nullable=False,
    )
    nazvanie_obekta: Mapped[str] = mapped_column("Название_Объекта", String(255))
    shifr_obekta: Mapped[str | None] = mapped_column("Шифр_Объекта", String(100))
    ploshchadka: Mapped[str | None] = mapped_column("Площадка", String(255))
    status: Mapped[str | None] = mapped_column("Статус", String(50))

    proekt: Mapped[Proekt] = relationship(back_populates="obekty")
    izometrii: Mapped[list[Izometriya]] = relationship(back_populates="obekt")
    dopuski: Mapped[list[DopuskKObektu]] = relationship(back_populates="obekt")


class Izometriya(Base):
    __tablename__ = "ИЗОМЕТРИИ"
    __table_args__ = {"schema": SCHEMA}

    id_izometrii: Mapped[int] = mapped_column(
        "ID_Изометрии", Integer, primary_key=True, autoincrement=True
    )
    id_obekta: Mapped[int] = mapped_column(
        "ID_Объекта",
        ForeignKey(f"{SCHEMA}.ОБЪЕКТЫ.ID_Объекта"),
        nullable=False,
    )
    nomer_izometrii: Mapped[str] = mapped_column("Номер_Изометрии", String(100))
    nomer_linii: Mapped[str | None] = mapped_column("Номер_Линии", String(100))
    reviziya: Mapped[str | None] = mapped_column("Ревизия", String(20))
    fayl_chertezha: Mapped[str | None] = mapped_column("Файл_Чертежа", String(500))
    status: Mapped[str | None] = mapped_column("Статус", String(50))

    obekt: Mapped[Obekt] = relationship(back_populates="izometrii")
    styki: Mapped[list[Styk]] = relationship(back_populates="izometriya")


class Styk(Base):
    __tablename__ = "СТЫКИ"
    __table_args__ = {"schema": SCHEMA}

    id_styka: Mapped[int] = mapped_column(
        "ID_Стыка", Integer, primary_key=True, autoincrement=True
    )
    id_izometrii: Mapped[int] = mapped_column(
        "ID_Изометрии",
        ForeignKey(f"{SCHEMA}.ИЗОМЕТРИИ.ID_Изометрии"),
        nullable=False,
    )
    nomer_styka: Mapped[str] = mapped_column("Номер_Стыка", String(50))
    diametr: Mapped[str | None] = mapped_column("Диаметр", String(50))
    tolshchina: Mapped[str | None] = mapped_column("Толщина", String(50))
    material_1: Mapped[str | None] = mapped_column("Материал_1", String(100))
    material_2: Mapped[str | None] = mapped_column("Материал_2", String(100))
    tip_soedineniya: Mapped[str | None] = mapped_column("Тип_Соединения", String(100))
    tip_styka: Mapped[str | None] = mapped_column("Тип_Стыка", String(100))
    sposob_svarки: Mapped[str | None] = mapped_column("Способ_Сварки", String(100))
    tekhnologiya_wps: Mapped[str | None] = mapped_column("Технология_WPS", String(100))
    status_styka: Mapped[str | None] = mapped_column("Статус_Стыка", String(50))

    izometriya: Mapped[Izometriya] = relationship(back_populates="styki")
    fakty_svarки: Mapped[list[FaktSvarки]] = relationship(back_populates="styk")
    kontroli: Mapped[list[Kontrol]] = relationship(back_populates="styk")


from models.production import FaktSvarки, Kontrol  # noqa: E402, F401
from models.welders import DopuskKObektu  # noqa: E402, F401
