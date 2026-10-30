# TG Flow - Bot Microservice

A FastAPI service with integrated Django authentication for the TG Flow project. Each chat subscription can keep the focused mention inbox or expose a complete message feed.

It also provides a secured MCP Streamable HTTP server and the `tgflow` CLI. See [MCP_AND_CLI.md](../MCP_AND_CLI.md) for architecture, OAuth/PKCE, deployment, and usage.

## Self-hosting

For a self-hosted instance, the public MCP address is `https://<your-domain>/mcp`. The bot, embedded auth, frontend and PostgreSQL must be deployed with an HTTPS reverse proxy, a persistent database and the correct trusted-proxy settings. The [installation guide and agent prompt](../README.md#install-with-a-coding-agent) describe the current early-access workflow and its limitations.

The production environment template is [envs/prod/env.op.example](envs/prod/env.op.example). It is an example, not a deployment configuration: replace its placeholders and keep secrets outside Git. The current Makefile publishes port 8081 on all interfaces and bind-mounts source code; it does not provide a complete hardened VPS deployment. Do not expose it directly to the public internet.

## Architecture

**Key Concept:** One bot per chat, but multiple users can subscribe to it.

The bot can be added to a chat only once (Telegram limitation), but multiple users can register and independently choose mention or full-feed access for that chat.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed architecture explanation.

## Quick Start

### Using Docker

1. Create and configure an environment file from
   `envs/dev/env.op.example`, preserving an existing `envs/dev/env.op`.
   Set the bot credentials and explicitly select the auth database with
   `AUTH_DB_*`. For PostgreSQL, the database must already exist, be running,
   and be reachable by the migration container. For OAuth Telegram login, set
   `TELEGRAM_BOT_USERNAME`. See [Existing auth data and configuration](#existing-auth-data-and-configuration)
   before using an existing database.
2. Build the image and create the Docker network named by `NETWORK` in the
   environment file. The example uses `flow_net`; use your configured name
   in both the network command and the migration command below.
3. Run the auth migrations **before** starting the service. The commands below
   use the development env file and default network:

   ```bash
   make build
   docker network inspect flow_net >/dev/null 2>&1 || docker network create flow_net
   ENV_FILE=envs/dev/env.op make auth-migrate
   ENV_FILE=envs/dev/env.op make up
   make migrate
   ```

   Run these commands from the bot repository root. The last command applies
   the separate Aerich bot migrations in the running container. For
   production, substitute the configured production env file and network.

`make auth-migrate` runs a temporary container and requires a built
`tg-flow-bot` image, an existing `ENV_FILE`, the configured Docker network,
and a reachable auth database. It mounts the repository at `/app`; an SQLite
auth database must be accessible at its configured container path and
persisted by an appropriate mount. The target does not create the network.

## Docker Commands

### Using Makefile (Recommended)

**Basic commands:**
- Build image: `make build` (ENV_FILE not required)
- Start container: `ENV_FILE=envs/dev/env.op make up` (ENV_FILE **required**)
- Stop container: `make down` (ENV_FILE not required)
- Restart container: `ENV_FILE=envs/dev/env.op make restart` (ENV_FILE **required**)
- View logs: `make logs` (ENV_FILE not required)
- Check status: `make ps` (ENV_FILE not required)
- Check health: `make health` (ENV_FILE not required)
- Clean: `make clean` (ENV_FILE not required)

**Development commands:**
- Access shell: `make shell` (ENV_FILE not required)
- Run tests: `make test` (ENV_FILE not required)
- Format code: `make format` (ENV_FILE not required)

**Database migrations:**
- Apply migrations: `make migrate`
- Apply Django auth migrations: `ENV_FILE=envs/dev/env.op make auth-migrate`
- Inspect Django migration history: `ENV_FILE=envs/dev/env.op make auth-migration-status`
- Create migration: `MSG='create tables' make makemigrations`
- Rollback one migration: `make migrate-down`
- Show migration history: `make migrate-history`

**Note:** `ENV_FILE` is required for `up`, `restart`, `auth-migrate`, and
`auth-migration-status`. Other commands operate on the image or existing
container and do not require `ENV_FILE`.

## API Endpoints

The service runs on port **8081**, including authentication and OAuth.

- `GET http://localhost:8081/` - Root endpoint
- `GET http://localhost:8081/health` - Health check endpoint
- `GET http://localhost:8081/docs` - Swagger UI documentation
- `GET http://localhost:8081/redoc` - ReDoc documentation
- `POST http://localhost:8081/mcp` - OAuth-protected MCP Streamable HTTP endpoint
- `GET http://localhost:8081/.well-known/oauth-protected-resource/mcp` - MCP OAuth discovery metadata
- `GET http://localhost:8081/.well-known/oauth-authorization-server` - OAuth authorization-server metadata
- `/api/auth/` and `/oauth/` - Django authentication and OAuth endpoints

### Existing auth data and configuration

Keep the existing Django signing secret in `DJANGO_SECRET_KEY` (or `SECRET_KEY`
if no separate bot secret is needed), Telegram token, OAuth issuer and MCP
introspection credentials when transferring an existing deployment; changing
the issuer may affect existing OAuth clients. Configure the reverse proxy to
route the issuer's auth, OAuth and discovery paths to this server.

### HTTPS reverse proxy trust

Terminate TLS at a reverse proxy and connect it to the bot over a private Docker
network. Give the proxy a stable private address and set `TRUSTED_PROXY_NETWORKS`
to that address (for example `172.30.0.2/32`), or to the narrowest CIDR containing
only trusted proxy peers. The default is empty: forwarding headers are ignored.
Do not trust an entire shared Docker subnet, a public network, or a NAT gateway
that can represent untrusted clients. Configure the proxy to remove any incoming
`X-Forwarded-Proto` and set exactly one value, `https` or `http`, based on the
actual external connection. Django checks the immediate connecting IP before
using this header; missing, invalid, or untrusted peers cannot assert HTTPS.

The Docker image starts Uvicorn with `--no-proxy-headers` so the peer address
and scheme cannot be rewritten before that check. Use the same option in any
custom Uvicorn command, and disable equivalent proxy-header processing in other
ASGI/WSGI servers. Protect the backend port with network/firewall rules; the
Makefile publishes 8081 on all host interfaces, while other containers on the
Docker network can reach it directly. If a host proxy or Docker NAT obscures the
real peer, do not trust the shared source address: use an isolated network or
another topology with a verifiable proxy peer. HTTPS directly terminated at the
application server does not require a trusted proxy setting. Local HTTP development
continues to work with the default empty list.

Django requires an explicit auth database choice. Set `AUTH_DB_ENGINE`,
`AUTH_DB_NAME`, `AUTH_DB_USER`, `AUTH_DB_PASSWORD`, `AUTH_DB_HOST` and
`AUTH_DB_PORT` to the existing auth database, even if it shares the bot DB.
For SQLite set `AUTH_DB_ENGINE=sqlite3` and `AUTH_DB_NAME` to the existing auth database
path to retain SQLite data. Ensure that file is persisted and mounted into the
container. Preserve the original `users` tables and Django migration history.
Back up the existing database and inspect the migration history with
`ENV_FILE=envs/dev/env.op make auth-migration-status` before applying
migrations. Use the appropriate environment file and network for your deployment.
Build the image and ensure
the configured Docker network exists first. Aerich's `make migrate` is separate. Neither
migration runs automatically on startup. Startup checks connectivity and
refuses to start if Django migrations are missing. For a new installation,
explicitly select its database and run Django migrations before starting.

Internal auth requests use local ASGI by default. Set `AUTH_LOCAL_ASGI=False`
and explicitly configure both `AUTH_API_URL` and `OAUTH_INTROSPECTION_URL`
to use an external auth service. Remote mode does not start local Django or
check its migrations; the external service must handle auth, OAuth and its
discovery routes, with the proxy routing those paths to it. Django's `ALLOWED_HOSTS` must include the host
in `OAUTH_ISSUER`, including for local internal requests.
If either legacy URL is configured, `AUTH_LOCAL_ASGI` must be set explicitly
to choose local or remote calls.
`AUTH_ALLOWED_HOSTS` can add the old auth service's hosts to `ALLOWED_HOSTS`.
Set `TELEGRAM_BOT_USERNAME` to the bot's username without `@` for OAuth
Telegram login; `BOT_TOKEN` is used for Telegram signature checks.

### Mention API authorization

The browser API is protected by a user session from the Auth service. The service enforces ownership for every mention, context, archive, restore, reply, and chat-photo operation; callers cannot choose another user through a request parameter.

The primary mention endpoints are `GET /api/mentions/`, `GET /api/mentions/stats/`, `GET /api/mentions/{mention_id}/context`, `PATCH /api/mentions/{mention_id}`, and `POST /api/mentions/{mention_id}/reply`. MCP access uses the same service capabilities but requires OAuth scopes: `mentions:read` for read operations and `mentions:write` for archive, restore, and reply. Consult the Swagger UI for request schemas and [MCP_AND_CLI.md](../MCP_AND_CLI.md) for the external-client contract.

### Capture modes

- `/subscribe mentions` keeps the existing mention inbox with five messages before and after each mention. Plain `/subscribe` uses this mode.
- `/subscribe all` starts a complete feed from the moment the mode is enabled.
- `/mode` shows the current mode; `/mode mentions` and `/mode all` switch it.

The web API exposes `GET /api/chats/`, `PATCH /api/chats/{chat_id}/mode`, and `GET /api/chats/{chat_id}/messages`. The messages endpoint is available only to the owner of a subscription currently in `full` mode.

`GET /api/chats/{chat_id}/messages` returns messages oldest-first within the selected page. `limit` defaults to 100 and accepts 1–200; `before_message_id` is an optional exclusive cursor for older pages. Only records saved after `full` was enabled are returned. Text and media captions are stored, but attachment binaries are not downloaded.

Apply the capture-mode migration before deploying this version:

```bash
make migrate
```

The remote MCP server exposes the same read boundary through `list_chat_subscriptions` and `list_chat_messages`; see [MCP_AND_CLI.md](../MCP_AND_CLI.md).

## Technology Stack

- FastAPI
- Python 3.13
- Tortoise ORM + Aerich
- PostgreSQL
- Pydantic
- python-telegram-bot
- MCP Python SDK
- Typer CLI
- Docker
