# TG Flow

Self-hosted Telegram inbox and MCP server. Run TG Flow on your own VPS, add your bot to a Telegram group, and connect a compatible MCP client to your instance:

```text
https://flow.example.com/mcp
```

The domain is yours. The MCP endpoint uses OAuth: users sign in with Telegram and approve the requested permissions. It is not a public, unauthenticated feed.

TG Flow can keep mentions with surrounding context or collect all new messages from a group. Adding the bot creates an all-messages subscription for the person who added it; other group members are not subscribed automatically. The owner can switch to mentions only or disable capture from Chats in the web interface. You can browse the data in the web interface and use supported MCP tools to read, archive, or reply to mentions. Message text and media captions may be stored; attachment binaries are not downloaded.

Telegram Business is an additional source for selected private conversations. The connected account's owner can browse captured messages and summarize new messages through the same web and MCP unread workflow. Business support was deployed to the configured VPS on 3 November 2026; a real account connection, private message ingestion and authenticated MCP reading were verified. A real private GPT-summary/checkpoint workflow remains to be verified. See the [VPS verification record](docs/vps-deployment.md#business-release--3-november-2026).

## Current status

This repository versions `tg_flow_bot`, `tg_flow_frontend`, and `tg_flow_storage` together in one tree. The bot contains the FastAPI API, Telegram bot, embedded Django authentication, OAuth server, and remote MCP endpoint. The frontend is a React app; storage runs PostgreSQL. A separate `tg_flow_auth` deployment is not needed when using the integrated auth mode.

**Self-hosting is an early-access workflow, not yet a one-command installer.** The checked-out code includes a VPS Compose stack, nginx configuration, backup/TLS helpers, and a deployment runbook. The configured VPS has verified HTTPS, OAuth/MCP access and private message ingestion; real outgoing reply acceptance remains pending. See [deployment operations and verification](docs/vps-deployment.md) and use the checked-out revision when installing.

## What you need

