import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Credentials:
    access_token: str
    refresh_token: str
    expires_at: int
    scope: str
    resource: str
    issuer: str
    client_id: str
    token_endpoint: str
    revocation_endpoint: str | None
    api_url: str


class CredentialStore:
    def __init__(self, path: Path | None = None):
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self.path = path or config_home / "tgflow" / "credentials.json"

    def load(self) -> Credentials | None:
        try:
            data = json.loads(self.path.read_text())
            return Credentials(**data)
        except FileNotFoundError:
            return None
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Credential file is invalid: {self.path}") from error

    def save(self, credentials: Credentials) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        handle, temporary_path = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=".credentials-",
            text=True,
        )
        try:
            with os.fdopen(handle, "w") as temporary_file:
                json.dump(asdict(credentials), temporary_file, indent=2)
                temporary_file.write("\n")
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, self.path)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
