# VPS deployment: tg.mishanya.fun

Deployment directory: `/opt/tg-flow` on SSH host `tg-flow` (`root@2.26.120.178`).
Public frontend: `https://tg.mishanya.fun`.
Public MCP endpoint: `https://tg.mishanya.fun/mcp` (Streamable HTTP, OAuth).
Canonical issuer: `https://tg.mishanya.fun/` (trailing slash).

This is a new VPS installation made from the checked-out sibling repositories,
including their uncommitted integrated-auth changes. It is independent of the
existing development database on the Mac. `source-manifest.json` records the
commits and SHA-256 of each packaged source file. Server sources are a snapshot,
not Git clones: `git pull` on the VPS is not an update procedure.

## Telegram Business — deployment and setup

Telegram Business private-conversation capture was deployed on 3 November 2026 alongside the existing group bot. Additive Aerich migration 5 stores durable account connections and owner-scoped private conversation metadata. A real account connection, private ingestion and authenticated MCP reading were verified as recorded below; a real private GPT-summary/checkpoint workflow remains pending. Existing group IDs, users, credentials, issuer, capture settings and read checkpoints were preserved.

The migration is `5_20261103120000_add_business_connections.py`. Rebuild the bot image with `python-telegram-bot==22.8`, pinned for current rights-based Business connection payload parsing; do not retain a 21.7 runtime image for the new code.

Use the update/backup procedure below and obtain approval before changing production. Before applying migration 5, inspect Django/Aerich state, retain the current source manifest and rollback images, create a fresh database backup, and verify a restore into an isolated volume. Build before the maintenance window. Stop the bot writer, take the final backup, apply pending Django migrations followed by Aerich migrations, and start one bot polling process only. Do not reset the database, remove volumes or run an automatic downgrade. Keep the old images and backup; a rollback must preserve Business data and use a separately restored volume if schema compatibility is uncertain.

