# USP Iconomy — API

Backend for the USP Iconomy platform.

## Stack

| Layer | Choice |
|---|---|
| Runtime | Python 3.13, Falcon 4 (ASGI) on Uvicorn |
| Dependencies | `uv` |
| Database | PostgreSQL 17, SQLAlchemy 2 async, Alembic |
| Queue / jobs | Redis 8 + ARQ (cron included) |
| Validation | Pydantic v2 |
| Observability | structlog (JSON in production) |
| Quality | ruff, mypy strict, pytest |

## Getting started

```bash
make setup   # install Python 3.13, create .venv, copy .env
make up      # start Postgres and Redis
make dev     # API on http://localhost:8000
make check   # lint + mypy + tests
```

```bash
curl localhost:8000/health/live    # the process is up (no I/O)
curl localhost:8000/health/ready   # dependencies are responding
```

## Layout

```
src/iconomy/
├── app.py        composition root — everything is wired here, by hand
├── config.py     Settings from the environment
├── worker.py     background jobs (ARQ)
├── api/          Falcon resources with no domain context (health)
└── core/         db, cache, errors, logging, middleware
```
## Migrations

```bash
make revision m="create courses table"   # autogenerate
make migrate                             # apply
```

New models must be imported in `alembic/env.py`, otherwise autogenerate will not see
them.

