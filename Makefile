.DEFAULT_GOAL := check
.PHONY: setup secrets up down logs dev worker test lint fmt typecheck check migrate revision reset kc-export

setup: secrets
	uv sync

secrets:
	@./scripts/local-secrets.sh

up: secrets
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

reset: secrets
	docker compose down -v
	docker compose up -d
# Snapshot the running realm. The export is noisy on purpose: fold what you
# need into realm-iconomy.json by hand and delete the snapshot. That file is
# the source of truth, not the console.
kc-export:
	@. ./.env; token=$$(curl -s http://localhost:8080/realms/master/protocol/openid-connect/token \
		-d client_id=admin-cli -d username=admin --data-urlencode password=$$KC_ADMIN_PASSWORD -d grant_type=password \
		| python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])"); \
	curl -s -X POST -H "Authorization: Bearer $$token" \
		"http://localhost:8080/admin/realms/iconomy/partial-export?exportClients=true&exportGroupsAndRoles=true" \
		| python3 -m json.tool > infrastructure/keycloak/realm-export.json
	@echo "wrote infrastructure/keycloak/realm-export.json"
