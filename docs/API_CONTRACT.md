# API contract

HTTP APIs are not implemented in the current phase. The planned read surface includes:

- `GET /api/documents/{id}`
- `GET /api/terms/{id}`
- `GET /api/sources/{id}`
- `GET /api/search`
- `POST /api/context/export`

The Reference Hub and external consumers will use the API rather than read repository directories. Runtime, AI, draft, proposal, and publishing endpoints will be specified when their implementation phases begin.
