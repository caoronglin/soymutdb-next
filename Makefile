
# =====================================================================
# SoyMutDB Makefile
# =====================================================================
# Usage:
#   make help          - Show available commands
#   make dev           - Set up development environment
#   make start         - Start all services (Docker)
#   make stop          - Stop all services
#   make test          - Run all tests
#   make build         - Build all components
#   make backup        - Create a backup
#   make deploy-linux  - Deploy to production (Linux)
# =====================================================================

.PHONY: help dev install env db-up db-down migrate init-clickhouse start stop restart logs ps dev-compose-check prod-compose-check \
        run-api run-worker run-web run-admin \
        test test-api test-web test-e2e load-test smoke-test slow-query-report explain-query check-architecture \
        build build-web build-admin build-jbrowse build-docker \
        lint lint-fix typecheck \
        backup backup-full restore upgrade health deploy-linux \
        clean clean-all

# Configuration
CONDA_ENV ?= soymutdb-dev
DOCKER_COMPOSE = docker compose
API_DIR = apps/api
WEB_DIR = apps/web
ADMIN_DIR = apps/admin
JBROWSE_DIR = apps/jbrowse

# Colors
GREEN  := $(shell tput -Txterm setaf 2 2>/dev/null || echo "")
YELLOW := $(shell tput -Txterm setaf 3 2>/dev/null || echo "")
CYAN   := $(shell tput -Txterm setaf 6 2>/dev/null || echo "")
RESET  := $(shell tput -Txterm sgr0 2>/dev/null || echo "")

