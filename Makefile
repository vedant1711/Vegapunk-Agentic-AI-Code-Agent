# Vegapunk - Autonomous Coding Agent
#
# One-command wrappers around uvicorn / npm / pytest so anyone reviewing
# the repo can run "make dev" or "make test" without knowing the specifics.

PYTHON   ?= python
PORT_API ?= 8000
PORT_WEB ?= 3000

.PHONY: help install dev dev-api dev-web test test-backend test-frontend \
        lint typecheck build clean demo docker-build

help:
	@echo "Vegapunk - Autonomous Coding Agent"
	@echo ""
	@echo "Common targets:"
	@echo "  make install         Install backend + frontend dependencies"
	@echo "  make dev-api         Run backend on :$(PORT_API) (auto-reload)"
	@echo "  make dev-web         Run frontend on :$(PORT_WEB) (auto-reload)"
	@echo "  make dev             Print instructions to run both in parallel"
	@echo "  make test            Run backend pytest + frontend typecheck + lint"
	@echo "  make test-backend    Backend pytest only (with coverage)"
	@echo "  make test-frontend   Frontend tsc + lint only"
	@echo "  make lint            Ruff (backend) + ESLint (frontend)"
	@echo "  make typecheck       mypy (backend, best-effort) + tsc (frontend)"
	@echo "  make build           Build frontend for production"
	@echo "  make demo            docker compose up --build (backend only for now)"
	@echo "  make clean           Remove caches and cloned workspaces"

install:
	$(PYTHON) -m pip install -e ".[dev]"
	cd frontend && npm install

dev-api:
	@# Uses `python -m uvicorn` (not bare `uvicorn`) so it works whether or
	@# not the venv's bin dir is on PATH - as long as the venv's `python`
	@# is first on PATH (which `source .venv/bin/activate` guarantees).
	$(PYTHON) -m uvicorn app.main:app --reload --port $(PORT_API) --reload-exclude 'workspaces/*'

dev-web:
	cd frontend && npm run dev -- --port $(PORT_WEB)

dev:
	@echo "Run these in two terminals:"
	@echo "  1) make dev-api"
	@echo "  2) make dev-web"

test: test-backend test-frontend

test-backend:
	$(PYTHON) -m pytest tests/ -v --cov --cov-report=term-missing

test-e2e:
	@# Runs the full pipeline against tests/fixtures/seed_repo with LLM +
	@# GitHub API + git push mocked out. No external services, no API keys.
	$(PYTHON) -m pytest tests/test_pipeline_e2e.py -v

test-frontend:
	cd frontend && npx tsc --noEmit && npm run lint

lint:
	$(PYTHON) -m ruff check .
	cd frontend && npm run lint

typecheck:
	@which mypy > /dev/null 2>&1 && mypy agent app tools llm || \
	  echo "mypy not installed - skipping backend typecheck"
	cd frontend && npx tsc --noEmit

build:
	cd frontend && npm run build

demo:
	docker compose up --build

docker-build:
	docker build -t vegapunk-api:latest .

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage coverage.xml
	rm -rf frontend/.next frontend/node_modules/.cache
	rm -rf workspaces/*
