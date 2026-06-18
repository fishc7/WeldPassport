from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from config import settings


@contextmanager
def get_connection() -> Generator[psycopg.Connection, None, None]:
    with psycopg.connect(**settings.conninfo, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(f'SET search_path TO "{settings.db_schema}", public')
        yield conn
