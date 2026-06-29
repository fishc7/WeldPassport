from fastapi import FastAPI

from app.workforce.api import router as workforce_router

app = FastAPI(
    title="WeldPassport API",
    version="0.1.0",
    description="API системы управления сварочным производством",
)

app.include_router(workforce_router, prefix="/api/v1")
