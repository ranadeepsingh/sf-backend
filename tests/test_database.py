import base64
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.database import (
    Base,
    _add_contact_gender_column,
    _backfill_legacy_addresses,
    engine,
    upgrade_contact_photo_schema,
)
from app.models import Contact


def test_photo_schema_upgrade_preserves_a_valid_legacy_data_url():
    image_bytes = (Path(__file__).parent / "fixtures" / "Rana.png").read_bytes()
    legacy_photo = f"data:image/png;base64,{base64.b64encode(image_bytes).decode()}"

    Base.metadata.drop_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE contacts (
                    id INTEGER PRIMARY KEY,
                    first_name VARCHAR(100) NOT NULL,
                    last_name VARCHAR(100) NOT NULL,
                    email VARCHAR(320) NOT NULL,
                    phone VARCHAR(40),
                    company VARCHAR(200),
                    job_title VARCHAR(200),
                    address VARCHAR(300),
                    city VARCHAR(120),
                    state VARCHAR(120),
                    postal_code VARCHAR(20),
                    country VARCHAR(120),
                    notes TEXT,
                    photo TEXT,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO contacts (id, first_name, last_name, email, photo, created_at, updated_at)
                VALUES (1, 'Rana', 'Singh', 'rana@example.com', :photo, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            ),
            {"photo": legacy_photo},
        )

    upgrade_contact_photo_schema(engine)
    upgrade_contact_photo_schema(engine)
    _add_contact_gender_column(engine)
    Base.metadata.tables["addresses"].create(bind=engine)

    columns = {column["name"] for column in inspect(engine).get_columns("contacts")}
    assert {"photo", "photo_data", "photo_content_type"} <= columns
    with Session(engine) as session:
        contact = session.get(Contact, 1)
        assert contact is not None
        assert contact.photo_data == image_bytes
        assert contact.photo_content_type == "image/png"
        assert contact.photo_url == "/api/v1/contacts/1/photo"

    newer_photo = b"newly-uploaded-photo"
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE contacts SET photo_data = :photo_data, photo_content_type = 'image/png' "
                "WHERE id = 1"
            ),
            {"photo_data": newer_photo},
        )
    upgrade_contact_photo_schema(engine)

    with Session(engine) as session:
        contact = session.get(Contact, 1)
        assert contact is not None
        assert contact.photo_data == newer_photo


def test_gender_column_is_added_and_backfilled_on_an_existing_contacts_table(
    tmp_path,
):
    legacy_engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'contacts.db'}")
    with legacy_engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE contacts (id INTEGER PRIMARY KEY, first_name VARCHAR(100))")
        )
        connection.execute(
            text("INSERT INTO contacts (id, first_name) VALUES (1, 'Ada')")
        )

    _add_contact_gender_column(legacy_engine)
    _add_contact_gender_column(legacy_engine)

    columns = {
        column["name"] for column in inspect(legacy_engine).get_columns("contacts")
    }
    assert "gender" in columns
    with legacy_engine.connect() as connection:
        assert connection.scalar(
            text("SELECT gender FROM contacts WHERE id = 1")
        ) == "unknown"


def test_legacy_addresses_are_backfilled_once_without_losing_values(tmp_path):
    legacy_engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'legacy.db'}")
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE contacts (
                    id INTEGER PRIMARY KEY,
                    first_name VARCHAR(100) NOT NULL,
                    last_name VARCHAR(100) NOT NULL,
                    email VARCHAR(320) NOT NULL,
                    address VARCHAR(300),
                    city VARCHAR(120),
                    state VARCHAR(120),
                    postal_code VARCHAR(20),
                    country VARCHAR(120)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO contacts
                    (id, first_name, last_name, email, address, city, state, postal_code, country)
                VALUES
                    (1, 'Ada', 'Lovelace', 'ada@example.com', '1 Market St', 'San Francisco',
                     'CA', '94105', 'USA'),
                    (2, 'Grace', 'Hopper', 'grace@example.com', NULL, '  ', NULL, '', NULL)
                """
            )
        )

    Base.metadata.create_all(bind=legacy_engine)
    upgrade_contact_photo_schema(legacy_engine)
    _backfill_legacy_addresses(legacy_engine)
    _backfill_legacy_addresses(legacy_engine)

    assert "addresses" in inspect(legacy_engine).get_table_names()
    assert {"photo_data", "photo_content_type"} <= {
        column["name"] for column in inspect(legacy_engine).get_columns("contacts")
    }
    with legacy_engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT contact_id, type, address, city, state, postal_code, country
                FROM addresses ORDER BY id
                """
            )
        ).all()
        contacts = connection.scalar(text("SELECT COUNT(*) FROM contacts"))

    assert contacts == 2
    assert rows == [(1, "Home", "1 Market St", "San Francisco", "CA", "94105", "USA")]


def test_backfill_does_not_duplicate_a_contact_that_already_has_an_address(tmp_path):
    legacy_engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'existing.db'}")
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE contacts (
                    id INTEGER PRIMARY KEY,
                    first_name VARCHAR(100) NOT NULL,
                    last_name VARCHAR(100) NOT NULL,
                    email VARCHAR(320) NOT NULL,
                    address VARCHAR(300),
                    city VARCHAR(120),
                    state VARCHAR(120),
                    postal_code VARCHAR(20),
                    country VARCHAR(120)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO contacts
                    (id, first_name, last_name, email, address, city, state, country)
                VALUES (1, 'Ada', 'Lovelace', 'ada@example.com', 'Legacy St', 'London',
                        'London', 'UK')
                """
            )
        )

    Base.metadata.create_all(bind=legacy_engine)
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO addresses (contact_id, type, address)
                VALUES (1, 'Work', 'Current St')
                """
            )
        )

    _backfill_legacy_addresses(legacy_engine)

    with legacy_engine.connect() as connection:
        rows = connection.execute(
            text("SELECT type, address FROM addresses WHERE contact_id = 1")
        ).all()
    assert rows == [("Work", "Current St")]


def test_concurrent_legacy_backfill_does_not_duplicate_rows(tmp_path):
    legacy_engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'concurrent.db'}",
        connect_args={"check_same_thread": False},
    )
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE contacts (
                    id INTEGER PRIMARY KEY,
                    address VARCHAR(300),
                    city VARCHAR(120),
                    state VARCHAR(120),
                    postal_code VARCHAR(20),
                    country VARCHAR(120)
                )
                """
            )
        )
        connection.execute(
            text("INSERT INTO contacts (id, city, country) VALUES (1, 'London', 'UK')")
        )

    Base.metadata.create_all(bind=legacy_engine)
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [
            workers.submit(_backfill_legacy_addresses, legacy_engine) for _ in range(2)
        ]
        for future in futures:
            future.result(timeout=5)

    with legacy_engine.connect() as connection:
        count = connection.scalar(text("SELECT COUNT(*) FROM addresses"))
    assert count == 1
