import base64
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.database import Base, engine, upgrade_contact_photo_schema
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

    columns = {column["name"] for column in inspect(engine).get_columns("contacts")}
    assert {"photo", "photo_data", "photo_content_type"} <= columns
    with Session(engine) as session:
        contact = session.get(Contact, 1)
        assert contact is not None
        assert contact.photo_data == image_bytes
        assert contact.photo_content_type == "image/png"
        assert contact.photo_url == "/api/v1/contacts/1/photo"
