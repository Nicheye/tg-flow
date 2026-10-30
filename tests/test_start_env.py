"""Tests for local environment setup without Docker or real credentials."""

import os
import pty
import select
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "start.sh"


def values(path):
    result = {}
    for line in path.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


class ConfigureEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = self.root / "storage/envs/dev/env.op"
        self.bot = self.root / "bot/envs/dev/env.op"
        self.frontend = self.root / "frontend/.env"
        for path in (self.storage, self.bot, self.frontend):
            path.parent.mkdir(parents=True, exist_ok=True)
        self.storage.write_text(
            "DB_NAME=shared_db\nDB_USER=shared_user\nDB_PASSWORD=shared_password\n"
            "DB_PORT=5433\nNETWORK=shared_net\n"
        )
        self.bot.write_text(
            "BOT_TOKEN=123456:test-token\nTELEGRAM_BOT_USERNAME=example_bot\n"
            "DJANGO_SECRET_KEY=test_signing_key\n"
        )

    def configure(self):
        command = (
            'source "$TEST_SCRIPT"; STORAGE_DIR="$TEST_ROOT/storage"; '
            'BOT_DIR="$TEST_ROOT/bot"; FRONTEND_DIR="$TEST_ROOT/frontend"; '
            'configure_env'
        )
        return subprocess.run(
            ["bash", "-c", command],
            env={**os.environ, "TEST_SCRIPT": str(SCRIPT), "TEST_ROOT": str(self.root)},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )

    def test_shared_database_values_are_copied_without_prompts(self):
        result = self.configure()
        self.assertEqual(result.returncode, 0, result.stderr)
        bot, front = values(self.bot), values(self.frontend)
        for suffix, expected in (("NAME", "shared_db"), ("USER", "shared_user"), ("PASSWORD", "shared_password")):
            self.assertEqual(bot[f"DB_{suffix}"], expected)
            self.assertEqual(bot[f"AUTH_DB_{suffix}"], expected)
        self.assertEqual(bot["NETWORK"], "shared_net")
        self.assertEqual(bot["DB_HOST"], "db")
        self.assertEqual(bot["DB_PORT"], "5432")  # Container port, not host port.
        self.assertEqual(front["VITE_BOT_USERNAME"], "example_bot")
        self.assertNotIn("shared_password", result.stdout + result.stderr)

        before = [p.read_bytes() for p in (self.storage, self.bot, self.frontend)]
        self.assertEqual(self.configure().returncode, 0)
        self.assertEqual(before, [p.read_bytes() for p in (self.storage, self.bot, self.frontend)])

    def test_fresh_interactive_setup_asks_for_database_values_only_once(self):
        self.storage.unlink()
        self.bot.unlink()
        master, slave = pty.openpty()
        command = (
            'source "$TEST_SCRIPT"; STORAGE_DIR="$TEST_ROOT/storage"; '
            'BOT_DIR="$TEST_ROOT/bot"; FRONTEND_DIR="$TEST_ROOT/frontend"; '
            'configure_env'
        )
        process = subprocess.Popen(
            ["bash", "-c", command],
            env={**os.environ, "TEST_SCRIPT": str(SCRIPT), "TEST_ROOT": str(self.root)},
            stdin=slave, stdout=slave, stderr=slave,
        )
        os.close(slave)
        output = b""
        deadline = time.monotonic() + 15
        try:
            while process.poll() is None and time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.5)
                if not ready:
                    continue
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                output += chunk
                if not chunk.endswith(b": "):
                    continue
                if b"(DB_PASSWORD)" in chunk:
                    answer = b"shared_password\n"
                elif b"(BOT_TOKEN)" in chunk:
                    answer = b"123456:test-token\n"
                elif b"(TELEGRAM_BOT_USERNAME)" in chunk:
                    answer = b"example_bot\n"
                elif b"(DJANGO_SECRET_KEY)" in chunk:
                    answer = b"test_signing_key\n"
                else:
                    answer = b"\n"
                time.sleep(0.03)  # Allow read -s to disable terminal echo.
                os.write(master, answer)
            if process.poll() is None:
                process.kill()
                self.fail("Interactive setup timed out")
            self.assertEqual(process.wait(), 0, output.decode(errors="replace"))
        finally:
            os.close(master)
            if process.poll() is None:
                process.kill()
                process.wait()
        for key in (b"DB_NAME", b"DB_USER", b"DB_PASSWORD"):
            self.assertEqual(output.count(b"(" + key + b")"), 1)
        self.assertNotIn(b"(AUTH_DB_NAME)", output)
        self.assertNotIn(b"shared_password", output)
        self.assertEqual(values(self.bot)["AUTH_DB_PASSWORD"], "shared_password")

    def test_existing_separate_auth_database_is_preserved(self):
        with self.bot.open("a") as f:
            f.write("AUTH_DB_ENGINE=postgresql\nAUTH_DB_NAME=auth_db\nAUTH_DB_USER=auth_user\n"
                    "AUTH_DB_PASSWORD=auth_password\nAUTH_DB_HOST=auth_host\nAUTH_DB_PORT=5432\n")
        result = self.configure()
        self.assertEqual(result.returncode, 0, result.stderr)
        bot = values(self.bot)
        self.assertEqual(bot["DB_NAME"], "shared_db")
        self.assertEqual(bot["AUTH_DB_NAME"], "auth_db")
        self.assertEqual(bot["AUTH_DB_PASSWORD"], "auth_password")
        self.assertEqual(bot["AUTH_DB_HOST"], "auth_host")

    def test_incomplete_separate_auth_database_is_not_filled_from_shared_database(self):
        with self.bot.open("a") as f:
            f.write("AUTH_DB_ENGINE=postgresql\nAUTH_DB_NAME=existing_auth_db\n")
        result = self.configure()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AUTH_DB_USER", result.stderr)
        bot = values(self.bot)
        self.assertEqual(bot["AUTH_DB_NAME"], "existing_auth_db")
        self.assertNotIn("AUTH_DB_USER", bot)

    def test_existing_bot_settings_are_not_overwritten(self):
        with self.bot.open("a") as f:
            f.write("DB_NAME=other_db\nDB_USER=other_user\nDB_PASSWORD=other_password\n")
        result = self.configure()
        self.assertEqual(result.returncode, 0, result.stderr)
        bot = values(self.bot)
        self.assertEqual(bot["DB_NAME"], "other_db")
        self.assertEqual(bot["DB_USER"], "other_user")
        self.assertEqual(bot["DB_PASSWORD"], "other_password")
        self.assertEqual(bot["AUTH_DB_NAME"], "other_db")


if __name__ == "__main__":
    unittest.main()
