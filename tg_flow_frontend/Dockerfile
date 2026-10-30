# Build stage
FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
ARG VITE_API_URL
ARG VITE_AUTH_API_URL
ARG VITE_BOT_USERNAME
RUN npm run build

# Production stage
FROM nginx:alpine

# Copy built files
COPY --from=builder /app/dist /usr/share/nginx/html

# The nginx image renders this template at startup, allowing a runtime upstream.
ENV BOT_API_UPSTREAM=http://host.docker.internal:8081
ENV TRUSTED_PROXY_RULES=""
ENV NGINX_ENVSUBST_FILTER=^(BOT_API_UPSTREAM|TRUSTED_PROXY_RULES)$
COPY nginx.conf /etc/nginx/templates/default.conf.template

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]