help: ## Show this help message
	@echo ""
	@echo "$(CYAN)SoyMutDB - Soybean Mutant Database$(RESET)"
	@echo ""
	@echo "Usage: make <target>"
	@echo ""
	@echo "Targets:"
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ { printf "  $(GREEN)%-18s$(RESET) %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@echo ""

# =====================================================================
# Development Setup
# =====================================================================

dev: ## Set up local development environment
	@echo "$(CYAN)Setting up development environment...$(RESET)"
	$(MAKE) env
	$(MAKE) install

install: ## Install all dependencies
	@echo "$(CYAN)Installing dependencies...$(RESET)"
	pnpm install
	cd $(API_DIR) && uv pip install -e . || pip install -e .
	cd apps/worker && uv pip install -e . || pip install -e .

env: ## Create .env from .env.example
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "$(GREEN)Created .env from .env.example$(RESET)"; \
	else \
		echo "$(YELLOW).env already exists$(RESET)"; \
	fi

# =====================================================================
# Database
# =====================================================================

DEV_COMPOSE = $(DOCKER_COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml --profile core

db-up: ## Start development data services (Docker)
	$(DEV_COMPOSE) up -d postgres clickhouse redis redis-celery minio minio-init

db-down: ## Stop development data services
	$(DEV_COMPOSE) stop postgres clickhouse redis redis-celery minio

dev-compose-check: ## Validate the development Compose contract without Docker
	python3 -m pytest -q scripts/test_development_compose_contract.py

prod-compose-check: ## Validate production runtime hardening without Docker
	python3 -m pytest -q scripts/test_production_compose_contract.py

migrate: ## Run database migrations
	@echo "$(CYAN)Running database migrations...$(RESET)"
	cd $(API_DIR) && alembic upgrade head

init-clickhouse: ## Initialize ClickHouse schema
	@echo "$(CYAN)Initializing ClickHouse...$(RESET)"
	cat infra/clickhouse/init.sql | docker exec -i $$(docker compose ps -q clickhouse) clickhouse-client --multiquery

# =====================================================================
# Running
# =====================================================================

start: ## Start all services (Docker Compose)
	$(DOCKER_COMPOSE) up -d

stop: ## Stop all services
	$(DOCKER_COMPOSE) down

restart: ## Restart all services
	$(DOCKER_COMPOSE) restart

logs: ## Follow all logs
	$(DOCKER_COMPOSE) logs -f

logs-api: ## Follow API logs
	$(DOCKER_COMPOSE) logs -f api

logs-worker: ## Follow worker logs
	$(DOCKER_COMPOSE) logs -f worker-default worker-blast worker-ingest worker-analyses

ps: ## Show service status
	$(DOCKER_COMPOSE) ps

run-api: ## Run API server locally (dev mode)
	cd $(API_DIR) && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

run-worker: ## Run Celery worker locally
	cd apps/worker && celery -A soymutdb_worker.main:celery_app worker --loglevel=info --concurrency=2

run-web: ## Run web frontend (dev mode)
	pnpm --filter @soymutdb/web dev

run-admin: ## Run admin frontend (dev mode)
	pnpm --filter @soymutdb/admin dev

# =====================================================================
# Testing
# =====================================================================

test: ## Run all tests
	$(MAKE) test-api
	$(MAKE) test-web

test-api: ## Run backend tests
	@echo "$(CYAN)Running API tests...$(RESET)"
	cd $(API_DIR) && pytest -v

test-web: ## Run frontend unit tests
	@echo "$(CYAN)Running web tests...$(RESET)"
	pnpm --filter @soymutdb/web test

test-e2e: ## Run end-to-end tests (Playwright)
	@echo "$(CYAN)Running E2E tests...$(RESET)"
	npx playwright test --config=tests/e2e/playwright.config.ts

load-test: ## Run k6 load test
	k6 run tests/load/api-load.js

smoke-test: ## Run k6 smoke test
	k6 run tests/load/smoke.js

stress-test: ## Run k6 stress test
	k6 run tests/load/variant-stress.js

check-architecture: ## Enforce backend import direction and service acyclicity
	python3 scripts/check_architecture.py

slow-query-report: ## Append pg_stat_statements Top-20 weekly baseline
	bash scripts/slow-query-report.sh

explain-query: ## Explain read-only query (Q="SELECT ...")
	bash scripts/explain-query.sh

# =====================================================================
# Building
# =====================================================================

build: ## Build all components
	$(MAKE) build-web
	$(MAKE) build-admin
	$(MAKE) build-jbrowse

build-web: ## Build web frontend
	pnpm --filter @soymutdb/web build

build-admin: ## Build admin frontend
	pnpm --filter @soymutdb/admin build

build-jbrowse: ## Build JBrowse app
	pnpm --filter @soymutdb/jbrowse build

build-docker: ## Build Docker images
	$(DOCKER_COMPOSE) build

# =====================================================================
# Code Quality
# =====================================================================

lint: ## Run linters
	@echo "$(CYAN)Linting Python...$(RESET)"
	cd $(API_DIR) && ruff check src/
	cd apps/worker && ruff check src/
	@echo "$(CYAN)Linting TypeScript...$(RESET)"
	pnpm --filter @soymutdb/web lint
	pnpm --filter @soymutdb/admin lint

lint-fix: ## Auto-fix lint issues
	cd $(API_DIR) && ruff check --fix src/
	cd apps/worker && ruff check --fix src/

typecheck: ## Run type checking
	@echo "$(CYAN)Type checking Python...$(RESET)"
	cd $(API_DIR) && mypy src/soymutdb/
	@echo "$(CYAN)Type checking TypeScript...$(RESET)"
	pnpm --filter @soymutdb/web typecheck
	pnpm --filter @soymutdb/admin typecheck

# =====================================================================
# Operations
# =====================================================================

backup: ## Create backup
	bash deploy/scripts/backup.sh

backup-full: ## Create full backup (including genomic data)
	bash deploy/scripts/backup.sh --full

restore: ## Restore from backup (specify BACKUP_DIR=...)
	@if [ -z "$(BACKUP_DIR)" ]; then \
		echo "Usage: make restore BACKUP_DIR=/path/to/backup.tar.gz"; \
		exit 1; \
	fi
	bash deploy/scripts/restore.sh $(BACKUP_DIR)

upgrade: ## Upgrade to latest version
	sudo bash deploy/scripts/upgrade.sh

health: ## Run health check
	bash deploy/scripts/healthcheck.sh

deploy-linux: ## Deploy to Linux server
	sudo bash deploy/linux/install.sh

# =====================================================================
# Cleanup
# =====================================================================

clean: ## Remove build artifacts
	rm -rf apps/web/dist
	rm -rf apps/admin/dist
	rm -rf apps/jbrowse/dist
	rm -rf packages/ui/dist
	cd $(API_DIR) && rm -rf build dist *.egg-info
	cd apps/worker && rm -rf build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.pyc" -delete 2>/dev/null || true
	rm -rf test-results

clean-all: clean ## Remove everything including node_modules and .venv
	rm -rf node_modules
	rm -rf pnpm-lock.yaml
	find . -name "node_modules" -type d -exec rm -rf {} + 2>/dev/null || true
