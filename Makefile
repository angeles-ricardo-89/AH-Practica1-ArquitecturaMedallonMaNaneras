.PHONY: up down ps logs pipeline-ingest pipeline-parse pipeline-enrich pipeline-full test lint typecheck install evaluacion e2e

# ─── Docker ───────────────────────────────────────────────
up:
	docker compose up -d

down:
	docker compose down

ps:
	docker compose ps

logs:
	docker compose logs -f

# ─── Pipeline ─────────────────────────────────────────────
# Las opciones se pasan con ARGS, por ejemplo:
#   make pipeline-ingest ARGS="--clean"
#   make pipeline-parse  ARGS="--clean --date 2024-10-01"
#   make pipeline-enrich ARGS="--clean"
ARGS ?=

pipeline-ingest:
	cd backend && PYTHONPATH=src uv run python -m lakehouse pipeline ingest $(ARGS)

pipeline-ingest-dry:
	cd backend && PYTHONPATH=src uv run python -m lakehouse pipeline ingest --dry-run $(ARGS)

pipeline-parse:
	cd backend && PYTHONPATH=src uv run python -m lakehouse pipeline parse $(ARGS)

pipeline-enrich:
	cd backend && PYTHONPATH=src uv run python -m lakehouse pipeline enrich $(ARGS)

pipeline-full:
	cd backend && PYTHONPATH=src uv run python -m lakehouse pipeline ingest $(ARGS) && PYTHONPATH=src uv run python -m lakehouse pipeline parse $(ARGS) && PYTHONPATH=src uv run python -m lakehouse pipeline enrich $(ARGS)

evaluate-rag:
	cd backend && PYTHONPATH=src uv run python -m lakehouse evaluate-rag

# ─── Tests ────────────────────────────────────────────────
test-backend:
	cd backend && uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=90

test-frontend:
	cd frontend && pnpm test:unit

test: test-backend test-frontend

# E2E sin mocks contra backend vivo (requiere demo users en .env + llamacpp + Ollama)
# Default: el stack docker real (frontend :5174 proxya /api -> backend)
e2e:
	cd backend && bash -c 'set -a; source ../.env 2>/dev/null || true; set +a; E2E_BASE_URL=$${E2E_BASE_URL:-http://localhost:5174/api} E2E_USERNAME=$${DEMO_USER_1_USERNAME:-} E2E_PASSWORD=$${DEMO_USER_1_PASSWORD:-} uv run pytest tests/e2e -m e2e -o addopts=""'

# ─── Lint & Typecheck ─────────────────────────────────────
lint:
	cd backend && uv run ruff check src/ tests/

lint-fix:
	cd backend && uv run ruff check --fix src/ tests/ && uv run ruff format src/ tests/

typecheck-backend:
	cd backend && uv run ty check

typecheck-frontend:
	cd frontend && pnpm typecheck

typecheck: typecheck-backend typecheck-frontend

# ─── Quality all-in-one ───────────────────────────────────
check: lint typecheck test

# ─── Install ──────────────────────────────────────────────
install-backend:
	cd backend && uv sync

install-frontend:
	cd frontend && pnpm install

install: install-backend install-frontend

# ─── Dev ──────────────────────────────────────────────────
dev-backend:
	cd backend && uv run fastapi dev src/lakehouse/main.py

dev-frontend:
	cd frontend && pnpm dev

dev-full:
	cd backend && uv run fastapi dev src/lakehouse/main.py & cd frontend && pnpm dev

build-frontend:
	cd frontend && pnpm build

# ─── Evaluacion ────────────────────────────────────────────
.PHONY: evaluacion
evaluacion:
	@cd backend && PYTHONPATH=src:../evaluacion/src uv run python -m evaluador.main
