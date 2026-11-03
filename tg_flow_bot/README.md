# TG Flow - Bot Microservice

A FastAPI service with integrated Django authentication for the TG Flow project. Each chat subscription can keep the focused mention inbox or expose a complete message feed.

It also provides a secured MCP Streamable HTTP server and the `tgflow` CLI. See [MCP_AND_CLI.md](../MCP_AND_CLI.md) for architecture, OAuth/PKCE, deployment, and usage.

## Self-hosting

For a self-hosted instance, the public MCP address is `https://<your-domain>/mcp`. The bot, embedded auth, frontend and PostgreSQL must be deployed with an HTTPS reverse proxy, a persistent database and the correct trusted-proxy settings. The sibling workspace's [installation guide and agent prompt](../README.md#install-with-a-coding-agent) describe the current early-access workflow and its limitations.

The production environment template is [envs/prod/env.op.example](envs/prod/env.op.example). It is an example, not a deployment configuration: replace its placeholders and keep secrets outside Git. The current Makefile publishes port 8081 on all interfaces and bind-mounts source code; it does not provide a complete hardened VPS deployment. Do not expose it directly to the public internet.

## Architecture

**Key Concept:** Adding the bot to a group automatically subscribes the human who added it to all new messages. Other users can optionally subscribe for themselves.

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

- Add the bot to a group or supergroup: the Telegram user who adds it is registered automatically and receives a `full` subscription, without `/start` or `/subscribe`. No other group members are subscribed automatically.
- In the web Chats page, choose All messages, Mentions + context, or turn saving off (`disabled`). Turning saving off preserves the subscription and previously stored messages/mentions; other subscribers can continue capturing the same group.
- Disabled subscriptions retain earlier mention text. Context is bounded by the disable time, including the effective capture/update time of shared messages. A context row edited after disabling is omitted for the disabled subscriber because the shared store does not retain prior row versions.
- Duplicate membership events and removing/re-adding the bot preserve existing choices, including disabled. Promotions to administrator do not subscribe anyone.
- For a group already containing the bot without a subscription, remove and re-add it, or use the optional `/subscribe all` recovery command in the group. Historical owners cannot safely be inferred. Telegram must deliver the membership event, and registration must succeed.
- The bot still needs Telegram permission to receive group messages (administrator access or privacy mode disabled). It cannot import earlier history or Telegram's personal read markers.
- `/subscribe mentions` keeps the existing mention inbox with five messages before and after each mention. Plain `/subscribe` uses this mode.
- `/subscribe all` starts a complete feed from the moment the mode is enabled.
- `/unsubscribe` turns saving off for your subscription without deleting history. `/subscribe` and `/mode` resolve your identity through auth after restarts; no earlier `/start` is required.
- `/mode` shows the current mode; `/mode mentions` and `/mode all` switch it.

The web API exposes `GET /api/chats/`, `PATCH /api/chats/{chat_id}/mode`, and `GET /api/chats/{chat_id}/messages`. The messages endpoint is available only to the owner of a subscription currently in `full` mode.

`GET /api/chats/{chat_id}/messages` returns messages oldest-first within the selected page. `limit` defaults to 100 and accepts 1–200; `before_message_id` is an optional exclusive cursor for older pages. For groups, only records saved after the current `full` interval was enabled are returned. Owner-isolated Business conversations instead retain captured history from the original subscription across mode changes. Text and media captions are stored, but attachment binaries are not downloaded.

### Telegram Business private conversations

