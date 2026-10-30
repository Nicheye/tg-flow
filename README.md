# TG Flow

Self-hosted Telegram inbox and MCP server. Run TG Flow on your own VPS, add your bot to a Telegram group, and connect a compatible MCP client to your instance:

```text
https://flow.example.com/mcp
```

The domain is yours. The MCP endpoint uses OAuth: users sign in with Telegram and approve the requested permissions. It is not a public, unauthenticated feed.

TG Flow can keep mentions with surrounding context, or collect new messages from a chat when its owner explicitly enables full-feed mode. You can browse the data in the web interface and use supported MCP tools to read, archive, or reply to mentions. Message text and media captions may be stored; attachment binaries are not downloaded.

## Current status

This repository contains `tg_flow_bot`, `tg_flow_frontend`, and `tg_flow_storage` in one versioned tree. The bot contains the FastAPI API, Telegram bot, embedded Django authentication, OAuth server, and remote MCP endpoint. The frontend is a React app; storage runs PostgreSQL. A separate `tg_flow_auth` deployment is not needed when using the integrated auth mode.

**Self-hosting is an early-access workflow, not yet a one-command installer.** There is no production Compose stack or complete automated HTTPS setup in this repository, and a clean VPS deployment and end-to-end ChatGPT/Claude connections have not been verified. Validate your installation before relying on it.

## What you need

