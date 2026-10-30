.PHONY: install dev build preview lint clean docker-build docker-run

# Install dependencies
install:
	npm install

# Development server
dev:
	npm run dev

# Build for production
build:
	npm run build

# Preview production build
preview:
	npm run preview

# Lint
lint:
	npm run lint

lint-fix:
	npm run lint:fix

# Clean
clean:
	rm -rf node_modules dist

# Docker
IMAGE_NAME=tg-flow-frontend
CONTAINER_NAME=tg-flow-frontend

docker-build:
	docker build -t $(IMAGE_NAME) .

docker-run:
	docker run -d --name $(CONTAINER_NAME) -p 3000:80 $(IMAGE_NAME)

docker-stop:
	docker stop $(CONTAINER_NAME) || true
	docker rm $(CONTAINER_NAME) || true