After deploying, enable **Secretary Mode / Business Mode** for the existing bot in BotFather. In the intended owner's Telegram account settings, connect the bot and select permitted private chats. Group Privacy Mode and `/setdomain` are separate settings and should remain configured. Follow [Telegram's current setup guide](https://core.telegram.org/bots/features#business-bots); do not paste credentials into chat or shell history.

Verify with new test messages in an explicitly selected private conversation:

- In Chats, a Business/private entry and active connection state appear only for the connected owner. Check text/caption collection in both directions, delivered edits/deletions, and absence from another user's API/MCP session.
- Through a real OAuth MCP client, list subscriptions, read the private chat's unread snapshot, create a summary, then acknowledge its observed boundary. Check that Telegram read receipts did not change.
- Disable capture in TG Flow; new messages must not be collected for that subscription and its full feed must be hidden. Reconnect in Telegram and verify the disabled choice remains disabled. Explicitly resume full capture and verify the owner's previous captured archive and read cursor remain intact, with no backfill from the disabled interval. Group feed interval boundaries remain unchanged.
- Disconnect in Telegram; new capture must stop, enabling full capture must fail, and already collected full-mode history/unread acknowledgement must remain available to its owner.
- Restart the service and verify connection ownership, subscriptions and checkpoints survive. Confirm group capture and existing OAuth tools still work.

Unknown connection IDs fail closed until Telegram delivers a connection lifecycle update. If the first event was missed, try disconnecting and reconnecting in Telegram; do not run another local bot using the production token. Ordering watermarks remain strict for messages, deletions and same-ID connection events. A lower-ID lifecycle event requires a fresh, non-retired connection ID verified live with `getBusinessConnection` against its ID, owner and enabled state; failed verification rejects it. A genuine Telegram update-ID reset after prolonged bot-wide inactivity may require a new connection ID or operator recovery. Reconnecting does not guarantee ID rotation; never clear ordering state or erase data automatically to work around it.

There is no old-history import, media-binary download or Telegram read-receipt synchronization. Ingestion does not send as the account; explicit replies use the separately authorized workflow below. Business IDs returned by TG Flow are app conversation IDs, not raw Telegram peer IDs or `t.me/c/…` links.

## Private Business replies — deployment and setup

Explicit private replies through Chats and MCP were deployed on 3 November 2026. Additive migration `6_20261103180000_add_business_reply_attempts.py` adds the durable per-owner reply-attempt ledger; the deployed database now has seven Aerich records. The user explicitly authorized this update. Real outgoing-message verification remains pending: deployment checks did not send messages. The verification and rollback record is below.

For subsequent approved updates, follow the backup/update procedure below: inspect the live Django/Aerich state, preserve source manifests, current images, configuration and credentials, take a fresh backup, and verify a restore into an isolated instance. Rehearse migration 6 against the restored current database and compare existing users, grants, Business ownership, captured rows and checkpoints. Build both bot and web before the maintenance window. Stop the writer, take the final backup, apply any pending Django migrations followed by Aerich migration 6, then start exactly one polling bot and the matching frontend. Do not reset data or remove volumes.

Preserve `business_reply_attempts` on every subsequent update or rollback: its committed reservation prevents duplicate sends under the same request UUID, including after a crash. The migration intentionally refuses downgrade. Do not clear reservations, delete rows, expire unknown attempts or replay a queued send to recover service. A same-key lookup/replay must only return the existing result; changed payload under the same key must fail. If rolling the application back to the current Business-capture release, verify its schema compatibility and retain the added table and migration history. A database rollback must use a separately restored volume and an explicitly approved cutover; preserve the post-update database and attempt records for reconciliation before any further sends.

New replies require an owner-scoped captured private target, full capture, an active matching Business connection and live Telegram `can_reply` permission. Telegram also requires incoming activity in that chat within the last 24 hours. The UI's **Send as me** button authorizes a specific recipient and text; MCP requires `mentions:write` and `confirmed=true` only after the client obtains that explicit approval. Neither a feature test nor a health check authorizes sending a real message. For live acceptance, obtain an actual test recipient and the exact approved text from the user first; do not use personal conversations for an unsolicited test.

After deployment, verify the UI recipient/target and explicit action, read-only attempt lookup, permissions and disconnected/disabled states, MCP write-scope challenge and false-confirmation rejection. Use mocks for failure/timeout cases rather than producing extra real messages. With a separately authorized test message, verify one delivery, its stored outgoing feed row and unchanged summary/read state. Repeating the same request UUID must return its existing result without a second delivery. Unknown results require checking Telegram before a separately approved new UUID. `reply_attached=false` on a sent result means Telegram used a standalone message because it could not attach the reply; it is not permission to resend. No exactly-once guarantee is claimed.

The website blocks a new send if it cannot persist and read back the tab's attempt metadata; the draft is retained and an actionable storage error is shown. Only attempt identifiers/status metadata are stored in `sessionStorage`, never reply drafts or original message text. Known recovery limitation: after reload, a retained attempt's composer is inaccessible when its chat is disabled/disconnected or its target is outside the visible feed. Use read-only MCP `get_chat_reply_status(chat_id, request_id)` or the equivalent owner-scoped GET with the retained request UUID. These require read scope, create no reservation and never re-send, including while capture is disabled or the connection inactive. A missing result may still correspond to an in-flight original request; do not create a new attempt automatically or clear the ledger/storage as a resend workaround. Check Telegram and reconcile delivery before a separately approved new send.

## Topology and security

Only edge nginx publishes ports 80 and 443. It terminates TLS, overwrites forwarding
headers, rate-limits registration and authentication, and routes `/api/`, `/oauth/`,
`/.well-known/`, and exact `/mcp` directly to the bot. Other requests go to the
frontend. MCP buffering is disabled. Request access logs are disabled at ingress
and Uvicorn to keep OAuth codes out of URL logs.

On the dedicated app bridge `172.30.40.0/28`, edge is `.2`, bot is `.3`, and frontend
is `.4`. Django trusts forwarding headers only from `172.30.40.2/32`; Uvicorn starts
with `--no-proxy-headers`. PostgreSQL has only an additional internal database network
with the bot and migration jobs, and no published port. The frontend trusts no
incoming forwarding headers; public backend requests bypass its proxy.

UFW permits TCP 22, 80, and 443. Docker-published ports can bypass UFW, so keeping
backend `ports` absent in Compose is part of the security boundary. All running
services have `restart: unless-stopped`. Runtime PostgreSQL, edge nginx and Certbot
images are pinned by digest; built bot/frontend images capture this source snapshot.

`/opt/tg-flow/.env` contains server-generated database, Django and introspection
secrets. `telegram.env` contains the bot token; both are private. Database credentials
match across PostgreSQL, bot `DB_*`, and Django `AUTH_DB_*`. Preserve these files,
the issuer, user IDs, migration history, and the `tg_flow_postgres` volume on updates.
The root database user is scoped to this isolated PostgreSQL instance.

## Verification record — 31 October 2026

Verified externally: trusted TLS, both discovery documents with the exact public
URLs, unauthenticated MCP `401` and OAuth challenge, unauthenticated mention API
`401`, and closed/filtered backend ports. Spoofed forwarded headers are overwritten
at ingress; a direct request from the untrusted frontend container cannot assert
HTTPS to Django. A token endpoint burst produced HTTP 429 responses as configured.
Database persistence and restart policies were checked, and a real backup restore
into an isolated PostgreSQL instance retained all migration records.

A real browser login exposed a frontend bug: the signed Telegram `photo_url` was
omitted from the authentication request. The fix preserves that field, has a
regression test, and is deployed. All 24 frontend tests and the production build
passed; the public JavaScript bundle was checked for the fix. The user confirmed
successful Telegram login on the website.

Two further checkout defects were repaired: migration `3_20261031123000` adds
missing `mentioned_messages.is_archived` and `chats.photo_file_id` columns without
changing existing values; the OAuth widget callback now checks the exact Telegram
frame/origin rather than using the CSP-blocked string callback. Its browser button
is visible with eval still forbidden. A PostgreSQL migration regression reproduced
the missing columns before the fix and passed afterward, including preservation of
existing archive/photo values. Backend validation: 153 tests passed, 2 skipped;
the PostgreSQL regression was run separately and passed. Production now has four
Aerich migrations, and a full model-column comparison passes.

The user confirmed successful OAuth connection. A real read-only
`get_mention_stats` call through the connected TG Flow MCP plugin succeeded on
31 October 2026, returning zero total mentions, chats with mentions, and recent
mentions. This verifies authenticated discovery/tool access through the chosen
client; Telegram group capture still requires Telegram permissions and a subscription.
The Mac development bot was stopped with the user's explicit approval to resolve
duplicate Telegram polling. HTTPS health checks alone are not end-to-end success.
Certificate renewal dry-run and Django deployment checks passed.

OAuth follow-up fixes accept Telegram's signed remembered-session (`init`) callback
and permit only the registered callback origin in the consent form's CSP. The
remembered-session JavaScript regression and a Chromium test of a real form POST
followed by a cross-origin 302 redirect both pass. Exact registered redirect URI,
PKCE, state, consent, and server-side Telegram signature checks remain in place.
The browser callback test can be rerun locally with
`python3 deployment/vps/bin/check-consent-redirect.py`; it uses isolated loopback
test servers and the installed `agent-browser` CLI, without production credentials.

If Telegram's popup closes without completing OAuth sign-in, the OAuth page offers
**Continue with your TG Flow account**. It exchanges the existing same-origin
website JWT for a Django login session, then reloads the authorization request to
show consent. `/oauth/session/web` requires a pending OAuth request, a valid access
JWT belonging to an active user, and CSRF protection. It ignores caller-supplied
user IDs and does not issue OAuth codes or tokens; explicit consent remains separate.
If no website token is present, the button opens `/login` in another tab. Sign in
there, then return and click Continue. No tokens are copied into chat or URLs.

## Update record — 2 November 2026 (Moscow)

Automatic group subscriptions and shared website/MCP unread checkpoints are deployed.
New bot additions subscribe only the person adding it, in full mode. Disabled
subscriptions retain history and remain disabled after re-adds. Existing groups
without a subscription need a one-time remove/re-add (or the optional recovery
command); owners and old history are not inferred.

`list_unread_chat_messages` and `mark_chat_read` are registered. Chats shows unread
counts and **Mark as read** using the same per-user cursor. Later arrivals remain
unread; reading alone never acknowledges. See [MCP_AND_CLI.md](../MCP_AND_CLI.md#unread-messages-and-summary-checkpoints).

Migration `4_20261102120000_add_chat_read_cursor.py` was applied after stopping bot
and taking a backup. There are now five Aerich records; Django had no pending
migrations. Config/secret file hashes, user IDs and the PostgreSQL volume are
unchanged. No volume was deleted or reset.

Release: `/opt/tg-flow/releases/read-checkpoint-1793568816870`.
Pre-migration backup: `/opt/tg-flow/backups/20261101T213428Z`.
An earlier backup at `/opt/tg-flow/backups/20261101T213320Z` also contains the old
sources before staging. Checksums passed. Previous sources, manifest and rollback
images are retained; exact application rollback commands are in the release's
`ROLLBACK.md`. The added columns are compatible with the previous application;
retain them and the migration record on an application rollback, with no downgrade.

Before deployment: backend 199 tests, frontend 44 tests, isolated PostgreSQL
migration/preservation/concurrency tests and desktop/mobile browser checks passed;
independent review approved. After deployment: public HTTPS/discovery, OAuth
challenge, current frontend bundle, tool registration, private ports, database
schema and bot restart checked. Existing authenticated MCP stats/subscription calls
succeeded. There were zero group subscriptions, so a real new-summary → mark-read
ChatGPT workflow still needs the bot re-added and the client's tool catalogue
refreshed. Deployment does not acknowledge messages on the user's behalf.

## Frontend update — 3 November 2026

Follow-up: removed all component shadows, including active mode buttons, toasts,
and hover states. Live HTTPS CSS was checked against the local build: every
box-shadow is none, with no text/drop shadows. Frontend-only release:
`/opt/tg-flow/releases/ui-no-shadows-1793718786956`; verified backup:
`/opt/tg-flow/backups/20261103T151326Z`. Previous image/source/manifest and
`ROLLBACK.md` are retained. Bot, database, edge and credentials were unchanged.

Deployed DM Sans for UI text and Redaction 50 regular for page headings and
headline numbers, with four locally hosted WOFF2 subsets and bundled OFL licenses.
Dashboard branding was removed; CSS and Tailwind component radii are zero.
Only the web container was rebuilt/recreated; bot, database and edge container IDs,
config/secret file hashes and private service bindings were verified unchanged.
No migrations or bot restart were needed.

Release: `/opt/tg-flow/releases/ui-fonts-1793718568857`.
Backup: `/opt/tg-flow/backups/20261103T150949Z` (checksums verified).
Previous frontend source/image, previous manifest and exact frontend-only rollback
commands are retained in the release directory (`ROLLBACK.md`).

Public HTTPS delivered the updated JS/CSS; all four font files were downloaded
and checked against the local source hashes. MCP discovery and its unauthenticated
OAuth challenge still passed; frontend nginx logs had no error entries.

## Business release — 3 November 2026

Release: `/opt/tg-flow/releases/business-20261103T153050Z`.
Final pre-migration backup: `/opt/tg-flow/backups/20261103T153345Z`.
Pre-build backup: `/opt/tg-flow/backups/20261103T153051Z`.
Both backup checksums passed. The pre-build dump was restored and migration 5
rehearsed in an isolated networkless PostgreSQL instance. Every existing
non-migration row was preserved. The final stopped-writer dump was independently
restored, and fingerprints for every table matched the pre-migration snapshot.
The disposable verification instance was then stopped; production volumes were
not removed or reset.

Bot and web images were rebuilt from the checked-out sibling repositories with
PTB 22.8. Django had no pending migration; Aerich now has six records. The live
migration preserved all existing rows, including the user, subscriptions, message
history, OAuth records and read checkpoints. Configuration/secret file hashes,
PostgreSQL volume and DB/edge container IDs are unchanged. SSH, firewall rules and
the unrelated service on TCP 8443 were not changed. Restart policies and private
backend/database bindings were checked; bot restart preserved subscription modes
and checkpoints and recovered its health endpoint.

Verified externally: frontend/login/chats HTTP 200, current Business JS/CSS,
unchanged self-hosted font hashes, exact public issuer/resource discovery and
unauthenticated MCP OAuth challenge. An authenticated `list_chat_subscriptions`
call through the connected MCP plugin returned the existing groups with the new
source/connection metadata. Logs contained no error/exception/polling-conflict
matches. Local pre-release validation: backend 218 tests, frontend 49 tests,
isolated PostgreSQL migration regression and independent review passed.

Initially, Telegram `getMe` reported Business connection capability disabled. The
user then enabled Secretary/Business Mode and connected the bot to their account.
After the user's configuration steps, the server received one active connection and captured two
messages in two private chats. Telegram's `getBusinessConnection` confirmed the
connection was enabled and its owner matched the stored owner. The connected MCP
client listed both private chats with active/full metadata and successfully read
one message through the real read-only `list_chat_messages` tool. Message text,
peer names and connection identifiers were not included in this verification
record. A real private-summary/mark-read workflow, deletion/edit delivery and
revocation/reconnection retention still require live acceptance testing; local
regression coverage is not claimed as proof of those live paths. Refresh the
client's tool catalogue if the unread/checkpoint tools are missing.

The release retains previous sources/manifest and rollback image tags. Read its
`ROLLBACK.md` before reverting: the previous application is safe only before any
Business connections/private rows exist. Once private data exists, keep ownership
guards and fix forward, or restore into a separate volume with an approved cutover.
Never downgrade migration 5 or clear ordering state.

## Private reply release — 3 November 2026

Release: `/opt/tg-flow/releases/replies-20261103T174732Z`.
Final pre-migration backup: `/opt/tg-flow/backups/20261103T174921Z`.
Pre-build backup: `/opt/tg-flow/backups/20261103T174732Z`.
Backup checksums passed. The pre-build dump was restored in an isolated,
networkless PostgreSQL instance and migration 6 rehearsed there. Every existing
row was preserved; the new ledger was empty. The final stopped-writer dump was
independently restored and all 21 table fingerprints matched the pre-migration
snapshot. The temporary verification instance was then stopped.

Bot/web images were rebuilt from the checked-out sibling sources. Django had no
pending migrations; migration 6 brought Aerich history to seven records. Every
prior live row, including Business ownership, captured messages, OAuth state and
checkpoints, was preserved. Credential/configuration hashes, DB volume, DB/edge
container IDs, firewall and the unrelated TCP 8443 listener were unchanged.
Backend/database ports remain private. Previous sources, manifest, images and
exact application rollback commands are retained in the release's `ROLLBACK.md`.
A transient SSH disconnect during cutover was followed by a state inspection;
completed migration and startup were verified without repeating the migration.

Verified externally: trusted HTTPS, frontend/login/chats HTTP 200, new reply UI
bundle, unchanged font hashes, exact MCP/OAuth discovery and unauthenticated MCP
challenge. Anonymous reply-status GET required authentication. The live MCP tool
registry includes `reply_to_chat_message` with confirmation defaulting false and
read-only `get_chat_reply_status`; an authenticated existing read-only MCP call
succeeded. Refresh the client's tool catalogue to expose the new tools. Django
production checks and log scan passed. Bot restart retained subscription modes,
read checkpoints, the ledger table and migration history.

Pre-release checks: 247 backend tests, 71 frontend tests, build/lint, isolated
PostgreSQL migration/concurrency/crash-restart checks and independent review passed.
No real Telegram reply was sent during deployment; a real recipient and exact
approved text are required for outgoing acceptance. Retain all reply-attempt rows
on application rollback; do not downgrade migration 6 or erase unknown attempts.

## Inspect and operate

Run on the VPS:

```bash
cd /opt/tg-flow
docker compose ps
docker compose exec -T bot python manage.py showmigrations --plan
docker compose run --rm --no-deps migrate aerich history
systemctl list-timers 'tg-flow-*'
ufw status verbose
```

Migration jobs use the maintenance service, which has no fixed app-network address.
Running `docker compose run bot ...` while the bot is up conflicts with its fixed IP.
Use `exec bot` for inspections of the running application.

Inspect logs locally on the VPS; review and redact before sharing:

```bash
docker compose logs --tail 100 bot
docker compose logs --tail 100 edge db
journalctl -u tg-flow-backup.service -u tg-flow-tls.service --since today
```

Restart the bot with `docker compose restart bot`. For database maintenance, stop
the bot first, restart the database, wait for health, then start the bot:

```bash
docker compose stop bot
docker compose restart db
docker compose up -d --wait db
docker compose up -d bot
```

Never run two polling instances with the same Telegram token. The development
container on the Mac must remain stopped while this VPS uses that bot.

## Backups and restore

```bash
/opt/tg-flow/bin/backup
```

The daily timer runs at 03:15 Moscow time with up to five minutes jitter. Each backup
directory under `/opt/tg-flow/backups/` contains:

- `database.dump`: consistent PostgreSQL custom-format dump of both app schemas.
- `globals.sql`: PostgreSQL roles, including credential hashes.
- `deployment.tar.gz`: sources, configuration, bot credentials and TLS state.
- `SHA256SUMS`: integrity checksums.

Backups contain secrets and private data. Keep them private, encrypt any exported
copies, and maintain an off-server copy. No off-server destination is configured;
server-only backups do not protect against loss of the VPS. Backups are not pruned
automatically; monitor disk usage.

Before restoring, stop writers, back up the current state and select the exact backup.
Verify `sha256sum -c SHA256SUMS` inside its directory. Restore into a **new volume or
isolated PostgreSQL instance**, using that backup's database credentials and matching
application sources. Restore the deployment archive into a staging directory, inspect
it, and use `pg_restore --exit-on-error --no-owner -U <database-user> -d <empty-database>`
with `database.dump` supplied via stdin. Do not apply `--clean` to the live database.
The deployment's database role is created from its preserved environment; consult
`globals.sql` for additional roles rather than blindly restoring duplicate roles.

For initial validation, a dump was restored into the isolated, networkless container
`tg-flow-restore-check`: all 20 Django and 3 Aerich migration records were present.
The stopped verification container and its separate `tg_flow_restore_check` volume
are retained. They are not the production database or a current backup.

## Update and rollback

Review pending migrations and obtain explicit approval before changing an existing
installation. Do not regenerate secrets, change the issuer, reset databases, remove
volumes, or assume the remote default branches match the desired source.

On the Mac, from the workspace root, create and transfer a reviewed snapshot:

```bash
python3 deployment/vps/bin/snapshot-source.py /tmp/tg-flow-update.tar.gz
scp /tmp/tg-flow-update.tar.gz tg-flow:/opt/tg-flow/incoming.tar.gz
```

Use a new archive filename if that local file already exists. On the VPS, use a
unique release ID, retain the current images and sources, and create a backup:

```bash
cd /opt/tg-flow
release=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "releases/$release/incoming"
tar -xzf incoming.tar.gz -C "releases/$release/incoming"
/opt/tg-flow/bin/backup
docker tag tg-flow-bot:vps-initial "tg-flow-bot:rollback-$release"
docker tag tg-flow-web:vps-initial "tg-flow-web:rollback-$release"
mv src "releases/$release/previous-src"
cp source-manifest.json "releases/$release/previous-manifest.json"
mv "releases/$release/incoming/src" src
cp "releases/$release/incoming/source-manifest.json" source-manifest.json
docker compose build bot web
docker compose run --rm --no-deps migrate python manage.py showmigrations --plan
docker compose run --rm --no-deps migrate aerich history
```

Check and approve the migration plan, then during the maintenance window:

```bash
docker compose stop bot
/opt/tg-flow/bin/backup
docker compose run --rm --no-deps migrate python manage.py migrate --noinput
docker compose run --rm --no-deps migrate aerich upgrade
docker compose up -d bot web
docker compose exec -T edge nginx -t
docker compose exec -T edge nginx -s reload
```

If the build fails, the old running containers remain available. Restore the previous
source directory and manifest before retrying. If an application rollback is compatible
with the resulting database schema, retag `tg-flow-bot:rollback-<release>` and
`tg-flow-web:rollback-<release>` to `:vps-initial`, restore previous sources and manifest,
and recreate bot/web with `docker compose up -d --force-recreate bot web`.
When migrations are not backward-compatible, keep writers stopped and restore the
pre-migration backup into a separate volume, then explicitly approve switching to it.
Never use `down -v`, `volume rm`, database reset, or automatic migration downgrades.

## HTTPS and client verification

The TLS timer checks renewal twice daily; nginx reloads after a successful check.
Run `/opt/tg-flow/bin/renew-tls` manually if needed. Certificate state is in
`/opt/tg-flow/letsencrypt`; the certificate was obtained without an account email.

External checks:

```bash
curl -fsS https://tg.mishanya.fun/.well-known/oauth-protected-resource/mcp
curl -fsS https://tg.mishanya.fun/.well-known/oauth-authorization-server
curl -i https://tg.mishanya.fun/mcp
```

Check the exact issuer/resource URLs and a `401` with `WWW-Authenticate: Bearer ...`
and the protected-resource metadata URL when unauthenticated. Confirm ports 5432,
8081 and frontend internal ports are unreachable externally. These checks do not
prove user authentication or an authenticated tool call.

This checkout uses Telegram's legacy login widget. In BotFather use `/setdomain`,
select `@testtestst12321312_bot`, and set `tg.mishanya.fun`. Open
`https://tg.mishanya.fun/login` and complete the real Telegram login.

In ChatGPT open [Plugins](https://chatgpt.com/plugins), select **+ → Add custom MCP
server**, provide a name and `https://tg.mishanya.fun/mcp`, select OAuth, and create
the plugin. Complete Telegram login and consent. Account/workspace policies may
restrict this capability. Public OAuth client registration is supported; there is
no client secret to paste and no Client ID Metadata Document support. Select the
plugin in a new chat and request **get_mention_stats, read-only**. Record a real
tool result before declaring the ChatGPT integration verified.

Sources: [OpenAI connection guide](https://developers.openai.com/apps-sdk/deploy/connect-chatgpt/),
[Telegram legacy widget](https://core.telegram.org/widgets/login-legacy),
[nginx rate limits](https://nginx.org/en/docs/http/ngx_http_limit_req_module.html),
[Docker firewall caveats](https://docs.docker.com/engine/install/ubuntu/#firewall-limitations),
[Certbot webroot](https://eff-certbot.readthedocs.io/en/stable/using.html#webroot).
