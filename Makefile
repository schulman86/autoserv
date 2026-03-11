# ─────────────────────────────────────────────────────────────────────────────
# Makefile — удобные команды для разработки
# Все docker-команды запускаются из корня репо.
# ─────────────────────────────────────────────────────────────────────────────

COMPOSE      = docker compose -f docker/docker-compose.yml
COMPOSE_DEV  = $(COMPOSE) -f docker/docker-compose.override.yml
COMPOSE_PROD = docker compose -f docker/docker-compose.yml --env-file .env

.DEFAULT_GOAL := help

# ── Help ─────────────────────────────────────────────────────────────────────

.PHONY: help
help:
	@echo ""
	@echo "  AutoService — команды разработки"
	@echo ""
	@echo "  Окружение:"
	@echo "    make up          — поднять dev-стек (с hot-reload)"
	@echo "    make down        — остановить и удалить контейнеры"
	@echo "    make restart     — пересобрать и поднять"
	@echo "    make logs        — tail логов всех сервисов"
	@echo "    make logs-api    — только логи API"
	@echo "    make logs-bot    — только логи бота"
	@echo "    make ps          — статус контейнеров"
	@echo ""
	@echo "  База данных:"
	@echo "    make migrate     — применить все миграции"
	@echo "    make migrate-new msg=…  — создать новую миграцию"
	@echo "    make db-shell    — psql в контейнере"
	@echo "    make db-reset    — drop + migrate (только dev!)"
	@echo ""
	@echo "  Разработка:"
	@echo "    make test        — запустить все тесты"
	@echo "    make lint        — ruff check + mypy"
	@echo "    make fmt         — ruff format"
	@echo "    make shell-api   — bash в контейнере api"
	@echo "    make shell-bot   — bash в контейнере bot"
	@echo ""

# ── Окружение ────────────────────────────────────────────────────────────────

.PHONY: up
up: .env
	$(COMPOSE_DEV) up --build -d
	@echo ""
	@echo "  ✓ Стек поднят"
	@echo "  API docs: http://localhost:8000/docs"
	@echo ""

.PHONY: down
down:
	$(COMPOSE_DEV) down

.PHONY: restart
restart: down up

.PHONY: logs
logs:
	$(COMPOSE_DEV) logs -f

.PHONY: logs-api
logs-api:
	$(COMPOSE_DEV) logs -f api

.PHONY: logs-bot
logs-bot:
	$(COMPOSE_DEV) logs -f bot

.PHONY: ps
ps:
	$(COMPOSE_DEV) ps

# ── База данных ───────────────────────────────────────────────────────────────

.PHONY: migrate
migrate:
	$(COMPOSE_DEV) run --rm api alembic upgrade head

.PHONY: migrate-new
migrate-new:
	@test -n "$(msg)" || (echo "Укажите msg: make migrate-new msg='add user table'" && exit 1)
	$(COMPOSE_DEV) run --rm api alembic revision --autogenerate -m "$(msg)"

.PHONY: migrate-down
migrate-down:
	$(COMPOSE_DEV) run --rm api alembic downgrade -1

.PHONY: db-shell
db-shell:
	$(COMPOSE_DEV) exec postgres psql -U $${POSTGRES_USER:-postgres} -d $${POSTGRES_DB:-autoservice}

.PHONY: db-reset
db-reset:
	@echo "⚠ Удаляем БД и накатываем миграции заново..."
	$(COMPOSE_DEV) run --rm api alembic downgrade base
	$(COMPOSE_DEV) run --rm api alembic upgrade head
	@echo "✓ Готово"

# ── Инфраструктура ────────────────────────────────────────────────────────────

.PHONY: infra-up
infra-up: .env
	$(COMPOSE_DEV) up postgres redis -d
	@echo "✓ postgres + redis запущены"

.PHONY: infra-down
infra-down:
	$(COMPOSE_DEV) stop postgres redis

# ── Тесты и линтинг ──────────────────────────────────────────────────────────

.PHONY: test
test:
	poetry run pytest --tb=short -q

.PHONY: test-cov
test-cov:
	poetry run pytest --cov=. --cov-report=term-missing --tb=short

.PHONY: lint
lint:
	poetry run ruff check .
	poetry run mypy .

.PHONY: fmt
fmt:
	poetry run ruff format .
	poetry run ruff check --fix .

# ── Shell ─────────────────────────────────────────────────────────────────────

.PHONY: shell-api
shell-api:
	$(COMPOSE_DEV) exec api bash

.PHONY: shell-bot
shell-bot:
	$(COMPOSE_DEV) exec bot bash

# ── Утилиты ───────────────────────────────────────────────────────────────────

# Автосоздание .env из .env.example если его нет
.env:
	@test -f .env || (cp .env.example .env && echo "⚠  Создан .env из .env.example — заполните BOT_TOKEN")
