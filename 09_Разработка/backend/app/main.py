from fastapi import FastAPI

from app.engineering.api import router as engineering_router
from app.engineering.heat_treatment_api import router as engineering_ht_router
from app.engineering.import_api import router as engineering_import_router
from app.hr.api import router as hr_router
from app.projects.api import router as projects_router
from app.quality.api import router as quality_router
from app.welding.api import router as ogs_router
from app.workforce.api import router as workforce_router  # deprecated — ADR-005

app = FastAPI(
    title="WeldPassport API",
    version="0.1.0",
    description="API системы управления сварочным производством",
)

app.include_router(workforce_router, prefix="/api/v1")
app.include_router(hr_router, prefix="/api/v1")
app.include_router(ogs_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(engineering_router, prefix="/api/v1")
app.include_router(engineering_ht_router, prefix="/api/v1")
app.include_router(engineering_import_router, prefix="/api/v1")
app.include_router(quality_router, prefix="/api/v1")
