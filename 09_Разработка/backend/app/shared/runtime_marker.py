from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.shared.runtime_profile import RuntimeContractError


_MARKER_RELATION_SQL = text(
    """
    SELECT to_regclass('public.alembic_version')
    """
)
_MARKER_VERSIONS_SQL = text(
    """
    SELECT version_num
    FROM public.alembic_version
    ORDER BY version_num
    """
)


def resolve_active_alembic_head(config_path: Path | None = None) -> str:
    resolved_path = (
        Path(__file__).resolve().parents[2] / "alembic.ini"
        if config_path is None
        else config_path
    )
    try:
        config = Config(str(resolved_path))
        script_location = Path(config.get_main_option("script_location"))
        if not script_location.is_absolute():
            config.set_main_option(
                "script_location",
                str(resolved_path.parent / script_location),
            )
        heads = tuple(
            sorted(ScriptDirectory.from_config(config).get_heads())
        )
    except Exception:
        raise RuntimeContractError(
            "CANONICAL-MARKER-MISMATCH",
            "active Alembic graph could not be read",
        ) from None

    if len(heads) != 1:
        raise RuntimeContractError(
            "CANONICAL-MARKER-MISMATCH",
            "active Alembic graph does not have exactly one head",
        )
    return heads[0]


def read_canonical_marker(connection: Connection) -> tuple[str, ...]:
    try:
        marker_relation = connection.execute(
            _MARKER_RELATION_SQL
        ).scalar_one()
        if marker_relation is None:
            raise RuntimeContractError(
                "CANONICAL-MARKER-MISMATCH",
                "public Alembic marker is missing",
            )
        versions = tuple(
            sorted(
                str(version)
                for version in connection.execute(
                    _MARKER_VERSIONS_SQL
                ).scalars().all()
            )
        )
    except RuntimeContractError:
        raise
    except Exception:
        raise RuntimeContractError(
            "CANONICAL-MARKER-MISMATCH",
            "canonical marker read failed",
        ) from None
    return versions


def verify_canonical_marker(
    connection: Connection,
    expected_head: str,
) -> None:
    if read_canonical_marker(connection) != (expected_head,):
        raise RuntimeContractError(
            "CANONICAL-MARKER-MISMATCH",
            "public Alembic marker does not match",
        )
