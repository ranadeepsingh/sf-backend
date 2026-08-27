from sqlalchemy import create_engine, inspect, text

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
