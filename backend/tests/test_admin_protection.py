from sqlalchemy import select

from app.core.security import hash_password, verify_password
from app.models import Permission, Role, RolePermission, User, UserRole
from app.services.identity import get_role_codes, seed_identity


def test_last_admin_cannot_remove_own_admin_role(client, db, admin_token):
    admin = db.scalar(select(User).where(User.username == "admin"))

    response = client.put(
        f"/api/v1/users/{admin.id}/roles",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"role_codes": ["VIEWER"], "reason": "last admin protection"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "CANNOT_REMOVE_LAST_ADMIN"

    db.expire_all()
    admin = db.scalar(select(User).where(User.username == "admin"))
    assert get_role_codes(admin) == ["ADMIN"]


def test_role_change_cannot_leave_system_without_admin(client, db):
    planner_role = db.scalar(select(Role).where(Role.code == "PLANNER"))
    manage_permission = db.scalar(select(Permission).where(Permission.code == "user.manage"))
    planner_role.permission_links.append(RolePermission(permission=manage_permission))

    actor = User(username="planner", display_name="Planner", password_hash=hash_password("PlannerTest123!"))
    actor.role_links.append(UserRole(role=planner_role))
    db.add(actor)
    db.commit()

    actor_login = client.post(
        "/api/v1/auth/login",
        json={"username": "planner", "password": "PlannerTest123!"},
    )
    actor_token = actor_login.json()["access_token"]
    admin = db.scalar(select(User).where(User.username == "admin"))

    response = client.put(
        f"/api/v1/users/{admin.id}/roles",
        headers={"Authorization": f"Bearer {actor_token}"},
        json={"role_codes": ["VIEWER"], "reason": "cross user admin protection"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "LAST_ADMIN_REQUIRED"

    db.expire_all()
    admin = db.scalar(select(User).where(User.username == "admin"))
    assert get_role_codes(admin) == ["ADMIN"]


def test_init_db_restores_admin_role_without_resetting_password(db):
    viewer_role = db.scalar(select(Role).where(Role.code == "VIEWER"))
    user = User(
        username="existing-admin",
        display_name="Existing Admin",
        password_hash=hash_password("OriginalPass123!"),
        is_active=False,
    )
    user.role_links.append(UserRole(role=viewer_role))
    db.add(user)
    db.commit()
    original_hash = user.password_hash

    restored = seed_identity(db, "existing-admin", "NewPassShouldNotApply123!")

    db.refresh(restored)
    assert restored.is_active is True
    assert set(get_role_codes(restored)) == {"ADMIN", "VIEWER"}
    assert restored.password_hash == original_hash
    assert verify_password("OriginalPass123!", restored.password_hash)
    assert not verify_password("NewPassShouldNotApply123!", restored.password_hash)
