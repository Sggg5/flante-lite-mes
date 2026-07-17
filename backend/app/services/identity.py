from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Permission, Role, RolePermission, User, UserRole
from app.core.security import hash_password


DEFAULT_PERMISSIONS = {
    "system.view": "查看系统",
    "user.manage": "管理用户与角色",
    "audit.view": "查看审计日志",
}

DEFAULT_ROLES = {
    "ADMIN": ("系统管理员", set(DEFAULT_PERMISSIONS)),
    "PLANNER": ("生产计划员", {"system.view"}),
    "FOREMAN": ("班组长", {"system.view"}),
    "VIEWER": ("只读用户", {"system.view"}),
}


def user_query():
    return select(User).options(
        selectinload(User.role_links).selectinload(UserRole.role).selectinload(Role.permission_links).selectinload(
            RolePermission.permission
        )
    )


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(user_query().where(User.username == username))


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.scalar(user_query().where(User.id == user_id))


def get_role_codes(user: User) -> list[str]:
    return sorted(link.role.code for link in user.role_links)


def get_permission_codes(user: User) -> list[str]:
    return sorted(
        {
            permission_link.permission.code
            for role_link in user.role_links
            for permission_link in role_link.role.permission_links
        }
    )


def seed_identity(db: Session, admin_username: str, admin_password: str) -> User:
    permissions: dict[str, Permission] = {}
    for code, name in DEFAULT_PERMISSIONS.items():
        permission = db.scalar(select(Permission).where(Permission.code == code))
        if permission is None:
            permission = Permission(code=code, name=name)
            db.add(permission)
            db.flush()
        permissions[code] = permission

    roles: dict[str, Role] = {}
    for code, (name, permission_codes) in DEFAULT_ROLES.items():
        role = db.scalar(select(Role).where(Role.code == code))
        if role is None:
            role = Role(code=code, name=name, is_system=True)
            db.add(role)
            db.flush()
        existing = {link.permission.code for link in role.permission_links}
        for permission_code in permission_codes - existing:
            role.permission_links.append(RolePermission(permission=permissions[permission_code]))
        roles[code] = role

    user = get_user_by_username(db, admin_username)
    if user is None:
        user = User(
            username=admin_username,
            display_name="系统管理员",
            password_hash=hash_password(admin_password),
            is_active=True,
        )
        user.role_links.append(UserRole(role=roles["ADMIN"]))
        db.add(user)

    db.commit()
    return user
