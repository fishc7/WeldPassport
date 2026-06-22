"""Добавление колонки ID_Должности в таблицу РАБОТНИКИ."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import text
from database import engine

# ID_ с латинской D, как в модели
SQL = (
    'ALTER TABLE test."РАБОТНИКИ" '
    'ADD COLUMN IF NOT EXISTS "ID_Должности" INTEGER '
    'REFERENCES test."СПРАВОЧНИК_ДОЛЖНОСТЕЙ"'
    '("ID_Должности")'
)

with engine.connect() as conn:
    conn.execute(text(SQL))
    conn.commit()
    print("OK: kolonka ID_Dolzhnosti dobavlena v RABOTNIKI")
