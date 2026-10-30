from pathlib import Path

from django.db import connection
from django.db.migrations.executor import MigrationExecutor


def check_auth_migrations():
    database = connection.settings_dict
    if database["ENGINE"].endswith("sqlite3"):
        name = str(database["NAME"])
        if name != ":memory:" and not name.startswith("file:") and not Path(name).is_file():
            raise RuntimeError(
                "The configured SQLite auth database does not exist; verify AUTH_DB_NAME "
                "before creating a new database with python manage.py migrate."
            )
    try:
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
    except Exception as exc:
        raise RuntimeError(
            "Cannot inspect the configured Django auth database; verify AUTH_DB_* and connectivity."
        ) from exc
    if pending:
        raise RuntimeError(
            "Django auth database has missing migrations; verify AUTH_DB_* points to the "
            "intended database, back it up, and run python manage.py migrate."
        )
