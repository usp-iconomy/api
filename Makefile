.DEFAULT_GOAL := check
.PHONY: setup up down logs dev worker test lint fmt typecheck check migrate revision reset

setup:
	uv sync
	@test -f .env || cp .env.example .env

up:
	docker compose up -d
	@docker compose ps

down:
	docker compose down

logs:
	docker compose logs -f

dev:
	uv run uvicorn iconomy.app:create_app --factory --reload --host 0.0.0.0 --port 8000

worker:
	uv run arq iconomy.worker.WorkerSettings

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy

check: lint typecheck test

migrate:
	uv run alembic upgrade head

revision:
	uv run alembic revision --autogenerate -m "$(m)"

reset:
	docker compose down -v
	docker compose up -d