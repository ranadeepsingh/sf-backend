# sf-backend

FastAPI and SQLAlchemy Contacts API. This is the backend fork:
https://github.com/ranadeepsingh/sf-backend (default branch: `trunk`). Its
counterpart frontend fork is https://github.com/ranadeepsingh/sf-frontend.
Do not make frontend changes from this repository.

Run the test suite with `python -m pytest`.

## Contact photo contract

Contact JSON create, replace, and patch requests do not carry image data.
`PUT /api/v1/contacts/{id}/photo` accepts multipart form field `file` as a
JPEG, PNG, or WebP image (maximum 2 MiB); it creates or replaces the image.
Responses expose `photo_url`, and `GET` on that URL returns the image bytes.
`DELETE /api/v1/contacts/{id}/photo` removes it idempotently for an existing
contact.

## Qodo

Use standalone `/review` for review and standalone `/improve` for
improvements. Ask questions in normal comments that contain `qodo`. `/ask` is
deprecated and must not be used.
