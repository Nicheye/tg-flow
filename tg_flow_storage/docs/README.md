# TG Flow - Storage Microservice

A PostgreSQL database microservice for the TG Flow project.

For a new self-hosted installation, start from [env.op.example](../envs/prod/env.op.example). Match its database name, user, password, and network to the bot/auth configuration when using a shared database. The current Compose file publishes PostgreSQL on all host interfaces; a public VPS needs a private deployment configuration or effective network restrictions. Existing volumes retain their initialization settings when env values change.

## Quick Start

### Using Docker Compose with Makefile

**Important:** `ENV_FILE` variable is **required** for `up`, `restart`, and `shell` commands.

Start the PostgreSQL database:

```bash
ENV_FILE=envs/dev/env.op make build
ENV_FILE=envs/dev/env.op make up
```

Or combine commands:
```bash
ENV_FILE=envs/dev/env.op make build up
```

Stop the database:

```bash
make down
```

Restart the database:

```bash
ENV_FILE=envs/dev/env.op make restart
```

Stop and remove volumes (⚠️ **WARNING**: This will delete all data):

```bash
make clean
```

### Database Connection

The database connection details are configured via environment variables in your `env.op` file:
- **Host**: `localhost` (or `DB_HOST` from env file)
- **Port**: `5432` (or `DB_PORT` from env file)
- **Database**: `DB_NAME` from env file
- **User**: `DB_USER` from env file
- **Password**: `DB_PASSWORD` from env file

### Environment Variables

Environment configuration files are located in the `envs/` directory:

- `envs/dev/env.op` - Development environment variables
- `envs/prod/env.op` - Production environment variables

**Required variables in env.op:**
- `DB_NAME` - Database name
- `DB_USER` - Database user
- `DB_PASSWORD` - Database password
- `DB_PORT` - Database port (default: 5432)

## Docker Commands

### Using Makefile (Recommended)

**Basic commands:**
- Pull/update images: `make build` (ENV_FILE not required)
- Start database: `ENV_FILE=envs/dev/env.op make up` (ENV_FILE **required**)
- Stop database: `make down` (ENV_FILE not required)
- Restart database: `ENV_FILE=envs/dev/env.op make restart` (ENV_FILE **required**)
- Clean (remove volumes): `make clean` (ENV_FILE not required)
- View logs: `make logs` (ENV_FILE not required)
- Check status: `make ps` (ENV_FILE not required)
- Access shell: `ENV_FILE=envs/dev/env.op make shell` (ENV_FILE **required**)
- Check health: `make health` (ENV_FILE not required)

**Note:** `ENV_FILE` is **required** for `up`, `restart`, and `shell` commands. If omitted, these commands will show an error. Other commands don't require `ENV_FILE` as they operate on existing containers.

### Using Docker Compose directly

You can also use docker-compose directly, but you need to export environment variables first:

```bash
export $(cat envs/dev/env.op | xargs)
docker compose up -d
```

## Project Structure

```
tg_flow_storage/
├── docker-compose.yml    # Docker Compose configuration with PostgreSQL
├── Makefile             # Makefile with ENV_FILE support
├── envs/                 # Environment configuration files
│   ├── dev/
│   │   └── env.op       # Development environment variables
│   └── prod/
│       └── env.op       # Production environment variables
└── docs/                 # Documentation
    └── README.md        # This file
```

## Technology Stack

- PostgreSQL 16 (Alpine Linux)
- Docker & Docker Compose

## Architecture

This is a **database microservice** designed to work in a microservices architecture:
- Provides a PostgreSQL database instance
- Can be shared by multiple microservices (auth, bot, etc.)
- Database credentials are configured via environment variables
- Data is persisted in Docker volumes

## Security Notes

⚠️ **Important**: The default credentials in this setup are for development only. For production:
- Change the default password
- Use environment variables or secrets management
- Restrict network access
- Enable SSL/TLS connections

