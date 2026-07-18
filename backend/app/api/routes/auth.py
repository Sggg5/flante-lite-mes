from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.core.errors import error_payload
from app.core.security import create_access_token, verify_password
from app.models import User
from app.schemas.auth import LoginRequest, TokenResponse, UserProfile
from app.services.audit import write_audit_log
from app.services.identity import get_permission_codes, get_role_codes, get_user_by_username


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    user = get_user_by_username(db, payload.username)
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_payload(request, "INVALID_CREDENTIALS", "用户名或密码错误"),
        )

    user.last_login_at = datetime.now(UTC)
    write_audit_log(
        db,
        request,
        user=user,
        action="auth.login",
        entity_type="user",
        entity_id=str(user.id),
    )
    db.commit()
    token, expires_in = create_access_token(str(user.id))
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=UserProfile)
def me(user: User = Depends(get_current_user)) -> UserProfile:
    return UserProfile(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        roles=get_role_codes(user),
        permissions=get_permission_codes(user),
    )
