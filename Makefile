# Riffle — developer entry points. `make help` lists them.

SHELL := /bin/bash
COMPOSE := docker compose
API := api
TOPIC := subscription.events.v1

.DEFAULT_GOAL := help

.PHONY: help up topic down logs ps reset migrate install lint fmt typecheck test test-unit test-integration web-install web-lint web-build demo

help:  ## Show this help
	grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

up: ## Start Redpanda + ClickHouse, wait for health, ensure the topic exists
	$(COMPOSE) up -d --wait redpanda clickhouse
	$(MAKE) topic

topic:  ## Create the event topic if it is missing
	@$(COMPOSE) exec -T redpanda rpk topic describe $(TOPIC) >/dev/null 2>&1 \
		|| $(COMPOSE) exec -T redpanda rpk topic create $(TOPIC) --partitions 3 --replicas 1

down:  ## Stop all services
	$(COMPOSE) --profile app down

reset:  ## Stop everything and delete all volumes
	$(COMPOSE) --profile app down -v

ps:  ## Show service status
	$(COMPOSE) ps

logs:  ## Tail service logs
	$(COMPOSE) logs -f --tail=100

install:  ## Sync the API virtualenv
	cd $(API) && uv sync

migrate: ## Apply ClickHouse migrations
	cd $(API) && uv run riffle-migrate --dir ../clickhouse/migrations

lint:  ## Lint the API
	cd $(API) && uv run ruff check . && uv run ruff format --check .

fmt:  ## Format the API
	cd $(API) && uv run ruff check --fix . && uv run ruff format .

typecheck:  ## Type-check the API
	cd $(API) && uv run mypy src tests

test-unit:  ## Run unit tests (no services required)
	cd $(API) && uv run pytest -m "not integration"

test-integration: up migrate  ## Run integration tests against live services
	cd $(API) && uv run pytest -m integration

test: test-unit test-integration  ## Run the whole suite

web-install:  ## Install web dependencies
	cd web && npm ci

web-lint:  ## Lint and type-check the web app
	cd web && npm run lint && npm run typecheck

web-build:  ## Build the web app
	cd web && npm run build

demo: up migrate  ## Bring up everything and open the dashboard
	$(COMPOSE) --profile app up -d --build --wait
	@echo "API  → http://localhost:8000/api/health/pipeline"
	@echo "Web  → http://localhost:5173"
