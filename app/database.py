import base64
import binascii
import logging
import re
from collections.abc import Generator

from sqlalchemy import LargeBinary, String, create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.photo import ImageValidationError, validate_image_bytes

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _engine_kwargs(database_url: str) -> dict:
    if not database_url.startswith("sqlite"):
        return {}

    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if ":memory:" in database_url or "mode=memory" in database_url:
        # A plain in-memory SQLite database lives and dies with its connection.
        # StaticPool keeps a single connection alive so every request — and every
        # thread FastAPI hands work to — sees the same data for the process's lifetime.
        kwargs["poolclass"] = StaticPool
    return kwargs


settings = get_settings()

engine = create_engine(
    settings.database_url,
    echo=settings.sql_echo,
    **_engine_kwargs(settings.database_url),
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    if engine.dialect.name != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


_LEGACY_DATA_URL = re.compile(r"^data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/]*={0,2})$")


def _is_duplicate_column_error(error: DBAPIError) -> bool:
    message = str(error).lower()
    return "duplicate column" in message or "already exists" in message


def _add_contact_column(connection, name: str, column_type: object) -> None:
    if name in {column["name"] for column in inspect(connection).get_columns("contacts")}:
        return

    sql_type = column_type.compile(dialect=connection.dialect)
    try:
        # A savepoint leaves the outer transaction usable on Postgres if another
        # worker wins the same additive migration race.
        with connection.begin_nested():
            connection.exec_driver_sql(f"ALTER TABLE contacts ADD COLUMN {name} {sql_type}")
    except DBAPIError as error:
        if not _is_duplicate_column_error(error):
            raise

    if name not in {column["name"] for column in inspect(connection).get_columns("contacts")}:
        raise RuntimeError(f"contacts.{name} was not created during schema upgrade")


def _decode_legacy_photo(value: str) -> tuple[bytes, str] | None:
    match = _LEGACY_DATA_URL.fullmatch(value)
    if match is None:
        return None

    try:
        data = base64.b64decode(match.group(2), validate=True)
        content_type = validate_image_bytes(data, declared_content_type=match.group(1))
    except (binascii.Error, ImageValidationError):
        return None
    return data, content_type


def _migrate_legacy_data_urls(connection, columns: set[str]) -> None:
    """Preserve valid PR #2 data URLs after the blob-based replacement is deployed."""
    if "photo" not in columns:
        return

    legacy_rows = connection.execute(
        text("SELECT id, photo FROM contacts WHERE photo IS NOT NULL AND photo_data IS NULL")
    ).mappings()
    for row in legacy_rows:
        decoded = _decode_legacy_photo(row["photo"])
        if decoded is None:
            logger.warning("Skipping invalid legacy contact photo for contact %s", row["id"])
            continue
        data, content_type = decoded
        connection.execute(
            text(
                "UPDATE contacts SET photo_data = :photo_data, photo_content_type = :content_type "
                "WHERE id = :id"
            ),
            {"id": row["id"], "photo_data": data, "content_type": content_type},
        )


def upgrade_contact_photo_schema(bind: Engine = engine) -> None:
    """Add photo columns without losing rows from pre-photo or PR #2 databases."""
    with bind.begin() as connection:
        if not inspect(connection).has_table("contacts"):
            return
        _add_contact_column(connection, "photo_data", LargeBinary())
        _add_contact_column(connection, "photo_content_type", String(100))
        columns = {column["name"] for column in inspect(connection).get_columns("contacts")}
        _migrate_legacy_data_urls(connection, columns)


def init_db() -> None:
    """Create tables and safely add photo columns for existing databases."""
    from app import models  # noqa: F401  (register models on Base.metadata)

    Base.metadata.create_all(bind=engine)
    upgrade_contact_photo_schema()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a session that is always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
