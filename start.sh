#!/usr/bin/env bash
set -euo pipefail

# Start the local development stack. Docker services stay up after Ctrl+C;
# the foreground Vite server stops with this script.
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
STORAGE_DIR="$ROOT_DIR/tg_flow_storage"
BOT_DIR="$ROOT_DIR/tg_flow_bot"
FRONTEND_DIR="$ROOT_DIR/tg_flow_frontend"
ENV_FILE="envs/dev/env.op"

fail() { printf '\nError: %s\n' "$*" >&2; exit 1; }
step() { printf '\n==> %s\n' "$*"; }

env_value() {
  # Read data as data: never source an env file as shell code. Last entry wins.
  awk -v key="$2" '
    /^[[:space:]]*#/ { next }
    {
      line = $0
      sub(/^[[:space:]]*export[[:space:]]+/, "", line)
      pos = index(line, "=")
      if (!pos) next
      name = substr(line, 1, pos - 1)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", name)
      if (name != key) next
      value = substr(line, pos + 1)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      if (value ~ /^".*"$/ || value ~ /^\047.*\047$/) value = substr(value, 2, length(value) - 2)
      found = value
    }
    END { print found }
  ' "$1"
}

ensure_file() {
  if [[ ! -f "$1" ]]; then
    mkdir -p "$(dirname "$1")"
    (umask 077; : > "$1")
    printf 'Created configuration file: %s\n' "$1"
  fi
}

ensure_value() {
  local file="$1" key="$2" description="$3" default_value="${4:-}" secret="${5:-false}"
  local value answer prompt
  value="$(env_value "$file" "$key")"
  case "$value" in
    ''|YOUR_BOT_TOKEN_HERE|YOUR_BOT_USERNAME|your_bot_username) ;;
    *) return ;;
  esac
  [[ -t 0 ]] || fail "Set $key in $file, or run this script in an interactive terminal."
  prompt="$description ($key)"
  if [[ -n "$default_value" ]]; then
    if [[ "$secret" == true ]]; then
      prompt="$prompt [Enter to use the value from related settings]"
    else
      prompt="$prompt [$default_value]"
    fi
  fi
  while :; do
    printf '%s: ' "$prompt" >&2
    if [[ "$secret" == true ]]; then
      if ! IFS= read -r -s answer; then fail "Input for $key was interrupted."; fi
      printf '\n' >&2
    else
      if ! IFS= read -r answer; then fail "Input for $key was interrupted."; fi
    fi
    value="${answer:-$default_value}"
    if [[ -z "$value" ]]; then
      printf 'A value is required.\n' >&2
    elif [[ "$value" =~ ^[a-zA-Z0-9_.,:/@%+=-]+$ ]]; then
      break
    else
      printf 'Use a value without spaces, quotes, or shell special characters.\n' >&2
    fi
  done
  # A leading newline also handles existing files without a final newline.
  printf '\n%s=%s\n' "$key" "$value" >> "$file"
}

copy_if_missing() {
  local file="$1" key="$2" value="$3" current
  current="$(env_value "$file" "$key")"
  case "$current" in
    ''|YOUR_BOT_USERNAME|your_bot_username) ;;
    *) return 0 ;;
  esac
  # The Makefiles consume env files with xargs, so values must remain compatible
  # with that parser. Reject unsupported input without printing the value.
  [[ "$value" =~ ^[a-zA-Z0-9_.,:/@%+=-]+$ ]] || \
    fail "Could not safely copy $key: check the format of the source value."
  printf '\n%s=%s\n' "$key" "$value" >> "$file"
}

