from sqlalchemy import create_engine, update
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app.models import schema  # noqa: F401  (registers tables on Base.metadata)

    Base.metadata.create_all(bind=engine)


def lock_authorization(db, authorization_id: str):
    """Serialize revoke, agent evaluation, and order creation until commit.

    A no-op UPDATE acquires a write lock on SQLite and a row lock on Postgres.
    SELECT FOR UPDATE alone would silently provide no locking on SQLite.
    SQLite serializes writers database-wide; keep deployment single-worker
    until the Postgres path and its concurrency behavior are validated.
    """
    from fastapi import HTTPException
    from app.models.schema import Authorization

    result = db.execute(
        update(Authorization).where(Authorization.authorization_id == authorization_id)
        .values(used_count=Authorization.used_count)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise HTTPException(status_code=404, detail="Unknown authorization_id")
    return db.get(Authorization, authorization_id, populate_existing=True)
