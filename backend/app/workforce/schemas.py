from datetime import date

from pydantic import BaseModel, ConfigDict


class DolzhnostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nazvanie: str
    professiya: str
    razryad: int
    etks_kod: str | None = None


# --- Работники ---

class RabotnikBase(BaseModel):
    fio: str
    tabelynyy_nomer: str | None = None
    id_dolzhnosti: int | None = None
    organizatsiya: str | None = None
    data_priema: date | None = None
    status: str | None = None


class RabotnikCreate(RabotnikBase):
    pass


class RabotnikUpdate(BaseModel):
    fio: str | None = None
    tabelynyy_nomer: str | None = None
    id_dolzhnosti: int | None = None
    organizatsiya: str | None = None
    data_priema: date | None = None
    status: str | None = None


class RabotnikOut(RabotnikBase):
    model_config = ConfigDict(from_attributes=True)

    id_rabotnika: int
    dolzhnost: str | None = None  # переходный период
    dolzhnost_ref: DolzhnostOut | None = None


# --- Сварщики ---

class SvarshchikBase(BaseModel):
    id_rabotnika: int
    kleymo: str | None = None
    razryad: str | None = None
    osnovnoy_sposob_svarки: str | None = None
    status_svarshchika: str | None = None


class SvarshchikCreate(SvarshchikBase):
    pass


class SvarshchikUpdate(BaseModel):
    kleymo: str | None = None
    razryad: str | None = None
    osnovnoy_sposob_svarки: str | None = None
    status_svarshchika: str | None = None


class SvarshchikOut(SvarshchikBase):
    model_config = ConfigDict(from_attributes=True)

    id_svarshchika: int
    rabotnik: RabotnikOut | None = None


# --- Документы ---

class DokumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_dokumenta: int
    vid_dokumenta: str | None = None
    nomer_dokumenta: str | None = None
    kem_vydan: str | None = None
    data_vydachi: date | None = None
    data_okonchaniya: date | None = None
    status_dokumenta: str | None = None


# --- Аттестации ---

class AttestatsiyaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_attestatsii: int
    tip_attestatsii: str | None = None
    sposob_svarки: str | None = None
    gruppa_materiala: str | None = None
    diaapazon_diametrov: str | None = None
    diaapazon_tolshchin: str | None = None
    polozhenie_svarки: str | None = None
    tip_soedineniya: str | None = None
    data_nachala: date | None = None
    data_okonchaniya: date | None = None
    status: str | None = None


# --- Внутренние допуски ---

class VnutrenniyDopuskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_vnutrennego_dopuskа: int
    data_proverki: date | None = None
    sposob_svarки: str | None = None
    material: str | None = None
    diametr: str | None = None
    tolshchina: str | None = None
    rezultat: str | None = None
    kto_proveril: str | None = None
    data_nachala_dopuskа: date | None = None
    data_okonchaniya_dopuskа: date | None = None
    status: str | None = None


# --- Допуски к объекту ---

class DopuskKObektuOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_dopuskа: int
    id_obekta: int
    data_nachala: date | None = None
    data_okonchaniya: date | None = None
    status: str | None = None
    kem_soglasovan: str | None = None