configure_env() {
  local storage_env="$STORAGE_DIR/$ENV_FILE" bot_env="$BOT_DIR/$ENV_FILE"
  local frontend_env="$FRONTEND_DIR/.env" key value auth_engine separate_auth=false
  step 'Checking environment configuration'
  ensure_file "$storage_env"
  ensure_file "$bot_env"
  ensure_file "$frontend_env"

  ensure_value "$storage_env" DB_NAME 'PostgreSQL database name' tg_flow
  ensure_value "$storage_env" DB_USER 'PostgreSQL user' postgres
  ensure_value "$storage_env" DB_PASSWORD 'PostgreSQL password' '' true
  ensure_value "$storage_env" DB_PORT 'PostgreSQL host port' 5432
  ensure_value "$storage_env" NETWORK 'Docker network name' flow_net

  ensure_value "$bot_env" BOT_TOKEN 'Telegram bot token from BotFather' '' true
  ensure_value "$bot_env" TELEGRAM_BOT_USERNAME 'Telegram bot username without @'
  copy_if_missing "$bot_env" AUTH_LOCAL_ASGI True
  copy_if_missing "$bot_env" DB_ENGINE postgresql
  for key in DB_NAME DB_USER DB_PASSWORD NETWORK; do
    value="$(env_value "$storage_env" "$key")"
    copy_if_missing "$bot_env" "$key" "$value"
  done
  copy_if_missing "$bot_env" DB_HOST db
  copy_if_missing "$bot_env" DB_PORT 5432

  if [[ "$(env_value "$bot_env" AUTH_LOCAL_ASGI)" =~ ^([Tt]rue|1)$ ]]; then
    if [[ -z "$(env_value "$bot_env" AUTH_DB_ENGINE)" && -n "$(env_value "$bot_env" AUTH_DB_NAME)" ]]; then
      ensure_value "$bot_env" AUTH_DB_ENGINE 'Existing authentication database type (postgresql/sqlite3)'
    else
      copy_if_missing "$bot_env" AUTH_DB_ENGINE postgresql
    fi
    auth_engine="$(env_value "$bot_env" AUTH_DB_ENGINE)"
    [[ "$auth_engine" == postgresql || "$auth_engine" == sqlite3 ]] || fail 'AUTH_DB_ENGINE must be postgresql or sqlite3.'
    if [[ "$auth_engine" == postgresql ]]; then
      # An existing different setting means this may be a separate database.
      # Preserve it and ask for its missing settings instead of guessing.
      for key in NAME USER PASSWORD HOST PORT; do
        value="$(env_value "$bot_env" "AUTH_DB_$key")"
        if [[ -n "$value" && "$value" != "$(env_value "$bot_env" "DB_$key")" ]]; then
          separate_auth=true
        fi
      done
      for key in NAME USER PASSWORD HOST PORT; do
        value="$(env_value "$bot_env" "DB_$key")"
        if [[ "$separate_auth" == false ]]; then
          copy_if_missing "$bot_env" "AUTH_DB_$key" "$value"
        elif [[ "$key" == PASSWORD ]]; then
          ensure_value "$bot_env" "AUTH_DB_$key" 'Separate authentication database password' '' true
        else
          ensure_value "$bot_env" "AUTH_DB_$key" 'Separate authentication database setting'
        fi
      done
    else
      ensure_value "$bot_env" AUTH_DB_NAME 'Path to the existing SQLite authentication database inside the container'
    fi
    if [[ -z "$(env_value "$bot_env" DJANGO_SECRET_KEY)" && -z "$(env_value "$bot_env" SECRET_KEY)" ]]; then
      ensure_value "$bot_env" DJANGO_SECRET_KEY 'Existing Django secret key (required to preserve sessions)' '' true
    fi
  elif [[ "$(env_value "$bot_env" AUTH_LOCAL_ASGI)" =~ ^([Ff]alse|0)$ ]]; then
    ensure_value "$bot_env" AUTH_API_URL 'External authentication URL'
    ensure_value "$bot_env" OAUTH_INTROSPECTION_URL 'External authentication introspection URL'
  else
    fail 'AUTH_LOCAL_ASGI must be True or False.'
  fi

  copy_if_missing "$frontend_env" VITE_API_URL http://localhost:8081
  value="$(env_value "$frontend_env" VITE_API_URL)"
  copy_if_missing "$frontend_env" VITE_AUTH_API_URL "${value%/}/api/auth"
  value="$(env_value "$bot_env" TELEGRAM_BOT_USERNAME)"
  copy_if_missing "$frontend_env" VITE_BOT_USERNAME "$value"
}

