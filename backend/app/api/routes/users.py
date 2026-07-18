from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.core.database import get_db
from app.core.errors import error_payload
from app.models import Role, User, UserRole
from app.schemas.auth import UpdateUserRolesRequest, UserRolesResponse
from app.services.audit import write_audit_log
from app.services.identity import count_active_admins, get_role_codes, get_user_by_id, lock_admin_role


router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.put("/{user_id}/roles", response_model=UserRolesResponse)
def update_user_roles(
    user_id: int,
    payload: UpdateUserRolesRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission("user.manage")),
) -> UserRolesResponse:
    user = get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_payload(request, "USER_NOT_FOUND", "用户不存在"),
        )

    requested_codes = sorted(set(payload.role_codes))
    lock_admin_role(db)
    roles = list(db.scalars(select(Role).where(Role.code.in_(requested_codes))))
    found_codes = {role.code for role in roles}
    missing_codes = sorted(set(requested_codes) - found_codes)
    if missing_codes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_payload(request, "ROLE_NOT_FOUND", "包含不存在的角色", {"role_codes": missing_codes}),
        )

    before_codes = get_role_codes(user)
    removes_admin_from_active_user = user.is_active and "ADMIN" in before_codes and "ADMIN" not in requested_codes
    if removes_admin_from_active_user and count_active_admins(db) <= 1:
        error_code = "CANNOT_REMOVE_LAST_ADMIN" if actor.id == user.id else "LAST_ADMIN_REQUIRED"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_payload(
                request,
                error_code,
                "系统必须至少保留一个启用状态且具有 ADMIN 角色的用户",
            ),
        )

    user.role_links.clear()
    user.role_links.extend(UserRole(role=role) for role in roles)
    db.flush()
    write_audit_log(
        db,
        request,
        user=actor,
        action="user.roles.update",
        entity_type="user",
        entity_id=str(user.id),
        before_data={"role_codes": before_codes},
        after_data={"role_codes": requested_codes},
        reason=payload.reason,
    )
    db.commit()
    return UserRolesResponse(user_id=user.id, role_codes=requested_codes)


@router.get("/permission-check")
def permission_check(user: User = Depends(require_permission("user.manage"))) -> dict[str, str]:
    return {"message": f"{user.username} has user.manage"}
