from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.address import (
    ADDRESS_MAX_LENGTH,
    ADDRESS_TYPES,
    CITY_MAX_LENGTH,
    COUNTRY_MAX_LENGTH,
    POSTAL_CODE_MAX_LENGTH,
    STATE_MAX_LENGTH,
)
from app.database import Base
from app.gender import GENDER_VALUES, Gender


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        CheckConstraint(
            f"gender IN ({', '.join(repr(value) for value in GENDER_VALUES)})",
            name="ck_contacts_gender",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    first_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(40))

    company: Mapped[str | None] = mapped_column(String(200))
    job_title: Mapped[str | None] = mapped_column(String(200))
    gender: Mapped[str] = mapped_column(
        String(7),
        nullable=False,
        default=Gender.UNKNOWN.value,
        server_default=Gender.UNKNOWN.value,
    )

    notes: Mapped[str | None] = mapped_column(Text)
    photo_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    photo_content_type: Mapped[str | None] = mapped_column(String(100))

    addresses: Mapped[list["Address"]] = relationship(
        back_populates="contact",
        cascade="all, delete-orphan",
        order_by="Address.id",
        lazy="selectin",
        passive_deletes=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
        nullable=False,
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def photo_url(self) -> str | None:
        return f"/api/v1/contacts/{self.id}/photo" if self.photo_data is not None else None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Contact id={self.id} email={self.email!r}>"


class Address(Base):
    __tablename__ = "addresses"
    __table_args__ = (
        CheckConstraint(
            f"type IN ({', '.join(repr(value) for value in ADDRESS_TYPES)})",
            name="ck_addresses_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(5), nullable=False)
    address: Mapped[str | None] = mapped_column(String(ADDRESS_MAX_LENGTH))
    city: Mapped[str | None] = mapped_column(String(CITY_MAX_LENGTH))
    state: Mapped[str | None] = mapped_column(String(STATE_MAX_LENGTH))
    postal_code: Mapped[str | None] = mapped_column(String(POSTAL_CODE_MAX_LENGTH))
    country: Mapped[str | None] = mapped_column(String(COUNTRY_MAX_LENGTH))

    contact: Mapped[Contact] = relationship(back_populates="addresses")
