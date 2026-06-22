import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import text
from database import engine

SQL = """
SELECT
    tc.constraint_name,
    tc.table_name,
    kcu.column_name,
    ccu.table_name  AS foreign_table,
    ccu.column_name AS foreign_column
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu
    ON tc.constraint_name = kcu.constraint_name
    AND tc.table_schema = kcu.table_schema
JOIN information_schema.constraint_column_usage AS ccu
    ON ccu.constraint_name = tc.constraint_name
    AND ccu.table_schema = tc.table_schema
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_schema = 'test'
  AND tc.table_name IN ('РАБОТНИКИ', 'СПРАВОЧНИК_ДОЛЖНОСТЕЙ');
"""

with engine.connect() as conn:
    rows = conn.execute(text(SQL)).fetchall()
    if not rows:
        print("FK constraints not found!")
    for row in rows:
        print(row)