- A Linux VPS you control, with Docker, Docker Compose, Git, and a persistent volume for PostgreSQL.
- A public domain pointing to the VPS and a trusted TLS certificate. The MCP URL must be reachable over HTTPS by the client you use.
- A Telegram bot token and username from [@BotFather](https://t.me/BotFather). Configure the public login domain in BotFather; the OAuth consent page uses the Telegram login widget. See [Telegram's widget setup](https://core.telegram.org/widgets/login/).
- An MCP client that can connect to a remote Streamable HTTP server and complete OAuth authorization. Availability, plan and workspace permissions vary. See the current [ChatGPT MCP documentation](https://help.openai.com/en/articles/12584461-developer-mode-and-full-mcp-connectors-in-chatgpt) and [Claude custom connector guide](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp).
- A checkout of this repository, which contains the bot, frontend, storage, documentation, and local development script together. The source currently has no public monorepo URL; add one when publishing it.

## Install with a coding agent

The prompt below is intended for an agent that can inspect the source and access your VPS. Give it the source directories and an SSH connection using your normal secure workflow. Replace the domain, or let the agent ask for it. **Do not paste bot tokens, passwords, private keys, or OAuth credentials into the prompt or chat.** Enter them directly on the server through a secure mechanism supported by your agent.

<details>
<summary>Copy the deployment prompt</summary>

```text
Help me deploy TG Flow on my VPS. I want a private self-hosted Telegram
inbox and a remote MCP server accessible at https://<my-domain>/mcp.
The workspace contains tg_flow_bot, tg_flow_frontend, and tg_flow_storage.
Read their current source, README files, env examples, and MCP_AND_CLI.md.
Use the checked-out repository revision.

First inspect the VPS and explain what is already running: OS, Docker/Compose,
ports, DNS, reverse proxy, existing TG Flow containers, volumes and backups.
Do not print secret values. Ask me only for information or actions you cannot
derive or perform, such as the public domain, SSH access, BotFather setup,
or a secure way for me to enter the bot token. Never ask me to paste tokens,
passwords or private keys into chat or command history.

Use the integrated auth mode in tg_flow_bot and a persistent PostgreSQL
database. Configure the same database credentials for PostgreSQL, the bot,
and AUTH_DB_* when using one shared database. Set DEBUG=False and use unique,
strong server-generated secrets. Set the public OAUTH_ISSUER and the exact
MCP_RESOURCE_URI consistently, configure the Telegram bot username and token,
allowed hosts/origins, CSRF settings and the frontend build arguments.
Preserve existing credentials, user IDs, Django signing keys, OAuth issuer,
database volumes and migrations when this is an existing installation.

Design and configure HTTPS and routing for the actual topology. Forward
/api/, /oauth/, /.well-known/ and /mcp to the correct services; /mcp uses
Streamable HTTP. Trust forwarded HTTPS headers only from the actual immediate
reverse-proxy peer, not arbitrary clients or a shared network. Keep PostgreSQL,
the bot's port 8081 and the frontend's internal port inaccessible from the
public internet; only expose intended HTTP/HTTPS ingress. The current Makefiles
publish ports on all interfaces, so do not expose them unchanged on a public
VPS. Check firewall rules, Docker port publishing and existing services before
changing them; do not lock me out of SSH. Preserve other applications.

Build the images, start the database, apply Django auth and Aerich bot
migrations in the correct order, start the services, and verify persistence,
restart behavior and logs without disclosing secrets. Before changing an
existing database or deployment, inspect its migration state and establish
a backup and rollback plan. Never delete volumes, reset databases, revoke
credentials, change unrelated services, or deploy over an existing installation
without my explicit approval. Do not run the local development start.sh as a
production installer.

Verify HTTPS externally, /.well-known/oauth-protected-resource/mcp,
/.well-known/oauth-authorization-server and that /mcp rejects unauthenticated
requests with the expected OAuth challenge. Check that discovery advertises
the exact public issuer and MCP URL. Help me finish BotFather domain setup,
Telegram login, OAuth consent and a real read-only MCP tool call from my
chosen client. If a client or provider setting requires me, tell me exactly
what to do; do not claim success based only on a health check. Configure
registration/token endpoint rate limiting at ingress where supported.

Finish with the verified public MCP URL, where to add it in my client, the
commands to inspect and update the deployment, backup/restore guidance, and
any limitations or steps that could not be verified. Never print secrets.
```

</details>

The prompt is a guide for an agent, not a verified turnkey deployment. The agent may need to prepare deployment configuration for your VPS and ask you for decisions before changing existing services.

## Configure and verify

Use the examples as a starting point, not as ready-to-run secrets:

- [Bot production environment](tg_flow_bot/envs/prod/env.op.example): public URLs, Telegram bot, signing keys, proxy trust, and both database connections.
- [Storage production environment](tg_flow_storage/envs/prod/env.op.example): PostgreSQL database, user, password, host port, and Docker network.
- [Frontend environment example](tg_flow_frontend/.env.example): Telegram bot username and optional public API overrides. `VITE_*` values are baked into the frontend at build time.

For a new shared database, the storage `DB_NAME`, `DB_USER`, and `DB_PASSWORD` must match both the bot's `DB_*` and `AUTH_DB_*` values. Preserve an existing auth database and signing key rather than silently switching to a new one. See the bot's [migration and proxy instructions](tg_flow_bot/README.md#existing-auth-data-and-configuration).

After deployment, inspect the public discovery documents:

```bash
curl -fsS https://flow.example.com/.well-known/oauth-protected-resource/mcp
curl -fsS https://flow.example.com/.well-known/oauth-authorization-server
```

Replace `flow.example.com` with your domain. The first document must identify your exact `https://…/mcp` resource and the second must identify your HTTPS OAuth issuer. A successful discovery response alone does not prove that Telegram login, consent, or MCP tools work: test those with a real client too. Details, scopes, and the CLI are in [MCP_AND_CLI.md](MCP_AND_CLI.md).

### Connect a client

In a compatible remote-MCP client, add `https://flow.example.com/mcp` as a custom connector, then complete Telegram sign-in and OAuth consent. Claude's current connector settings offer automatic client registration; TG Flow supports dynamic registration but does **not** advertise Client ID Metadata Documents. Choose automatic registration if the client supports it and its published-identity option is incompatible. Check the provider's documentation and your plan's permissions. Client compatibility has not yet been verified end to end for this checkout.

In Telegram, open your bot and send `/start`, add it to a group, then send `/subscribe` in that group. Use `/subscribe all` only if you want to retain all new messages, and `/mode` to inspect or change the capture mode. Make sure the bot has the Telegram permissions and privacy settings necessary for the messages you want it to receive.

## Local development

This workspace has a separate interactive `./start.sh` for local development. It uses dev env files, runs the Vite development server, starts containers, and applies database migrations. It is **not** a VPS installer and does not configure production TLS or firewalling. Read the script before running it against an existing database.

During first-time setup, enter the local PostgreSQL name, user, and password once. The launcher fills missing bot and embedded-auth settings from them and copies the bot username to the frontend. Existing values are preserved; if an existing auth configuration points to a different database, the launcher asks for any missing settings instead of guessing. The host PostgreSQL port can differ from the internal container port, which defaults to `5432`.

Useful development and architecture references:

- [Bot and embedded auth](tg_flow_bot/README.md)
- [Frontend](tg_flow_frontend/README.md)
- [PostgreSQL service](tg_flow_storage/docs/README.md)
- [MCP, OAuth and CLI](MCP_AND_CLI.md)

## Security and data

Your instance stores Telegram user data and messages in PostgreSQL. Keep its volume and auth secrets backed up, limit access to the host and database, use TLS and trusted proxy boundaries, and review what you enable through `/subscribe all`. OAuth tokens and bot credentials are secrets; never commit them or paste them into support requests. Back up before applying migrations, changing signing keys, or deleting any container volumes.

No license file is present yet; choose and publish a license before presenting the project as open source. Add a public remote and release process before asking new users to clone it.

# tg-flow
