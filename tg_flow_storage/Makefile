.PHONY: build up down restart logs ps shell status clean health

# Pull/update Docker images
build:
	docker compose pull

# Start the PostgreSQL database
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
	NETWORK=$${NETWORK:-flow_net} && \
	export NETWORK && \
	if ! docker network inspect $$NETWORK >/dev/null 2>&1; then \
		docker network create $$NETWORK; \
	fi && \
	NETWORK=$$NETWORK docker compose up -d

# Stop the PostgreSQL database
down:
	docker compose down

# Stop and remove volumes (⚠️ WARNING: deletes all data)
clean:
	docker compose down -v

# Restart the database
restart:
	@if [ -z "$(ENV_FILE)" ]; then \
		echo "Error: ENV_FILE variable is required"; \
		echo "Usage: ENV_FILE=envs/dev/env.op make restart"; \
		exit 1; \
	fi
	$(MAKE) down
	$(MAKE) build
	$(MAKE) up ENV_FILE=$(ENV_FILE)

# View database logs
logs:
	docker compose logs -f

# Check database status
ps:
	docker compose ps

# Access PostgreSQL shell
shell:
	@if [ -z "$(ENV_FILE)" ]; then \
		echo "Error: ENV_FILE variable is required"; \
		echo "Usage: ENV_FILE=envs/dev/env.op make shell"; \
		exit 1; \
	fi
	@if [ ! -f "$(ENV_FILE)" ]; then \
		echo "Error: ENV_FILE $(ENV_FILE) not found"; \
		exit 1; \
	fi
	@export $$(cat $(ENV_FILE) | grep -v '^#' | xargs) && \
	docker compose exec db psql -U $${DB_USER:-postgres} -d $${DB_NAME:-tg_flow_storage}

# Check database health
health:
	docker compose exec db pg_isready -U postgres

