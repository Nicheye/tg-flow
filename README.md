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
inbox and an OAuth-protected remote MCP server at https://<my-domain>/mcp.
Treat this as a deployment task: inspect, prepare a reviewable plan, implement
approved changes, and verify the result. Do not claim unverified steps succeeded.

1. Establish the exact source and target

Use this checked-out TG Flow monorepo containing tg_flow_bot,
tg_flow_frontend, and tg_flow_storage. Confirm its absolute root and the build
contexts before acting; do not accidentally deploy similarly named sibling
copies. Read AGENTS.md, the current source, all relevant README/env examples,
MCP_AND_CLI.md, docs/vps-deployment.md, and deployment/vps/. Use the exact checkout,
including relevant uncommitted files, package-lock.json and pinned requirements.
Do not substitute remote default branches, stale images, or upgrade dependencies
as a deployment shortcut. Run the relevant existing checks before rollout.
Record the commit, working-tree file hashes and resulting image IDs/digests.
Exclude real secrets, local databases, caches and development credentials from
source archives and build contexts. Adapt all example domains, paths, service
names, networks and IPs to this host. The runbook's recorded VPS is an example,
not authorization to connect to it, copy its credentials, or change its services.

Ask me only for information or actions you cannot derive or perform: the intended
host/domain and SSH access, account/client choices, required Telegram interaction,
or secure credential entry. Never ask for tokens, passwords or private keys in
chat or command history. Reuse authorized SSH access, verify the server identity,
and do not bypass SSH host-key or browser/TLS warnings. Do not create or rotate
credentials if an existing installation already has working ones.

2. Inspect before changing anything

Explain the OS/architecture, resources/free disk, clock synchronization,
Docker/Compose versions, listening/published ports, firewall rules, DNS,
reverse proxy, TLS, existing TG Flow containers/images, mounts/volumes,
database and migration state, scheduled jobs, backups and other applications.
Determine whether this is a fresh installation or an upgrade. Check for other
polling processes using this bot token, including local development instances,
and any webhook/polling conflict, without exposing the token or webhook secrets.

Check the intended subdomain's authoritative and public DNS, including A/AAAA.
An AAAA record must not point to an unusable IPv6 ingress. Preserve root-domain,
mail and unrelated records. Do not change authoritative nameservers without
explicit approval. Distinguish DNS failure from application failure using a
direct-IP request with the correct hostname and full TLS verification; do not
turn off certificate checks or redeploy blindly when DNS is the problem.

Show a concrete plan with the affected services, expected interruption, pending
migrations, backup location, verification steps and rollback boundary. Before
changing an existing database/deployment, obtain my explicit approval unless
this session already authorizes that exact change. Never delete volumes, reset
databases, revoke credentials, change unrelated services or silently replace
an existing installation. Preserve SSH access and other applications.

3. Preserve data and establish recovery

Before an upgrade, retain the running image IDs/tags, sources, manifest and
configuration. Back up both bot and Django/OAuth data, database roles,
credentials/signing keys, deployment files and TLS state. Verify checksums and
restore into an isolated, non-public database; rehearse pending migrations there.
For the live migration, stop writers and take a final consistent backup.
Compare stable pre-existing rows/ownership and migration state after rollout.
Keep users, OAuth clients/grants, issuer, signing keys, subscriptions, messages,
capture settings, read checkpoints and Business ownership intact.

Preserve every business_reply_attempts row and its no-resend semantics. Never
clear/downgrade the ledger, expire uncertain attempts, or resend them after a
restart or restore. An older image may be unsafe once Business/private data or
reply attempts exist: check schema and ownership compatibility before choosing
an application rollback. Do not automatically downgrade migrations. If database
restore is needed, restore into a separate volume and get approval for cutover;
never restore destructively over the live database. Retain rollback artifacts.

Configure scheduled backups, verify a restore, and arrange an encrypted off-VPS
copy to a destination I approve. If an off-server destination is unavailable,
report that gap explicitly; local-only backups do not cover loss of the VPS.
Monitor backup growth without automatic volume removal or unapproved pruning.

