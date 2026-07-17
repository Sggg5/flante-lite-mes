from sqlalchemy import select

from app.core.security import hash_password
from app.models import AuditLog, Role, User, UserRole


def test_login_and_current_user(client):
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminTest123!"},
    )
    assert login.status_code == 200
    assert login.json()["token_type"] == "bearer"

    profile = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert profile.status_code == 200
    assert profile.json()["roles"] == ["ADMIN"]
    assert "user.manage" in profile.json()["permissions"]


def test_wrong_password_uses_generic_error(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"
    assert response.json()["message"] == "用户名或密码错误"
    assert response.json()["request_id"]


def test_protected_endpoint_requires_token(client):
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["code"] == "NOT_AUTHENTICATED"


def test_role_update_is_authorized_and_audited(client, db, admin_token):
    viewer_role = db.scalar(select(Role).where(Role.code == "VIEWER"))
    user = User(username="viewer", display_name="只读用户", password_hash=hash_password("ViewerTest123!"))
    user.role_links.append(UserRole(role=viewer_role))
    db.add(user)
    db.commit()
    db.refresh(user)

    viewer_login = client.post(
        "/api/v1/auth/login",
        json={"username": "viewer", "password": "ViewerTest123!"},
    )
    viewer_token = viewer_login.json()["access_token"]
    forbidden = client.get(
        "/api/v1/users/permission-check",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "PERMISSION_DENIED"

    response = client.put(
        f"/api/v1/users/{user.id}/roles",
        headers={"Authorization": f"Bearer {admin_token}", "X-Request-ID": "test-role-change"},
        json={"role_codes": ["PLANNER"], "reason": "阶段一权限审计测试"},
    )
    assert response.status_code == 200
    assert response.json()["role_codes"] == ["PLANNER"]

    db.expire_all()
    audit = db.scalar(select(AuditLog).where(AuditLog.request_id == "test-role-change"))
    assert audit is not None
    assert audit.before_data == {"role_codes": ["VIEWER"]}
    assert audit.after_data == {"role_codes": ["PLANNER"]}
    assert audit.reason == "阶段一权限审计测试"
