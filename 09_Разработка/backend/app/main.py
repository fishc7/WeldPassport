from app.shared.application_factory import create_app
from app.shared.config import settings
from app.shared.runtime_profile import resolve_runtime_configuration


runtime_configuration = resolve_runtime_configuration(
    runtime_profile=settings.runtime_profile,
    legacy_schema=settings.legacy_schema,
)

app = create_app(runtime_configuration)
