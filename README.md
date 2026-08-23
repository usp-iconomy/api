# USP Iconomy — API

Backend for the USP Iconomy platform.

## Stack

| Layer | Choice |
|---|---|
| Runtime | Python 3.13, Falcon 4 (ASGI) on Uvicorn |
| Dependencies | `uv` |
| Database | PostgreSQL 17, SQLAlchemy 2 async, Alembic |
| Queue / jobs | Redis 8 + ARQ (cron included) |
| Identity | Keycloak 26 (OIDC) — the API is a resource server |
| Validation | Pydantic v2 |
| Observability | structlog (JSON in production) |
| Quality | ruff, mypy strict, pytest |

## Getting started

```bash
make setup   # install Python 3.13, create .venv, copy .env
make up      # Postgres, Redis, Keycloak and Mailpit
make migrate # apply migrations
make dev     # API on http://localhost:8000
make check   # lint + mypy + tests
```

| Service | Where | Notes |
|---|---|---|
| API | http://localhost:8000 | |
| Keycloak | http://localhost:8080 | admin console: `admin` / `admin` |
| Mailpit | http://localhost:8025 | every e-mail Keycloak sends lands here |
| Postgres | localhost:5432 | |
| Redis | localhost:**6380** | 6379 is left free for a Redis already on the host |

```bash
curl localhost:8000/health/live    # the process is up (no I/O)
curl localhost:8000/health/ready   # dependencies are responding
```

## Identity

Keycloak owns identity — passwords, password recovery, e-mail verification,
MFA, and one day the USP single sign-on. This API never sees a password. It
validates the access token against the realm's JWKS and nothing else.

What the API owns is what the identity *means* in the domain: the platform role
(`student`, `teacher`, `admin`, `donor`), the profile, and everything downstream.
`users.external_subject` holds the `sub` claim and is the only link between the two.

Members are provisioned **just in time**: the first request carrying an unknown
`sub` creates the local row from the token's claims. There is no sign-up
endpoint, and there will not need to be one when federated members start
arriving already authenticated.

`admin` is deliberately not self-assignable: self-service administrators
would hand anyone the Explorer.

| Endpoint | |
|---|---|
| `GET /auth/me` | the signed-in member, provisioned on first sight |
| `POST /auth/me/role` | the onboarding step — set once, `student`/`teacher`/`donor` |

### The realm

`infrastructure/keycloak/realm-iconomy.json` is the source of truth, imported at
every boot. It is **hand-written and small on purpose** — a raw console export
runs to thousands of lines and stops being reviewable.

Keycloak runs in `start-dev` mode with an embedded database, so `docker compose
down && make up` always gives back the same realm. `docker compose stop/start`
keeps whatever you created while testing.

Three members ship with it, all with password `iconomy2026`:
`professora@usp.br`, `aluno@example.org`, `doador@example.org`.

If you do change something in the console, `make kc-export` snapshots the realm
so you can fold the relevant part back into the JSON by hand. The snapshot
itself is git-ignored.

## Layout

```
src/iconomy/
├── app.py        composition root — everything is wired here, by hand
├── config.py     Settings from the environment
├── worker.py     background jobs (ARQ)
├── accounts/     members: model, repository, service, resources
├── api/          Falcon resources with no domain context (health)
└── core/         db, cache, errors, logging, schemas, security, middleware
```

A domain module is a package with `models.py`, `schemas.py`, `repository.py`,
`service.py` and `resources.py`. Transactions open in the service; resources
parse, delegate and serialise.

Payloads are snake_case in Python and **camelCase on the wire**, matching the
vocabulary the web client already speaks in `front/src/types/domain.ts`.
Messages stay in English — the UI translates.

## Migrations

```bash
make revision m="create courses table"   # autogenerate
make migrate                             # apply
```

New models must be imported in `alembic/env.py`, otherwise autogenerate will not see
them.

## Tests

```bash
make test
```

Tests need Postgres, and nothing else — they create `iconomy_test` on first run.
Keycloak stays out of it: the suite mints its own RS256 tokens and serves them
through a static key source, so authentication is exercised without a container
and without the network.