4. Configure production authentication and frontend

Use integrated auth explicitly (AUTH_LOCAL_ASGI=True) and persistent PostgreSQL.
For one shared database, PostgreSQL credentials must match DB_* and AUTH_DB_*;
preserve separate existing auth data rather than silently starting an empty DB.
Set DEBUG=False. Generate unique strong server-side secrets only for a new
installation or genuinely missing settings. Preserve existing credentials,
user IDs, Django/JWT signing keys, public issuer and migration history.
Keep secret files private and out of Git, logs and build arguments.

Set OAUTH_ISSUER consistently to the canonical public HTTPS issuer (including
its normalized trailing slash), and MCP_RESOURCE_URI to the exact public
https://<my-domain>/mcp resource. Match resource-server introspection credentials
across auth and MCP. Verify the bot token privately using Telegram getMe and
use the actual username. BOT_TOKEN and TELEGRAM_BOT_TOKEN, if both set, must
identify the same bot. Use a hidden server-side prompt or equivalent secure
mechanism for token entry; do not expose token-bearing Telegram API URLs.

Configure exact allowed hosts/origins, CORS/CSRF settings and secure cookies for
the actual topology, without broad production wildcards. Build the frontend
with the correct public VITE_BOT_USERNAME, VITE_API_URL and VITE_AUTH_API_URL
(or verified same-origin defaults). VITE_* values are public build-time values:
never place secrets there. Verify the served bundle and local font/static assets,
not just the source env file. Review the intended account-access/registration
policy and verify that unauthenticated users cannot read private data.

5. Configure networking and operation

Install only missing, compatible prerequisites from official sources; do not
upgrade unrelated software. Use production Compose/service definitions adapted
to this installation.
Only publish the intended HTTP/HTTPS ingress; keep PostgreSQL, bot port 8081
and the frontend's internal port off the public internet. The Makefiles publish
ports broadly, so do not deploy them unchanged. Check both firewall rules and
Docker port publishing; firewall rules alone do not constrain published ports.
Avoid overlapping Docker networks and preserve existing applications.

Provision trusted HTTPS, HTTP-to-HTTPS redirects, ACME challenge routing and
automated certificate renewal. Test renewal and verify its timer/reload behavior.
Route /api/, /oauth/, /.well-known/ and exact /mcp to the correct backend;
serve frontend deep links correctly. /mcp uses Streamable HTTP: preserve the
path, avoid caching/buffering, and configure suitable connection timeouts.
Trust forwarded HTTPS/host headers only from the actual immediate reverse-proxy
peer, not arbitrary clients or a shared network. Overwrite untrusted headers
at ingress. Verify spoofed forwarding headers cannot bypass this boundary.

Rate-limit registration, token and login/authorization/session endpoints at
trusted ingress where supported. Keep access/error logs from recording OAuth
codes, token-bearing URLs, authorization headers, cookies, Telegram tokens or
private message content; disable unsafe HTTPX/request logging. Set bounded log
rotation. Inspect/redact before sharing logs or resolved Compose configuration.

Build images, start PostgreSQL and wait for readiness. With writers stopped,
inspect and apply pending Django auth migrations, then checked-in Aerich bot
migrations in their documented order, including current Business/reply tables.
Use a maintenance container with no polling or fixed-IP conflict. Do not generate
an empty replacement schema or use local start.sh as a production installer.
Start the services only after migrations succeed. Keep one active polling bot
per token and one app worker/replica for this combined polling deployment;
no development reload or accidental parallel workers. Preserve pending Telegram
updates and request membership/Business message, edit and deletion update types.
Verify startup, restart policies, actual restart recovery and database persistence.
For a frontend-only update, avoid restarting/migrating the bot or DB unnecessarily.

6. Complete Telegram setup and capture verification

