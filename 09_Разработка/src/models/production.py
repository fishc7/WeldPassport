from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import SCHEMA, Base

if TYPE_CHECKING:
    from models.projects import Styk
    from models.workers import Rabotnik, Svarshchik


class FaktSvarки(Base):
    __tablename__ = "ФАКТЫ_СВАРКИ"
    __table_args__ = {"schema": SCHEMA}

    id_fakta_svarки: Mapped[int] = mapped_column(
        "ID_Факта_Сварки", Integer, primary_key=True, autoincrement=True
    )
    id_styka: Mapped[int] = mapped_column(
        "ID_Стыка",
        ForeignKey(f"{SCHEMA}.СТЫКИ.ID_Стыка"),
        nullable=False,
    )
    data_svarки: Mapped[date | None] = mapped_column("Дата_Сварки", Date)
    smena: Mapped[str | None] = mapped_column("Смена", String(50))
    status_raboty: Mapped[str | None] = mapped_column("Статус_Работы", String(50))
    kto_soobschil: Mapped[str | None] = mapped_column("Кто_Сообщил", String(255))
    kto_vnes: Mapped[str | None] = mapped_column("Кто_Внес", String(255))
    primechanie: Mapped[str | None] = mapped_column("Примечание", Text)

    styk: Mapped[Styk] = relationship(back_populates="fakty_svarки")
    uchastniki: Mapped[list[UchastnikSvarки]] = relationship(
        back_populates="fakt_svarки"
    )


class UchastnikSvarки(Base):
    __tablename__ = "УЧАСТНИКИ_СВАРКИ"
    __table_args__ = {"schema": SCHEMA}

    id_uchastnika: Mapped[int] = mapped_column(
        "ID_Участника", Integer, primary_key=True, autoincrement=True
    )
    id_fakta_svarки: Mapped[int] = mapped_column(
        "ID_Факта_Сварки",
        ForeignKey(f"{SCHEMA}.ФАКТЫ_СВАРКИ.ID_Факта_Сварки"),
        nullable=False,
    )
    id_rabotnika: Mapped[int] = mapped_column(
        "ID_Работника",
        ForeignKey(f"{SCHEMA}.РАБОТНИКИ.ID_Работника"),
        nullable=False,
    )
    id_svarshchika: Mapped[int | None] = mapped_column(
        "ID_Сварщика",
        ForeignKey(f"{SCHEMA}.СВАРЩИКИ.ID_Сварщика"),
    )
    rol_v_rabote: Mapped[str | None] = mapped_column("Роль_В_Работе", String(100))
    fakticheskiy_ispolnitel: Mapped[bool | None] = mapped_column(
        "Фактический_Исполнитель", Boolean, default=False
    )
    uchastok_shva: Mapped[str | None] = mapped_column("Участок_Шва", String(100))
    dopusk_proveren: Mapped[bool | None] = mapped_column(
        "Допуск_Проверен", Boolean, default=False
    )
    primechanie: Mapped[str | None] = mapped_column("Примечание", Text)

    fakt_svarки: Mapped[FaktSvarки] = relationship(back_populates="uchastniki")
    rabotnik: Mapped[Rabotnik] = relationship(back_populates="uchastniki_svarки")
    svarshchik: Mapped[Svarshchik | None] = relationship(
        back_populates="uchastniki_svarки"
    )


class Kontrol(Base):
    __tablename__ = "КОНТРОЛЬ"
    __table_args__ = {"schema": SCHEMA}

    id_kontrolya: Mapped[int] = mapped_column(
        "ID_Контроля", Integer, primary_key=True, autoincrement=True
    )
    id_styka: Mapped[int] = mapped_column(
        "ID_Стыка",
        ForeignKey(f"{SCHEMA}.СТЫКИ.ID_Стыка"),
        nullable=False,
    )
    vid_kontrolya: Mapped[str | None] = mapped_column("Вид_Контроля", String(100))
    data_kontrolya: Mapped[date | None] = mapped_column("Дата_Контроля", Date)
    kontroler: Mapped[str | None] = mapped_column("Контролер", String(255))
    rezultat: Mapped[str | None] = mapped_column("Результат", String(50))
    nomer_akta: Mapped[str | None] = mapped_column("Номер_Акта", String(100))
    fayl_dokumenta: Mapped[str | None] = mapped_column("Файл_Документа", String(500))
    primechanie: Mapped[str | None] = mapped_column("Примечание", Text)

    styk: Mapped[Styk] = relationship(back_populates="kontroli")
