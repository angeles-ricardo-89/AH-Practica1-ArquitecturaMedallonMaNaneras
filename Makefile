.PHONY: up down ps logs pipeline-ingest pipeline-parse pipeline-enrich pipeline-full test lint typecheck install

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
pipeline-ingest:
	cd backend && PYTHONPATH=src uv run python -m lakehouse pipeline ingest

pipeline-ingest-dry:
	cd backend && PYTHONPATH=src uv run python -m lakehouse pipeline ingest --dry-run

pipeline-parse:
	cd backend && PYTHONPATH=src uv run python -m lakehouse pipeline parse

pipeline-enrich:
	cd backend && PYTHONPATH=src uv run python -m lakehouse pipeline enrich

pipeline-full:
	cd backend && PYTHONPATH=src uv run python -m lakehouse pipeline ingest && PYTHONPATH=src uv run python -m lakehouse pipeline parse && PYTHONPATH=src uv run python -m lakehouse pipeline enrich

evaluate-rag:
	cd backend && PYTHONPATH=src uv run python -m lakehouse evaluate-rag

# ─── Tests ────────────────────────────────────────────────
test-backend:
	cd backend && uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=90

test-frontend:
	cd frontend && pnpm test:unit

test: test-backend test-frontend

# ─── Lint & Typecheck ─────────────────────────────────────
lint:
	cd backend && uv run ruff check src/ tests/

lint-fix:
	cd backend && uv run ruff check --fix src/ tests/ && uv run ruff format src/ tests/

typecheck-backend:
	cd backend && uv run pyright src/

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
