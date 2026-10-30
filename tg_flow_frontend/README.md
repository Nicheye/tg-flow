# TG Flow Frontend

A web interface and Telegram Mini App for reviewing and managing mentions. The Bot API verifies the Telegram user and issues a session through `/api/auth` on the same origin.

## Stack

- React 18 + TypeScript + Vite
- Tailwind CSS, TanStack Query, and React Router
- Telegram Mini App SDK and Telegram Login Widget

## Visual design

The dashboard uses light white and gray surfaces, system fonts, and a simple layout. Primary actions and text remain legible on mobile and larger screens.

- The overview shows workspace status, active mentions, and chats.
- The inbox groups mentions by chat and provides reply, archive, and Telegram links.
- Mention context displays the messages before and after the mention.
- Capture controls let users choose `mentions` or `full` per subscription and view the full feed after enabling it.
- Common actions use brief feedback; movement is removed when `prefers-reduced-motion` is enabled.
- The interface does not claim unimplemented LLM capabilities; TG Flow is a bridge between Telegram signals and future LLM workflows.

## Development

```bash
npm install
npm run dev
npm test
npm run lint
npm run build
npm run preview
```

## Environment variables

If needed, create `.env` in the `tg_flow_frontend` directory using [.env.example](.env.example):

```dotenv
VITE_BOT_USERNAME=your_bot_username
```

In development, the Bot API defaults to `http://localhost:8081`. Production builds default to same-origin `/api/...` paths, which the frontend server must proxy to the Bot API. To use another address, set `VITE_API_URL`, for example `https://bot.example.com`. The authentication URL is derived by appending `/api/auth`; override it with `VITE_AUTH_API_URL` if needed. Explicit values apply in development and production.

Vite embeds `VITE_*` values at build time. Local `.env` files are excluded from the Docker build context; pass values if needed using `docker build --build-arg VITE_API_URL=https://bot.example.com --build-arg VITE_BOT_USERNAME=your_bot_username .`. Changing `VITE_*` only when starting a container does not change an already-built frontend.

## Routes and authentication

| Route | Purpose |
| --- | --- |
| `/` | Overview and entry point |
| `/login` | Telegram Login Widget sign-in in a browser |
| `/mentions` | Saved mentions and statistics |
| `/mentions/:mentionId` | Context, reply, and archive for a mention |
| `/chats` | Subscription modes and the full feed for chats with `full` enabled |

- The Telegram Mini App sends complete `initData`, which the Bot API checks for authenticity and freshness.
- In a browser, the Telegram Login Widget sends signed data to the same service.
- After verification, the frontend uses a short-lived access token and refreshes it with a refresh token. The mentions screen does not replace unauthenticated users with a test profile.
- Bot API requests act on behalf of the current user; the server enforces user-level data isolation.
- Switching to `full` exposes new messages saved after the switch. Switching back to `mentions` immediately closes access to the full feed.

See the [Bot service README](../tg_flow_bot/README.md) for REST operations and the access model. External AI clients should use the separate OAuth-protected MCP/CLI interface described in [MCP_AND_CLI.md](../MCP_AND_CLI.md), not browser tokens.

## Structure

```text
src/
├── App.tsx                 # Routes and protected pages
├── contexts/AuthContext.tsx # Session state and Telegram sign-in
├── hooks/useTelegram.ts     # Telegram WebApp integration
├── lib/api.ts               # Bot API client and session refresh
├── lib/auth.ts              # Bot API authentication client
└── pages/                   # Overview, login, mentions, context, and chat modes
```

## Docker

```bash
docker build -t tg-flow-web .
docker run --add-host=host.docker.internal:host-gateway -p 3000:80 tg-flow-web
```

By default, nginx proxies `/api/`, `/oauth`, `/oauth/`, `/.well-known/`, and the exact path `/mcp` to `http://host.docker.internal:8081`. MCP uses HTTP/1.1 without response buffering for Streamable HTTP. The example above reaches the Bot API on the host; if the bot is on another network or container, specify an address reachable from the container, for example `-e BOT_API_UPSTREAM=http://bot:8081`. Use an origin without a trailing `/` or path.

Nginx forwards the original `Host`, including its port (for example, `localhost:3000`); for HTTP/1.0 without `Host`, it uses the nginx server name. Restrict allowed public hosts in Bot/Auth: `MCP_ALLOWED_HOSTS` includes the port, while Django's `ALLOWED_HOSTS` checks the hostname. Nginx syntax validation is not a trusted-domain allowlist.

By default, nginx does not trust incoming `X-Forwarded-Proto` and forwards its own connection scheme. If HTTPS terminates at another reverse proxy, specify the addresses of its direct connections to nginx using `TRUSTED_PROXY_RULES`, for example `-e 'TRUSTED_PROXY_RULES=10.20.0.5/32 1; 2001:db8::5/128 1;'`. Each entry is an IP address or CIDR in nginx geo format followed by `1;`; the default list is empty. Use only trusted proxy addresses as seen by nginx after network translation, and restrict access to the container. The trusted proxy must overwrite, not append to, the client's `X-Forwarded-Proto`. Only a single `http` or `https` value is accepted from such sources; missing or invalid values fall back to the nginx connection scheme. Do not trust shared networks or all addresses, or clients could spoof the scheme. Bot/Auth must also trust forwarded headers only from this nginx; otherwise HTTPS redirects can loop or the scheme can be spoofed through direct service access.

The Vite development server calls the local Bot API directly, so no development proxy is required. Run `npm run test:proxy` to test routing, streaming, and trusted-scheme handling with a test upstream (requires Docker).
