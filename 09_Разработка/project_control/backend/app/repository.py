from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dashboard import ManagementAssessment, ManagementStatus, ProjectModule
from app.models import ManagementAssessmentModel, ProjectModuleModel


class SqlAlchemyAssessmentRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def sync_modules(self, modules: list[ProjectModule]) -> None:
        with self._session_factory() as session, session.begin():
            for module in modules:
                row = session.scalar(
                    select(ProjectModuleModel).where(ProjectModuleModel.code == module.code)
                )
                if row is None:
                    session.add(
                        ProjectModuleModel(
                            code=module.code,
                            name=module.name,
                            stage=module.stage,
                            next_action=module.next_action,
                            weight=1,
                        )
                    )
                else:
                    row.name = module.name
                    row.stage = module.stage
                    row.next_action = module.next_action

    def append(
        self,
        module_code: str,
        status: ManagementStatus,
        reason: str,
        author: str,
    ) -> ManagementAssessment:
        with self._session_factory() as session, session.begin():
            module_id = session.scalar(
                select(ProjectModuleModel.id)
                .where(ProjectModuleModel.code == module_code)
                .with_for_update()
            )
            if module_id is None:
                raise KeyError(module_code)
            last_version = session.scalar(
                select(func.max(ManagementAssessmentModel.version)).where(
                    ManagementAssessmentModel.module_id == module_id
                )
            )
            assessment = ManagementAssessment(
                module_code=module_code,
                status=status,
                reason=reason,
                author=author,
                version=(last_version or 0) + 1,
                created_at=datetime.now(UTC),
            )
            session.add(ManagementAssessmentModel(
                module_id=module_id,
                status=assessment.status.value,
                reason=assessment.reason,
                author=assessment.author,
                version=assessment.version,
                created_at=assessment.created_at,
            ))
        return assessment

    def history(self, module_code: str) -> tuple[ManagementAssessment, ...]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(ManagementAssessmentModel)
                .join(
                    ProjectModuleModel,
                    ProjectModuleModel.id == ManagementAssessmentModel.module_id,
                )
                .where(ProjectModuleModel.code == module_code)
                .order_by(ManagementAssessmentModel.version)
            ).all()
            return tuple(self._to_domain(module_code, row) for row in rows)

    def latest(self, module_code: str) -> ManagementAssessment | None:
        history = self.history(module_code)
        return history[-1] if history else None

    @staticmethod
    def _module_id(session: Session, module_code: str) -> UUID:
        module_id = session.scalar(
            select(ProjectModuleModel.id).where(ProjectModuleModel.code == module_code)
        )
        if module_id is None:
            raise KeyError(module_code)
        return module_id

    @staticmethod
    def _to_domain(
        module_code: str,
        row: ManagementAssessmentModel,
    ) -> ManagementAssessment:
        return ManagementAssessment(
            module_code=module_code,
            status=ManagementStatus(row.status),
            reason=row.reason,
            author=row.author,
            version=row.version,
            created_at=row.created_at,
        )