Enable Secretary/Business Mode for the bot in BotFather, then connect it from the owner's Telegram account settings and select private conversations. This is separate from group Privacy Mode and website/OAuth login. Follow [Telegram's setup guide](https://core.telegram.org/bots/features#business-bots); no extra account password, user-session key, or token needs to be supplied to TG Flow.

The bot handles connection lifecycle, newly delivered incoming/outgoing private text and captions, edits, and deletions. A private conversation is created for its connected account's resolved auth owner with a `full` subscription on first capture. Only `full` and `disabled` are supported for private conversations. Existing disabled choices survive repeated events and reconnection. Edits affect existing captured messages only while capture and the connection are active; they cannot create an archive or restore deleted rows. Delivered deletion events for the current connection remove matching retained messages even when capture is disabled or the connection is inactive. Old history and attachment binaries are not imported; Business commands are captured as messages rather than executed as ordinary bot commands. Ingestion remains read-only; explicit account replies use the separate workflow below. Telegram read-receipt operations are not performed.

Business conversation IDs are internal app IDs; the actual Telegram peer is stored separately. Conversations and messages are scoped by connection owner, so a shared correspondent and Telegram message ID cannot merge different owners' histories. REST and MCP subscription results include `source` (`group` or `business`) and `connection_active`. Business IDs must not be used to construct Telegram links or passed directly to Telegram send/photo methods.

Disconnecting in Telegram stops new collection immediately when its update is received. The owner retains access to previously stored full-mode messages and can advance the TG Flow summary checkpoint. Enabling full capture requires an active connection. A Business subscription switched to `disabled` hides its feed; switching back to `full` restores the already captured archive and read cursor, bounded by the original `subscribed_at`. No messages from the disabled interval are imported. Snapshot generation checks still use `capture_mode_changed_at`.

Unknown or obsolete connection IDs do not ingest messages; records persist across restarts, but an unknown connection requires a Telegram connection update rather than an automatic fetch. If the initial event was missed, try disconnecting and reconnecting in Telegram. Ordering watermarks are strict for messages, deletions and same-ID connection events. A lower-ID lifecycle event is accepted only for a new, non-retired connection ID verified with Telegram's `getBusinessConnection` against the exact connection, owner and enabled state. Verification failure rejects the event. A genuine Telegram update-ID reset after prolonged bot-wide inactivity can therefore require a new connection ID or operator recovery; reconnecting is not guaranteed to rotate the ID. Never clear the watermark automatically or start a second polling process with the same token.

The dependency is pinned to `python-telegram-bot==22.8` for current rights-based Business connection payload compatibility; older 21.7 payload parsing is insufficient.

Apply additive Aerich [migration 5](migrations/models/5_20261103120000_add_business_connections.py) before starting this code, after inspecting the migration plan and taking a database backup. This feature and migration were deployed to the configured VPS on 3 November 2026; a real Business connection, private ingestion and authenticated MCP reads were verified. See the [VPS runbook](../docs/vps-deployment.md#telegram-business--deployment-and-setup).

### Explicit replies from the connected account

TG Flow provides `POST /api/chats/{chat_id}/messages/{message_id}/reply` with `{text, request_id}` and the MCP tool `reply_to_chat_message(chat_id, message_id, text, request_id, confirmed=False)`. Both use one send service and require write scope. MCP additionally rejects false confirmation before reservation; clients must obtain approval of the exact recipient/text. The UI uses an explicit **Send as me** action. Internal app chat IDs and captured target IDs are resolved to the stored Business peer/connection; arbitrary destinations, groups, cross-owner subscriptions and cross-chat targets are rejected.

New sends require active full capture, a visible captured target and a current Telegram connection with matching owner and `can_reply`. Telegram permits replies only in eligible private chats with incoming activity within 24 hours. Fresh rights checks use bounded timeouts; Telegram remains authoritative for chat eligibility. Plain text is trimmed to 1–4096 characters. The result includes `status: sent|failed|unknown`, request UUID, nullable sent message ID, `reply_attached`, and safe error fields. Telegram may send a standalone message if its reply target disappeared, so attachment is reported from the actual result.

Apply additive [migration 6](migrations/models/6_20261103180000_add_business_reply_attempts.py) before running reply code. It adds a durable per-owner request UUID ledger, reserved and committed before any send. A hash binds normalized text, app chat and target; the ledger does not store an extra plaintext request body. Identical repeated keys return their existing result without sending; conflicting payloads return 409. Reserved/crashed attempts remain non-resendable and surface `unknown` / `delivery_pending`. A timeout after sending may mean delivery succeeded, so it reports unknown and never retries automatically. Definitive provider rejection reports failed; a separately approved attempt needs a new UUID. Do not erase or downgrade this ledger to make a request resendable.

`get_chat_reply_status(chat_id, request_id)` and `GET /api/chats/{chat_id}/reply-attempts/{request_id}` are read-only owner-scoped lookups requiring `mentions:read`. They create no reservation and never send or retry a message. Existing results can be retrieved after disconnect/disable or loss of target visibility without enabling a new send. A missing result is not proof of non-delivery while an original request may still be in flight. Successful outgoing messages enter the existing chat store and polling echoes deduplicate by chat/message ID. Replying does not mark any local or Telegram messages read or archive mentions. Replies were deployed on 3 November 2026; real outgoing-message verification remains pending; see the [reply runbook](../docs/vps-deployment.md#private-business-replies--deployment-and-setup).

### New messages since the last summary

Each subscription stores a durable `read_through_message_id` and nullable `last_read_at` independently of mention archives and Telegram read receipts. Existing accessible full-mode history starts unread; switching modes or disabling capture preserves the cursor. Editing an already acknowledged Telegram message ID does not make it unread again.

`GET /api/chats/{chat_id}/unread` returns oldest-first messages, the current read cursor, `snapshot_through_message_id`, mode generation, `has_more`, `next_after_message_id`, and `unread_count`. Limit is 1–200. Continue with the same `through_message_id` and `capture_mode_changed_at` plus `after_message_id=next_after_message_id`. Messages arriving beyond the frozen snapshot remain unread. Reading the feed or unread endpoint never acknowledges anything.

`POST /api/chats/{chat_id}/read` takes `{through_message_id, capture_mode_changed_at}` and requires write scope, current full mode, and a visible captured target. It advances the cursor atomically and monotonically. Stale mode generations fail; smaller or repeated markers never move the cursor backward. It returns the updated subscription. Listing chats includes the cursor, last acknowledgement time, and available unread count (zero outside full mode).

For a requested GPT summary use `list_unread_chat_messages`, read all pages of its frozen snapshot, produce the summary successfully, then call `mark_chat_read` through that snapshot boundary. For an explicitly partial summary acknowledge only its last processed message. Failed summaries do not mark. No extra archive/reply confirmation is required for the user's requested summary workflow; the existing confirmation requirement for archive/reply stays in place. The website provides per-chat unread counts and an explicit mark-as-read action using an observed snapshot.

Back up and inspect migration state before deployment. Apply additive migration 4 (read cursor columns) together with any pending capture-mode migrations; do not reset existing databases:


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
