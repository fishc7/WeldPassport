"""Заполнение справочника должностей согласно ЕТКС."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from database import get_session
from models.spravochniki import DolzhnostETKS

DOLZHNOSTI = [
    # Профессия, разряд
    ("Электрогазосварщик", 2),
    ("Электрогазосварщик", 3),
    ("Электрогазосварщик", 4),
    ("Электрогазосварщик", 5),
    ("Электрогазосварщик", 6),
    ("Электросварщик ручной сварки", 2),
    ("Электросварщик ручной сварки", 3),
    ("Электросварщик ручной сварки", 4),
    ("Электросварщик ручной сварки", 5),
    ("Электросварщик ручной сварки", 6),
]


def main() -> None:
    with get_session() as session:
        added = 0
        for professiya, razryad in DOLZHNOSTI:
            nazvanie = f"{professiya} ({razryad}-й разряд)"
            exists = (
                session.query(DolzhnostETKS)
                .filter_by(nazvanie=nazvanie)
                .first()
            )
            if exists:
                print(f"  уже есть: {nazvanie}")
                continue
            session.add(
                DolzhnostETKS(
                    nazvanie=nazvanie,
                    professiya=professiya,
                    razryad=razryad,
                )
            )
            print(f"  добавлено: {nazvanie}")
            added += 1

        print(f"\nИтого добавлено: {added} должностей")


if __name__ == "__main__":
    main()
