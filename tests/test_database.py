from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import create_engine, inspect, text

import app.database as database
from app.database import _add_contact_photo_column


def test_photo_column_is_added_to_an_existing_contacts_table(tmp_path):
    legacy_engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'contacts.db'}")
    with legacy_engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE contacts (id INTEGER PRIMARY KEY, first_name VARCHAR(100))")
        )
        connection.execute(
            text("INSERT INTO contacts (id, first_name) VALUES (1, 'Ada')")
        )

    _add_contact_photo_column(legacy_engine)
    _add_contact_photo_column(legacy_engine)

    columns = {
        column["name"] for column in inspect(legacy_engine).get_columns("contacts")
    }
    assert "photo" in columns

    with legacy_engine.connect() as connection:
        row = connection.execute(
            text("SELECT first_name, photo FROM contacts WHERE id = 1")
        ).one()
    assert row == ("Ada", None)


def test_concurrent_photo_column_migration_is_safe(tmp_path, monkeypatch):
    legacy_engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'contacts.db'}",
        connect_args={"check_same_thread": False},
    )
    with legacy_engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE contacts (id INTEGER PRIMARY KEY, first_name VARCHAR(100))")
        )

    initial_checks = Barrier(2)
    sqlalchemy_inspect = inspect

    def synchronized_inspect(bind):
        inspector = sqlalchemy_inspect(bind)

        class SynchronizedInspector:
            def get_columns(self, table_name):
                columns = inspector.get_columns(table_name)
                if table_name == "contacts" and not any(
                    column["name"] == "photo" for column in columns
                ):
                    initial_checks.wait(timeout=5)
                return columns

        return SynchronizedInspector()

    monkeypatch.setattr(database, "inspect", synchronized_inspect)

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [
            workers.submit(_add_contact_photo_column, legacy_engine) for _ in range(2)
        ]
        for future in futures:
            future.result(timeout=5)

    columns = {
        column["name"] for column in inspect(legacy_engine).get_columns("contacts")
    }
    assert "photo" in columns
