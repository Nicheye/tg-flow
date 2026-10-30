# TG Flow project structure

- `tg_flow_bot` — FastAPI REST API, Telegram bot, remote MCP server, local stdio MCP bridge, and `tgflow` CLI on port 8081; by default it also hosts the integrated Django authentication and OAuth routes. Remote auth mode uses an external auth service instead.
- `tg_flow_storage` — PostgreSQL Docker Compose service on the shared `flow_net` network.
- `tg_flow_frontend` — React/Vite Telegram Mini App and web frontend.
- `MCP_AND_CLI.md` — MCP architecture, OAuth/PKCE security model, configuration, deployment, and CLI guide.
- `start.sh` — interactive local development launcher, not a production installer.

Production cutover and migration have not been verified. Preserve the canonical public OAuth issuer, legacy proxy routes, auth database, and existing authentication keys during the transition; see `MCP_AND_CLI.md`.