main() {
configure_env

storage_network="$(env_value "$STORAGE_DIR/$ENV_FILE" NETWORK)"
bot_network="$(env_value "$BOT_DIR/$ENV_FILE" NETWORK)"
[[ "$storage_network" == "$bot_network" ]] || fail 'NETWORK differs between the database and bot settings.'

for command in docker make npm curl; do
  command -v "$command" >/dev/null 2>&1 || fail "Command not found: $command"
done
docker info >/dev/null 2>&1 || fail "Docker is unavailable. Start the Docker daemon or Docker Desktop."
docker compose version >/dev/null 2>&1 || fail "Docker Compose is unavailable."

step 'Starting PostgreSQL'
(cd "$STORAGE_DIR" && ENV_FILE="$ENV_FILE" make up)
db_id="$(cd "$STORAGE_DIR" && docker compose --env-file "$ENV_FILE" ps -q db)"
[[ -n "$db_id" ]] || fail 'PostgreSQL container not found.'
db_ready=false
for ((attempt=0; attempt<60; attempt++)); do
  if docker exec "$db_id" pg_isready -q >/dev/null 2>&1; then
    db_ready=true
    break
  fi
  sleep 1
done
[[ "$db_ready" == true ]] || fail 'PostgreSQL was not ready within 60 seconds. Check the database logs.'
db_ip="$(docker inspect --format '{{range .NetworkSettings.Networks}}{{println .IPAddress}}{{end}}' "$db_id" | head -n 1)"
[[ -n "$db_ip" ]] || fail 'Could not determine the PostgreSQL network address.'

check_db_credentials() {
  local prefix="$1" label="$2" host port database user password
  host="$(env_value "$BOT_DIR/$ENV_FILE" "${prefix}HOST")"
  port="$(env_value "$BOT_DIR/$ENV_FILE" "${prefix}PORT")"
  # Only validate the local storage service; remote databases can have other credentials.
  [[ "$host" == db && "$port" == 5432 ]] || return 0
  database="$(env_value "$BOT_DIR/$ENV_FILE" "${prefix}NAME")"
  user="$(env_value "$BOT_DIR/$ENV_FILE" "${prefix}USER")"
  password="$(env_value "$BOT_DIR/$ENV_FILE" "${prefix}PASSWORD")"
  if ! printf '%s\n' "$password" | docker exec -i "$db_id" sh -c \
    'IFS= read -r PGPASSWORD; export PGPASSWORD; exec psql -h "$1" -U "$2" -d "$3" -Atqc "SELECT 1"' \
    sh "$db_ip" "$user" "$database" >/dev/null 2>&1; then
    fail "Could not connect $label to PostgreSQL. Check ${prefix}NAME, ${prefix}USER, and ${prefix}PASSWORD in $BOT_DIR/$ENV_FILE and the database settings in $STORAGE_DIR/$ENV_FILE. If the Docker volume already existed, restore its original database name, user, and password: changing env settings does not reinitialize the volume. Do not delete the volume if you need its data."
  fi
}

step 'Checking access to the existing database'
check_db_credentials DB_ 'the bot'
if [[ "$(env_value "$BOT_DIR/$ENV_FILE" AUTH_LOCAL_ASGI)" =~ ^([Tt]rue|1)$ ]] && \
   [[ "$(env_value "$BOT_DIR/$ENV_FILE" AUTH_DB_ENGINE)" == postgresql ]]; then
  check_db_credentials AUTH_DB_ 'authentication'
fi

bot_state="$(docker inspect --format '{{.State.Status}}' tg-flow-bot 2>/dev/null || true)"
if [[ "$bot_state" == running ]]; then
  step 'Bot container is already running; using it without recreation'
elif [[ -n "$bot_state" ]]; then
  fail "Container tg-flow-bot exists but its state is $bot_state. Check docker logs tg-flow-bot."
else
  step 'Building the bot and embedded authentication'
  (cd "$BOT_DIR" && make build)
  if [[ "$(env_value "$BOT_DIR/$ENV_FILE" AUTH_LOCAL_ASGI)" =~ ^([Tt]rue|1)$ ]]; then
    step 'Applying authentication migrations'
    (cd "$BOT_DIR" && ENV_FILE="$ENV_FILE" make auth-migrate)
  fi
  step 'Starting the bot'
  (cd "$BOT_DIR" && ENV_FILE="$ENV_FILE" make up)
fi

step 'Waiting for the API to become ready'
api_ready=false
for ((attempt=0; attempt<60; attempt++)); do
  bot_state="$(docker inspect --format '{{.State.Status}}' tg-flow-bot 2>/dev/null || true)"
  [[ "$bot_state" == running ]] || fail 'The bot stopped. Check docker logs tg-flow-bot.'
  if curl --fail --silent --max-time 2 http://127.0.0.1:8081/health >/dev/null; then
    api_ready=true
    break
  fi
  sleep 1
done
[[ "$api_ready" == true ]] || fail 'The API did not respond within 60 seconds. Check docker logs tg-flow-bot.'

step 'Applying bot migrations'
(cd "$BOT_DIR" && make migrate)

if [[ ! -x "$FRONTEND_DIR/node_modules/.bin/vite" ]]; then
  step 'Installing frontend dependencies'
  (cd "$FRONTEND_DIR" && npm ci)
fi

step 'Starting the frontend: http://localhost:5173'
printf 'Stop the frontend with Ctrl+C. The database and bot containers will keep running.\n'
cd "$FRONTEND_DIR"
exec npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
