from sqlalchemy import select

from app.core.request_id import REQUEST_ID_PATTERN
from app.models import AuditLog


def login(client, request_id: str | None = None):
    headers = {"X-Request-ID": request_id} if request_id is not None else {}
    return client.post(
        "/api/v1/auth/login",
        headers=headers,
        json={"username": "admin", "password": "AdminTest123!"},
    )


def test_valid_request_id_is_preserved_in_response_and_audit_log(client, db):
    response = login(client, "valid-request_123")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "valid-request_123"

    audit = db.scalar(select(AuditLog).where(AuditLog.request_id == "valid-request_123"))
    assert audit is not None


def test_overlong_request_id_is_replaced_before_audit_log_write(client, db):
    overlong = "a" * 65
    response = login(client, overlong)

    assert response.status_code == 200
    request_id = response.headers["X-Request-ID"]
    assert request_id != overlong
    assert REQUEST_ID_PATTERN.fullmatch(request_id)

    audit = db.scalar(select(AuditLog).where(AuditLog.request_id == request_id))
    assert audit is not None
    assert len(audit.request_id) <= 64


def test_request_id_with_invalid_characters_is_replaced(client, db):
    response = login(client, "invalid request id!")

    assert response.status_code == 200
    request_id = response.headers["X-Request-ID"]
    assert request_id != "invalid request id!"
    assert REQUEST_ID_PATTERN.fullmatch(request_id)

    audit = db.scalar(select(AuditLog).where(AuditLog.request_id == request_id))
    assert audit is not None