- A Linux VPS you control, with Docker, Docker Compose, Git, and a persistent volume for PostgreSQL.
- A public domain pointing to the VPS and a trusted TLS certificate. The MCP URL must be reachable over HTTPS by the client you use.
- A Telegram bot token and username from [@BotFather](https://t.me/BotFather). Configure the public login domain in BotFather; the OAuth consent page uses the Telegram login widget. See [Telegram's widget setup](https://core.telegram.org/widgets/login/).
- An MCP client that can connect to a remote Streamable HTTP server and complete OAuth authorization. Availability, plan and workspace permissions vary. See the current [ChatGPT MCP documentation](https://help.openai.com/en/articles/12584461-developer-mode-and-full-mcp-connectors-in-chatgpt) and [Claude custom connector guide](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp).
- A checkout of [Nicheye/tg-flow](https://github.com/Nicheye/tg-flow), containing all three services, documentation and deployment helpers. `start.sh` is a local development launcher; use the VPS runbook for production.

## Install with a coding agent

The prompt below is intended for an agent that can inspect the source and access your VPS. Give it the source directories and an SSH connection using your normal secure workflow. Replace the domain, or let the agent ask for it. **Do not paste bot tokens, passwords, private keys, or OAuth credentials into the prompt or chat.** Enter them directly on the server through a secure mechanism supported by your agent.

<details>
<summary>Copy the deployment prompt</summary>

```text
Help me deploy TG Flow on my VPS. I want a private self-hosted Telegram
inbox and a remote MCP server accessible at https://<my-domain>/mcp.
Use this checked-out TG Flow monorepo, containing tg_flow_bot,
tg_flow_frontend, and tg_flow_storage. Read their current source, README files,
env examples, MCP_AND_CLI.md, docs/vps-deployment.md, and deployment/vps/.
Use the exact checked-out revision and pinned dependencies; do not substitute
remote default branches or older runtime images. Adapt deployment templates
to my actual host/domain. The runbook's recorded VPS is an example installation,
not permission to connect to it or copy its credentials.

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
production installer. Use a maintenance container for migrations rather than
starting a second polling bot. Verify a restore into an isolated database and
rehearse pending migrations there before changing the existing database.
Preserve Business account ownership, captured private history, read checkpoints
and all business_reply_attempts records. Never downgrade or erase the reply
ledger, expire uncertain attempts, or automatically resend them after recovery.

Include automatic group subscriptions and Telegram Business private chats.
Help me enable Secretary/Business Mode in BotFather and connect the bot through
Telegram Settings > Chat Automation, selecting the private conversations it may
access. Website login alone does not connect the Telegram account. Verify the
connection and newly delivered messages without printing private message text.
Check owner isolation and the UI's active/disconnected and full/disabled states.
Do not promise old-history import or automatic Telegram read-receipt syncing.

Verify HTTPS externally, /.well-known/oauth-protected-resource/mcp,
/.well-known/oauth-authorization-server and that /mcp rejects unauthenticated
requests with the expected OAuth challenge. Check that discovery advertises
the exact public issuer and MCP URL. Help me finish BotFather domain setup,
Telegram login, OAuth consent and a real read-only MCP tool call from my
chosen client. If a client or provider setting requires me, tell me exactly
what to do; do not claim success based only on a health check. Configure
registration/token endpoint rate limiting at ingress where supported.
Refresh the client's tool catalogue and check that the current chat, unread,
reply and reply-status tools are registered with their documented scopes.

For requested GPT summaries, read every page of a fixed unread snapshot, produce
the summary successfully, then mark only the processed boundary read. Reading
alone and failed summaries must not advance the checkpoint. Verify Mark as read
uses the same per-owner checkpoint in the UI and MCP; do not acknowledge real
messages merely to perform a deployment health check.

Check the private Reply / Send as me UI, write-scope enforcement and the MCP
reply_to_chat_message confirmation gate using mocks or non-sending probes.
Sending requires a current owner-matched Business connection, can_reply rights,
and Telegram's recent-incoming-message eligibility. Never send a real test
message without my explicit approval of the recipient and exact text.
Use one UUID per approved attempt; repeated keys must never cause another send.
Check delivery only through the read-only get_chat_reply_status tool or GET
endpoint. A timeout or missing result does not authorize a new attempt: check
Telegram and reconcile before a separately approved new send. Explain any
unknown delivery or reply_attached=false result without automatically retrying.
Preserve attempt metadata across browser reloads and report storage/recovery
limitations honestly. Distinguish registered tools and passing tests from a
real outgoing-message delivery that has actually been verified.

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

Add your bot to a group: TG Flow automatically subscribes the person who added it and saves all new messages it receives. No `/start` or `/subscribe` is required. In the web interface, open **Chats** to choose mentions only, disable capture, or resume all-message capture. Disabling preserves the subscription and previously saved data; adding the bot again does not re-enable a disabled subscription. Existing subscriptions retain their current mode.

For a group where the bot was already present before this feature, remove and re-add the bot, or use the optional `/subscribe all` recovery command. TG Flow cannot infer the original owner or fetch older group history. Make sure the bot has the Telegram permissions and privacy settings necessary to receive ordinary messages. In **Chats**, an unread count and **Mark as read** button share a per-user checkpoint with MCP. A client can summarize new messages and explicitly mark that bounded batch as read afterward; simply opening or reading a feed does not mark anything read. This is a TG Flow checkpoint, independent of Telegram read receipts. See [the unread workflow](MCP_AND_CLI.md#unread-messages-and-summary-checkpoints).

### Connect private conversations with Telegram Business

1. Enable **Secretary Mode / Business Mode** for your existing bot in [@BotFather](https://t.me/BotFather). Telegram's current terminology may vary between clients; this enables account connections, separate from group Privacy Mode and the login domain.
2. In your Telegram account settings, open the business/chat-automation bot connection settings, connect your TG Flow bot, and choose the private conversations it may access. Connecting authorizes collection of the selected conversations; website login alone does not connect them. See [Telegram's Business Bots setup](https://core.telegram.org/bots/features#business-bots).
3. Exchange a new message in a selected conversation, then refresh **Chats** on your TG Flow website. The private conversation appears for the connected account's owner. Use **All messages**, **Disable subscription**, and **Mark as read** there; private conversations do not offer mention-only capture.
4. In your MCP client, use `list_chat_subscriptions`, `list_unread_chat_messages`, and `mark_chat_read` with the returned app `chat_id`, as for groups. The checkpoint stays local to TG Flow and never marks the Telegram conversation read.

The bot stores new incoming and outgoing text or captions delivered through the connection, including supported edits and deletions. It does not import old conversation history or download attachment binaries. Connections and private histories are isolated by owner, even if two owners chat with the same person. Business app chat IDs identify stored conversations, not raw Telegram peer IDs; they are not `t.me/c/…` links.

Disabling a subscription stops capture for it and hides its full feed until it is re-enabled. For Business conversations, re-enabling retains the previously captured archive and summary checkpoint; messages sent while disabled are not imported. Disconnecting the bot in Telegram stops new capture for that account; the owner retains access to already captured full-mode history and its local unread checkpoint. Re-enabling capture requires an active connection. Reconnecting does not silently re-enable subscriptions you disabled. Events for an unknown connection are rejected until Telegram delivers its connection update; if this was missed, try disconnecting and reconnecting the bot in Telegram. Do not run a second bot process with the same token while testing.

Business updates use persistent ordering checks to reject stale events. A Telegram update-ID reset after prolonged bot inactivity can require a new connection ID or operator-assisted recovery; reconnecting is not guaranteed to rotate the ID. TG Flow does not automatically reset an existing connection's ordering watermark. The bot dependency is pinned to `python-telegram-bot==22.8` to accept Telegram's current rights-based Business connection payloads.

Business connections apply to selected private chats; group capture continues through adding the bot to each group. Ingestion itself does not send messages or synchronize Telegram read receipts. Explicit private replies, described below, were deployed on 3 November 2026. A real outgoing reply remains unverified; no deployment test sent a message.

### Reply in a Business private chat

In Chats, select a connected Business conversation with **All messages** enabled, choose **Reply** on a captured message, and review the recipient and original message. Enter 1–4096 characters and click **Send as me** to send from your connected Telegram account. Telegram requires the bot's `can_reply` permission and an incoming message in that chat within the last 24 hours. The server checks current connection ownership and permissions; it never accepts an arbitrary Telegram destination from the browser or MCP caller.

For MCP, use `reply_to_chat_message` with the returned app `chat_id`, captured `message_id`, text and a UUID `request_id`. The client must show the exact recipient and text, obtain your approval, then set `confirmed=true`; `mentions:write` is required. This confirmation flag records the client's approval assertion, not a separate authentication mechanism.

Each attempt has durable duplicate protection: reuse its request ID when checking/repeating that same attempt. A repeated key never sends again; reusing it with different content or a different target is rejected. If delivery is uncertain, check Telegram before deliberately starting another reply with a new ID. **Check delivery** only reads the stored result. This does not guarantee exactly-once delivery: a crash or network timeout can leave the outcome unknown.

A successful reply is saved in the chat feed without advancing the summary checkpoint, archiving mentions or changing Telegram read receipts. If the original message disappeared on Telegram, Telegram may send a standalone message; the result reports whether a reply was attached. See the [reply deployment and rollback guide](docs/vps-deployment.md#private-business-replies--deployment-and-setup) before updating an existing installation. No real outgoing reply has been verified yet.

## Local development

This workspace has a separate interactive `./start.sh` for local development. It uses dev env files, runs the Vite development server, starts containers, and applies database migrations. It is **not** a VPS installer and does not configure production TLS or firewalling. Read the script before running it against an existing database.

Useful development and architecture references:

- [Bot and embedded auth](tg_flow_bot/README.md)
- [Frontend](tg_flow_frontend/README.md)
- [PostgreSQL service](tg_flow_storage/docs/README.md)
- [MCP, OAuth and CLI](MCP_AND_CLI.md)

## Security and data

Your instance stores Telegram user data and messages in PostgreSQL. Keep its volume and auth secrets backed up, limit access to the host and database, use TLS and trusted proxy boundaries, and review the groups where you add the bot and their capture settings in Chats. New group additions enable all-message capture for the person adding the bot. OAuth tokens and bot credentials are secrets; never commit them or paste them into support requests. Back up before applying migrations, changing signing keys, or deleting any container volumes.

No license file is present in this workspace; choose and publish a license before presenting the project as open source. The repository layout and public release process also need to be decided before a new user can reliably clone the exact stack described here.
