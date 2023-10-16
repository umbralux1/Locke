ENV_DEV ?= .env_dev

build:
	@docker compose build

down:
	@docker compose down --remove-orphans

clean: down
	@docker volume rm parser_logfiles || true

clean-all: clean
	@docker volume rm parser_postgres_data || true
	@docker volume rm parser_redis_data || true

dev:
	@ENV_DEV=$(ENV_DEV) docker compose -f docker-compose.yml -f docker-compose.dev.yml up

prod:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml up --force-recreate

prod-db:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.pgcfg.yml up --force-recreate

.PHONY: build down clean clean-all dev prod prod-db