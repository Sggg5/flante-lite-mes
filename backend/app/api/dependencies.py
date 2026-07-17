from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import error_payload
from app.core.security import decode_access_token
from app.models import User
from app.services.identity import get_permission_codes, get_user_by_id


bearer_scheme = HTTPBearer(auto_error=False)


def authentication_error(request: Request) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=error_payload(request, "NOT_AUTHENTICATED", "身份验证失败"),
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise authentication_error(request)
    try:
        user_id = int(decode_access_token(credentials.credentials))
    except (jwt.InvalidTokenError, ValueError):
        raise authentication_error(request) from None
    user = get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        raise authentication_error(request)
    return user


def require_permission(permission_code: str) -> Callable[..., User]:
    def dependency(request: Request, user: User = Depends(get_current_user)) -> User:
        if permission_code not in get_permission_codes(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=error_payload(request, "PERMISSION_DENIED", "没有执行此操作的权限"),
            )
        return user

    return dependency
