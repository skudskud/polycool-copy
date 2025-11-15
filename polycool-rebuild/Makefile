# Polycool Development Makefile

.PHONY: help setup start stop test clean docker-up docker-down docker-logs

# Default target
help: ## Show this help message
	@echo "Polycool Development Commands:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# Setup commands
setup: ## One-command setup for new developers
	./scripts/dev/setup.sh

setup-env: ## Create .env file from template
	cp env.template .env
	@echo "✅ .env file created. Please edit it with your credentials."

# Development commands
start: ## Start the application in development mode
	./scripts/dev/start.sh

stop: ## Stop all Docker services
	docker compose down

restart: ## Restart the application
	docker compose restart

# Testing commands
test: ## Run the full test suite
	./scripts/dev/test.sh

test-unit: ## Run only unit tests
	pytest tests/unit/ -v

test-integration: ## Run only integration tests
	pytest tests/integration/ -v

test-e2e: ## Run only end-to-end tests
	pytest tests/e2e/ -v

test-cov: ## Run tests with coverage report
	pytest --cov-report=html --cov-fail-under=70
	@echo "📊 Coverage report generated in htmlcov/"

# Docker commands
docker-up: ## Start all Docker services
	docker compose up -d

docker-down: ## Stop all Docker services
	docker compose down

docker-logs: ## Show Docker logs
	docker compose logs -f

docker-ps: ## Show Docker service status
	docker compose ps

# Database commands
db-init: ## Initialize database schema
	python -c "import asyncio; from core.database.connection import init_db; asyncio.run(init_db())"

db-reset: ## Reset database (WARNING: destroys all data)
	docker compose down postgres
	docker volume rm polycool_postgres_data
	docker compose up -d postgres
	sleep 5
	make db-init

# Code quality commands
lint: ## Run linting (black, isort, flake8)
	black telegram_bot core data_ingestion infrastructure
	isort telegram_bot core data_ingestion infrastructure
	flake8 telegram_bot core data_ingestion infrastructure

format: ## Format code with black and isort
	black telegram_bot core data_ingestion infrastructure
	isort telegram_bot core data_ingestion infrastructure

type-check: ## Run mypy type checking
	mypy telegram_bot core data_ingestion infrastructure

quality: ## Run all code quality checks
	make lint
	make type-check
	make test

# Cleaning commands
clean: ## Clean up temporary files and caches
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.pyd" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".coverage" -exec rm -rf {} +
	find . -type d -name "htmlcov" -exec rm -rf {} +

clean-all: clean ## Clean everything including Docker volumes
	docker compose down -v
	docker system prune -f

# Information commands
info: ## Show development environment info
	@echo "🐳 Docker services:"
	@docker compose ps
	@echo ""
	@echo "📊 Database: $(shell grep DATABASE_URL .env 2>/dev/null | cut -d'=' -f2 || echo 'Not configured')"
	@echo "🤖 Bot Token: $(shell grep BOT_TOKEN .env 2>/dev/null | cut -d'=' -f2 | wc -c 2>/dev/null | xargs echo | sed 's/1/Not configured/' | sed 's/[0-9]*/Configured/')"
	@echo ""
	@echo "🔗 Useful URLs:"
	@echo "  API: http://localhost:8000"
	@echo "  Health: http://localhost:8000/health"
	@echo "  API Docs: http://localhost:8000/docs"
	@echo "  pgAdmin: http://localhost:5050"
	@echo "  Redis Commander: http://localhost:8081"

deps: ## Show dependency tree
	pipdeptree

# Development helpers
shell: ## Start Python shell with project context
	python -c "import sys; sys.path.insert(0, '.'); from infrastructure.config.settings import settings; print('Settings loaded:', settings.environment)"

debug: ## Run local debugging tests
	python debug_local.py

debug-interactive: ## Run interactive debugging mode
	python debug_local.py --interactive

logs: ## Show recent logs
	@tail -f logs/polycool.log 2>/dev/null || echo "No logs found. Run 'make debug' first."

logs-errors: ## Show error logs
	@tail -f logs/errors.log 2>/dev/null || echo "No error logs found."

logs-telegram: ## Show Telegram-specific logs
	@tail -f logs/telegram.log 2>/dev/null || echo "No Telegram logs found."

migrate: ## Run database migrations (when implemented)
	@echo "🔄 Database migrations not yet implemented"
	@echo "TODO: Implement Alembic migrations"

backup: ## Backup database
	@echo "💾 Database backup not yet implemented"
	@echo "TODO: Implement backup script"

# CI/CD simulation
ci: ## Simulate CI pipeline
	make quality
	make test
	@echo "✅ CI pipeline passed!"

# Emergency commands
emergency-stop: ## Emergency stop all services
	docker compose down --remove-orphans
	docker stop $$(docker ps -aq) 2>/dev/null || true
	docker rm $$(docker ps -aq) 2>/dev/null || true

# Aliases for common commands
s: start ## Alias for start
t: test ## Alias for test
d: docker-up ## Alias for docker-up
