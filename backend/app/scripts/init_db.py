from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.identity import seed_identity


def main() -> None:
    settings = get_settings()
    if not settings.initial_admin_password:
        raise SystemExit("INITIAL_ADMIN_PASSWORD is required to initialize the administrator")
    with SessionLocal() as db:
        seed_identity(db, settings.initial_admin_username, settings.initial_admin_password)
    print(f"Initialized roles, permissions and administrator '{settings.initial_admin_username}'.")


if __name__ == "__main__":
    main()
