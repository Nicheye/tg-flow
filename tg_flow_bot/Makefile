.PHONY: build up down restart logs shell test format ps health clean db-tables db-schema db-sql db-generate-schema migrate migrate-down migrate-history makemigrations

IMAGE_NAME=tg-flow-bot
CONTAINER_NAME=tg-flow-bot

build:
	docker build -t $(IMAGE_NAME) .

up:
	@if [ -z "$(ENV_FILE)" ]; then \
		echo "Error: ENV_FILE variable is required"; \
		echo "Usage: ENV_FILE=envs/dev/env.op make up"; \
		exit 1; \
	fi
	@if [ ! -f "$(ENV_FILE)" ]; then \
		echo "Error: ENV_FILE $(ENV_FILE) not found"; \
		exit 1; \
	fi
	@export $$(cat $(ENV_FILE) | grep -v '^#' | xargs) && \
	if ! docker network inspect $${NETWORK:-flow_net} >/dev/null 2>&1; then \
		docker network create $${NETWORK:-flow_net}; \
	fi && \
	docker run -d \
		--name $(CONTAINER_NAME) \
		--network $${NETWORK:-flow_net} \
		-p 8081:8081 \
		-v $(PWD):/app \
		--env-file $(ENV_FILE) \
		$(IMAGE_NAME)

down:
	docker stop $(CONTAINER_NAME) || true
	docker rm $(CONTAINER_NAME) || true

restart:
	@if [ -z "$(ENV_FILE)" ]; then \
		echo "Error: ENV_FILE variable is required"; \
		echo "Usage: ENV_FILE=envs/dev/env.op make restart"; \
		exit 1; \
	fi
	$(MAKE) down
	$(MAKE) up ENV_FILE=$(ENV_FILE)

logs:
	docker logs -f $(CONTAINER_NAME)

ps:
	docker ps -f name=$(CONTAINER_NAME)

shell:
	docker exec -it $(CONTAINER_NAME) /bin/bash

test:
	docker exec $(CONTAINER_NAME) pytest -v

test-cov:
	docker exec $(CONTAINER_NAME) pytest -v --cov=bot --cov-report=term-missing

format:
	@echo "🎨 Running ruff format..."
	@docker exec $(CONTAINER_NAME) bash -c "ruff format ." || echo "ruff not installed"
	@echo "✅ Done!"

health:
	@docker ps -f name=$(CONTAINER_NAME) --format "{{.Status}}" || echo "Container is not running"

clean: down
	@echo "Cleaned up"

# Database migrations
db-tables:
	@docker exec $(CONTAINER_NAME) python -c "code = 'import asyncio\nfrom tortoise import Tortoise\nfrom config import settings\n\nasync def run():\n    await Tortoise.init(db_url=settings.database_url, modules={\"models\": [\"models\"]})\n    conn = Tortoise.get_connection(\"default\")\n    rows = await conn.execute_query(\"SELECT tablename FROM pg_tables WHERE schemaname=\\'public\\'\")\n    print(\"Tables:\", [r[\"tablename\"] for r in rows[1]])\n    await Tortoise.close_connections()\n\nasyncio.run(run())'\nexec(code)"

db-schema:
	@docker exec $(CONTAINER_NAME) python -c "code = 'import asyncio\nfrom tortoise import Tortoise\nfrom config import settings\n\nasync def run():\n    await Tortoise.init(db_url=settings.database_url, modules={\"models\": [\"models\"]})\n    conn = Tortoise.get_connection(\"default\")\n    rows = await conn.execute_query(\"SELECT column_name, data_type FROM information_schema.columns WHERE table_name=\\'mentioned_messages\\'\")\n    print(\"mentioned_messages columns:\")\n    for r in rows[1]:\n        print(f\"  {r[\\\"column_name\\\"]}: {r[\\\"data_type\\\"]}\")\n    await Tortoise.close_connections()\n\nasyncio.run(run())'\nexec(code)"

db-sql:
	@if [ -z "$(SQL)" ]; then \
		echo "Usage: make db-sql SQL=\"ALTER TABLE ...\""; \
		exit 1; \
	fi
	@docker exec $(CONTAINER_NAME) python -c "code = 'import asyncio\nfrom tortoise import Tortoise\nfrom config import settings\n\nasync def run():\n    await Tortoise.init(db_url=settings.database_url, modules={\"models\": [\"models\"]})\n    conn = Tortoise.get_connection(\"default\")\n    await conn.execute_query(\\'$(SQL)\\')\n    print(\"Done!\")\n    await Tortoise.close_connections()\n\nasyncio.run(run())'\nexec(code)"

db-generate-schema:
	@docker exec $(CONTAINER_NAME) python -c "code = 'import asyncio\nfrom tortoise import Tortoise\nfrom config import settings\n\nasync def run():\n    await Tortoise.init(db_url=settings.database_url, modules={\"models\": [\"models\"]})\n    await Tortoise.generate_schemas(safe=True)\n    print(\"Schema generated!\")\n    await Tortoise.close_connections()\n\nasyncio.run(run())'\nexec(code)"

# Aerich migrations
auth-migrate:
	@test -n "$(ENV_FILE)" -a -f "$(ENV_FILE)" || { echo "Usage: ENV_FILE=envs/dev/env.op make auth-migrate"; exit 1; }
	@export $$(cat $(ENV_FILE) | grep -v '^#' | xargs) && \
	docker run --rm --network $${NETWORK:-flow_net} -v $(PWD):/app --env-file $(ENV_FILE) $(IMAGE_NAME) python manage.py migrate

auth-migration-status:
	@test -n "$(ENV_FILE)" -a -f "$(ENV_FILE)" || { echo "Usage: ENV_FILE=envs/dev/env.op make auth-migration-status"; exit 1; }
	@export $$(cat $(ENV_FILE) | grep -v '^#' | xargs) && \
	docker run --rm --network $${NETWORK:-flow_net} -v $(PWD):/app --env-file $(ENV_FILE) $(IMAGE_NAME) python manage.py showmigrations

migrate:
	@docker exec $(CONTAINER_NAME) aerich upgrade

migrate-down:
	@docker exec $(CONTAINER_NAME) aerich downgrade

migrate-history:
	@docker exec $(CONTAINER_NAME) aerich history

makemigrations:
	@if [ -z "$(MSG)" ]; then \
		echo "Usage: MSG='add chat messages' make makemigrations"; \
		exit 1; \
	fi
	@docker exec $(CONTAINER_NAME) aerich migrate --name "$(MSG)"
