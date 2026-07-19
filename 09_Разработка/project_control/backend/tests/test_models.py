from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.models import Base, ManagementAssessmentModel, ProjectModuleModel


def test_control_tables_live_in_dedicated_postgresql_schema() -> None:
    assert set(Base.metadata.tables) == {
        "project_control.management_assessments",
        "project_control.progress_snapshots",
        "project_control.project_modules",
        "project_control.source_syncs",
    }
    assert ProjectModuleModel.__table__.schema == "project_control"


def test_assessment_model_has_append_only_version_constraint() -> None:
    constraints = {
        constraint.name for constraint in ManagementAssessmentModel.__table__.constraints
    }
    assert "uq_management_assessment_module_version" in constraints

    sql = str(
        CreateTable(ManagementAssessmentModel.__table__).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "project_control.management_assessments" in sql
    assert "UNIQUE (module_id, version)" in sql
