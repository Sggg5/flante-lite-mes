from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.schemas.common import HealthResponse


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    settings = get_settings()
    db.execute(text("SELECT 1"))
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        database="ok",
    )
