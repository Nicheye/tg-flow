import os

# Tests must never connect to a developer or production auth database.
os.environ["AUTH_DB_ENGINE"] = "sqlite3"
os.environ["AUTH_DB_NAME"] = ":memory:"

from auth_project.settings import *  # noqa: F403, E402
