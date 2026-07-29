from __future__ import annotations

import ast
from pathlib import Path

from alembic.config import Config


BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
ENV_PATH = BACKEND_DIR / "migrations" / "env.py"


def test_b04_marker_001_version_locations_is_exact_active_directory() -> None:
    config = Config(ALEMBIC_INI)
    configured = config.get_main_option("version_locations")

    assert configured is not None
    assert Path(configured).resolve() == (
        BACKEND_DIR / "migrations" / "versions"
    ).resolve()
    assert config.get_main_option("path_separator") == "os"


def test_b04_marker_002_online_and_offline_use_literal_public_pk_marker() -> None:
    tree = ast.parse(ENV_PATH.read_text(encoding="utf-8"), filename=str(ENV_PATH))
    configure_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "context"
        and node.func.attr == "configure"
    ]

    assert len(configure_calls) == 2
    for call in configure_calls:
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        assert ast.literal_eval(keywords["version_table_schema"]) == "public"
        assert ast.literal_eval(keywords["version_table_pk"]) is True
