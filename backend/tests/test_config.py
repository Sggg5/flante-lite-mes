import pytest
from pydantic import ValidationError

from app.core.config import DEVELOPMENT_SECRET_KEY, Settings


def make_settings(**overrides):
    values = {
        "app_env": "development",
        "secret_key": "x" * 32,
        "initial_admin_password": None,
        "cors_origins": None,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_development_settings_allow_local_cors_default():
    settings = make_settings()

    assert settings.cors_origin_list == ["http://localhost:5173"]
    assert settings.import_max_file_size_mb == 64
    assert settings.import_max_file_size_bytes == 64 * 1024 * 1024


def test_production_rejects_development_secret_key():
    with pytest.raises(ValidationError) as exc_info:
        make_settings(
            app_env="production",
            secret_key=DEVELOPMENT_SECRET_KEY,
            initial_admin_password="AdminTest123!",
            cors_origins="https://mes.example.test",
        )

    assert "development default" in str(exc_info.value)


def test_secret_key_must_be_at_least_32_characters():
    with pytest.raises(ValidationError) as exc_info:
        make_settings(secret_key="too-short")

    assert "at least 32 characters" in str(exc_info.value)


def test_production_requires_initial_admin_password():
    with pytest.raises(ValidationError) as exc_info:
        make_settings(app_env="production", initial_admin_password=" ", cors_origins="https://mes.example.test")

    assert "INITIAL_ADMIN_PASSWORD" in str(exc_info.value)


def test_production_requires_explicit_cors_origins():
    with pytest.raises(ValidationError) as exc_info:
        make_settings(app_env="production", initial_admin_password="AdminTest123!", cors_origins=" ")

    assert "CORS_ORIGINS" in str(exc_info.value)


def test_valid_production_settings_are_accepted():
    settings = make_settings(
        app_env="production",
        secret_key="production-secret-key-with-32-plus-chars",
        initial_admin_password="AdminTest123!",
        cors_origins="https://mes.example.test,https://admin.example.test",
    )

    assert settings.is_production is True
    assert settings.cors_origin_list == ["https://mes.example.test", "https://admin.example.test"]
