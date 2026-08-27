import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import __version__
from app.config import get_settings
from app.crud import count_contacts
from app.database import engine, get_db, init_db
from app.photo import MAX_MULTIPART_BODY_BYTES
from app.routers import contacts
from app.schemas import HealthResponse, RootResponse
from app.seed import seed_if_empty

logger = logging.getLogger("contacts")
settings = get_settings()

API_DESCRIPTION = """
A self-contained REST API for storing people's basic contact information.

By default the service runs against an **in-process SQLite database**, so no
external database is required — start the process and the API is ready. Data is
lost when the process exits; set `CONTACTS_DATABASE_URL` to a file or Postgres
URL to persist it.

### Conventions

* Contact request and response bodies are JSON. Photo replacement is the
  `multipart/form-data` endpoint `PUT /api/v1/contacts/{id}/photo`.
* Timestamps are ISO 8601 in UTC.
* Errors return `{"detail": "..."}`; request-validation failures (`422`) return
  FastAPI's standard `HTTPValidationError` shape.
* Collection responses are wrapped as `{items, total, limit, offset}` so clients
  can paginate.

### Interactive docs

* Swagger UI — [`/docs`](/docs)
* ReDoc — [`/redoc`](/redoc)
* Raw specification — [`/openapi.json`](/openapi.json)
"""

TAGS_METADATA = [
    {
        "name": "contacts",
        "description": (
            "Create, read, update, and delete contacts. Emails are unique across "
            "the collection, compared case-insensitively."
        ),
    },
    {
        "name": "meta",
        "description": "Service discovery and health checks. Useful for probes and smoke tests.",
    },
]
PHOTO_UPLOAD_PATH = re.compile(r"^/api/v1/contacts/\d+/photo$")


class PhotoUploadBodyLimitMiddleware:
    """Reject oversized multipart bodies before Starlette can spool uploaded files."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "PUT" or not PHOTO_UPLOAD_PATH.fullmatch(scope["path"]):
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        content_length = headers.get(b"content-length")
        if content_length is not None and content_length.isdigit() and int(content_length) > MAX_MULTIPART_BODY_BYTES:
            await self._too_large(scope, receive, send)
            return

        messages: list[Message] = []
        received = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break
            received += len(message.get("body", b""))
            if received > MAX_MULTIPART_BODY_BYTES:
                await self._too_large(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        async def replay_receive() -> Message:
            if messages:
                return messages.pop(0)
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _too_large(scope: Scope, receive: Receive, send: Send) -> None:
        await JSONResponse(
            status_code=413,
            content={"detail": "Photo upload request exceeds the allowed 2 MiB file limit."},
        )(scope, receive, send)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    logger.info("database ready: %s", settings.database_url)
    if settings.seed_data:
        added = seed_if_empty()
        if added:
            logger.info("seeded %d sample contacts", added)
    yield
    engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    summary="Self-contained Contacts REST API backed by an in-memory database.",
    description=API_DESCRIPTION,
    openapi_tags=TAGS_METADATA,
    contact={"name": "sf-backend", "url": "https://github.com/ranadeepsingh/sf-backend"},
    license_info={"name": "MIT", "identifier": "MIT"},
    servers=[{"url": "/", "description": "This server"}],
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(PhotoUploadBodyLimitMiddleware)

app.include_router(contacts.router)


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["meta"],
    operation_id="healthCheck",
    summary="Health check",
    response_description="Service status, active database dialect, and contact count.",
)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    """
    Liveness probe that also proves the database is reachable.

    Issues a real `SELECT` against the configured database, so a `200` means the
    service can actually serve requests — not merely that the process is up.
    """
    db.execute(text("SELECT 1"))
    return HealthResponse(
        status="ok",
        database=engine.dialect.name,
        contacts=count_contacts(db),
    )


@app.get(
    "/",
    response_model=RootResponse,
    tags=["meta"],
    operation_id="getRoot",
    summary="Service discovery",
    response_description="Links to the docs, the specification, and the main collections.",
)
def root() -> RootResponse:
    """Return the paths a client needs to discover the rest of the API."""
    return RootResponse(
        name=settings.app_name,
        version=__version__,
        docs="/docs",
        redoc="/redoc",
        openapi="/openapi.json",
        contacts="/api/v1/contacts",
        health="/health",
    )


def run() -> None:
    """Entry point for `contacts-api` / `python -m app.main`."""
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    run()
