from sqlalchemy import select

from app.core.security import hash_password, verify_password
from app.models import AuditLog, Permission, Role, RolePermission, User, UserRole
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


def test_admin_can_demote_another_admin_and_audit_role_change(client, db, admin_token):
    admin_role = db.scalar(select(Role).where(Role.code == "ADMIN"))
    second_admin = User(
        username="second-admin",
        display_name="Second Admin",
        password_hash=hash_password("SecondAdminTest123!"),
        is_active=True,
    )
    second_admin.role_links.append(UserRole(role=admin_role))
    db.add(second_admin)
    db.commit()
    target_user_id = second_admin.id
    reason = "demote redundant administrator"

    response = client.put(
        f"/api/v1/users/{target_user_id}/roles",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"role_codes": ["VIEWER"], "reason": reason},
    )

    assert response.status_code == 200
    assert response.json() == {"user_id": target_user_id, "role_codes": ["VIEWER"]}

    db.expire_all()
    demoted_user = db.get(User, target_user_id)
    assert get_role_codes(demoted_user) == ["VIEWER"]

    active_admins = db.scalars(
        select(User)
        .join(UserRole)
        .join(Role)
        .where(User.is_active.is_(True), Role.code == "ADMIN")
    ).all()
    assert [user.username for user in active_admins] == ["admin"]

    audit_log = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "user.roles.update",
            AuditLog.entity_type == "user",
            AuditLog.entity_id == str(target_user_id),
        )
    )
    actor = db.scalar(select(User).where(User.username == "admin"))
    assert audit_log is not None
    assert audit_log.user_id == actor.id
    assert audit_log.before_data == {"role_codes": ["ADMIN"]}
    assert audit_log.after_data == {"role_codes": ["VIEWER"]}
    assert audit_log.reason == reason


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
