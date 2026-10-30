from urllib.parse import quote

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    # Bot settings
    BOT_TOKEN: str = ""
    WEBHOOK_URL: str | None = None
    WEBHOOK_PATH: str = "/webhook"

    # API settings
    AUTH_API_URL: str = "http://localhost:8081/api/auth"
    AUTH_API_TIMEOUT: int = 5
    OAUTH_ISSUER: str = "http://localhost:8081/"
    OAUTH_INTROSPECTION_URL: str = "http://localhost:8081/oauth/introspect"
    AUTH_LOCAL_ASGI: bool = True
    MCP_RESOURCE_URI: str = "http://localhost:8081/mcp"
    MCP_INTROSPECTION_CLIENT_ID: str = "tg-flow-mcp"
    MCP_INTROSPECTION_CLIENT_SECRET: str = "development-only-introspection-secret"
    MCP_ALLOWED_HOSTS: str = "localhost:*,127.0.0.1:*"
    MCP_ALLOWED_ORIGINS: str = "http://localhost:*,http://127.0.0.1:*"

    # Database settings
    DB_ENGINE: str = "postgresql"
    DB_HOST: str = "localhost"
    DB_NAME: str = "tg_flow"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = ""
    DB_PORT: int = 5432

    # Network
    NETWORK: str = "flow_net"

    # Debug
    DEBUG: bool = True

    @field_validator("OAUTH_ISSUER")
    @classmethod
    def canonicalize_issuer(cls, value: str) -> str:
        return value.rstrip("/") + "/"

    @field_validator("MCP_RESOURCE_URI")
    @classmethod
    def canonicalize_resource(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def database_url(self) -> str:
        user = quote(self.DB_USER, safe="")
        password = quote(self.DB_PASSWORD, safe="")
        database = quote(self.DB_NAME, safe="")
        return f"asyncpg://{user}:{password}@{self.DB_HOST}:{self.DB_PORT}/{database}"

    @property
    def mcp_allowed_hosts(self) -> list[str]:
        return [value.strip() for value in self.MCP_ALLOWED_HOSTS.split(",") if value.strip()]

    @property
    def mcp_allowed_origins(self) -> list[str]:
        return [value.strip() for value in self.MCP_ALLOWED_ORIGINS.split(",") if value.strip()]

    @model_validator(mode="after")
    def validate_production_secrets(self):
        if ({"AUTH_API_URL", "OAUTH_INTROSPECTION_URL"} & self.model_fields_set
                and "AUTH_LOCAL_ASGI" not in self.model_fields_set):
            raise ValueError(
                "Legacy auth URLs are configured: explicitly set AUTH_LOCAL_ASGI=True "
                "for integrated auth or False to keep remote calls"
            )
        if not self.AUTH_LOCAL_ASGI:
            missing_urls = {"AUTH_API_URL", "OAUTH_INTROSPECTION_URL"} - self.model_fields_set
            if missing_urls:
                raise ValueError(
                    "Remote auth requires explicit URLs: " + ", ".join(sorted(missing_urls))
                )
        if not self.DEBUG:
            required = {
                "BOT_TOKEN": self.BOT_TOKEN,
                "DB_PASSWORD": self.DB_PASSWORD,
                "MCP_INTROSPECTION_CLIENT_SECRET": self.MCP_INTROSPECTION_CLIENT_SECRET,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(f"Missing production settings: {', '.join(missing)}")
            if (
                self.MCP_INTROSPECTION_CLIENT_SECRET == "development-only-introspection-secret"
                or len(self.MCP_INTROSPECTION_CLIENT_SECRET) < 32
            ):
                raise ValueError(
                    "MCP_INTROSPECTION_CLIENT_SECRET must be at least 32 characters and changed in production"
                )
            if not self.OAUTH_ISSUER.startswith("https://") or not self.MCP_RESOURCE_URI.startswith(
                "https://"
            ):
                raise ValueError("OAUTH_ISSUER and MCP_RESOURCE_URI must use HTTPS in production")
        return self


settings = Settings()