Help me configure the bot's login domain in BotFather and complete real Telegram
website login. For groups, ensure the bot may receive the desired messages
through the appropriate Privacy Mode/group permissions. New additions should
subscribe only the human who added the bot in full mode, without mandatory
/start or /subscribe. Existing modes, especially disabled, must stay unchanged.
For an old group without a subscription, explain the one-time remove/re-add or
optional recovery command rather than guessing ownership. Verify new ingestion
and reversible UI disabling without deleting history or exposing another owner's
messages. Do not print private message text.

Include Telegram Business private chats. Verify current Telegram account/client
eligibility, BotFather Secretary/Business Mode and the account's chat-automation
connection settings using current official instructions. Help me select which
private conversations the bot may access. Website login alone does not connect
the Telegram account. Verify the live connection and newly delivered events,
owner isolation, UI active/disconnected and full/disabled states, and retention
of already captured history/checkpoints as documented. Preserve persistent event
ordering; do not reset watermarks or promise reconnecting rotates a connection ID.
Do not promise old-history import, attachment downloads or automatic Telegram
read-receipt syncing. Report unavailable account features or missing rights.

7. Verify OAuth, MCP and unread workflow

From outside the VPS, verify trusted HTTPS, both discovery endpoints
/.well-known/oauth-protected-resource/mcp and
/.well-known/oauth-authorization-server, the exact issuer/resource, and the
expected unauthenticated /mcp OAuth challenge. Verify protected APIs reject
unauthenticated access and internal ports remain unreachable externally.
Test the actual chosen client's Telegram login, OAuth consent and a real
read-only MCP call; a health check or local tool registry alone is insufficient.
Preserve existing working sessions and validate write-scope enforcement.

Refresh the client's tool catalogue after metadata changes, start a new chat,
and check client-visible tools against MCP_AND_CLI.md. In particular verify
list_unread_chat_messages, mark_chat_read, reply_to_chat_message and
get_chat_reply_status, their schemas and documented scopes. For ChatGPT, use
the connection's Refresh action where available; do not treat a VPS-only tools
listing as proof the client can call it. If a provider step requires me, give
exact current instructions without asking for secrets or full OAuth URLs.

For requested GPT summaries, read every page of a fixed unread snapshot,
produce the summary successfully, then acknowledge only the processed boundary
with its capture-mode generation. Newer arrivals must remain unread. Reading
alone and failed/partial processing must not acknowledge unprocessed messages.
Verify the UI Mark as read and MCP share the same per-owner checkpoint; use
isolated fixtures or an explicitly requested real workflow. Do not mark real
messages read merely for a deployment check, archive mentions instead of marking
read, or confuse this cursor with Telegram read receipts.

8. Verify private replies without unintended sends

Check the private Reply / Send as me UI, ownership, write-scope enforcement and
reply_to_chat_message confirmation gate using mocks or non-sending probes.
Sending requires a current owner-matched Business connection, can_reply rights,
a captured target in that chat and Telegram's recent-incoming-message eligibility.
Never send a real test message without my approval of the recipient and exact
text. For an approved real attempt, use one UUID request_id; repeated keys must
never cause another send. A fresh UUID is a separately approved new attempt.

Check delivery using only read-only get_chat_reply_status or its GET endpoint.
Timeouts, reloads, missing results, rate limits or unknown status never authorize
an automatic resend. Check Telegram and reconcile before a separately approved
new send. Explain unknown delivery and reply_attached=false without retrying.
Preserve attempt metadata across browser reloads and report storage/recovery
limitations. Distinguish registered tools, mock tests and real delivery actually
verified; outgoing verification may remain pending if I do not approve a send.

9. Handover

Report what changed, the deployed source/image manifest, backup and rollback
locations, checks performed/results, and any unresolved or user-only steps.
Give the verified website/MCP URLs, exact client setup/refresh instructions,
commands to inspect logs/status/migrations, restart and safely update the stack,
certificate/backup schedules, and backup/restore/rollback guidance. Explain the
unverified steps and off-server backup gaps explicitly. Never print secrets.
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
