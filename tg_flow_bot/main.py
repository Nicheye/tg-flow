import logging
from contextlib import asynccontextmanager

from asgiref.sync import sync_to_async
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.transport_security import TransportSecuritySettings
from telegram.ext import Application
from tortoise import Tortoise

from bot import create_bot_application
from config import settings
from database import TORTOISE_ORM
from mcp_server import ToolScopeMiddleware, create_mcp_server
from routers import mentions_router
from routers.chats import router as chats_router

if settings.AUTH_LOCAL_ASGI:
    from auth_project.asgi import application as django_app
else:
    django_app = None


class AuthRoutingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if django_app is not None and scope["type"] == "http" and (
            path.startswith(("/api/auth/", "/oauth/", "/admin/", "/static/"))
            or path in ("/api/auth", "/oauth", "/admin", "/.well-known/oauth-authorization-server")
        ):
            await django_app(scope, receive, send)
        else:
            await self.app(scope, receive, send)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# HTTPX logs full request URLs. Telegram's API places the bot token in its URL,
# so request-level HTTPX/HTTPCore logging must stay disabled in every environment.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Global bot instance
bot_application: Application | None = None
mcp, mcp_token_verifier = create_mcp_server()


def get_bot() -> Application:
    """Get the bot application instance"""
    if bot_application is None:
        raise RuntimeError("Bot not initialized")
    return bot_application


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot_application

    if settings.AUTH_LOCAL_ASGI:
        from auth_project.startup import check_auth_migrations

        await sync_to_async(check_auth_migrations, thread_sensitive=True)()

    # Init Tortoise ORM
    await Tortoise.init(config=TORTOISE_ORM)
    logger.info("Database connected")

    async with mcp.session_manager.run():
        # Start bot
        bot_application = create_bot_application()
        await bot_application.initialize()
        await bot_application.start()
        await bot_application.updater.start_polling(drop_pending_updates=True)
        logger.info("Bot started")

        yield

        # Shutdown
        await bot_application.updater.stop()
        await bot_application.stop()
        await bot_application.shutdown()
        bot_application = None
        logger.info("Bot stopped")

    await Tortoise.close_connections()
    logger.info("Database disconnected")


app = FastAPI(
    title="TG Flow Bot",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://tag-flow.ru",
        "https://www.tag-flow.ru",
        "https://bot.tag-flow.ru",
        "https://api.tag-flow.ru",
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(AuthRoutingMiddleware)

app.include_router(mentions_router, prefix="/api")
app.include_router(chats_router, prefix="/api")


@app.get("/")
async def root():
    return {"message": "TG Flow Bot API", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy", "bot": "running"}


@app.get("/.well-known/oauth-protected-resource/mcp")
async def oauth_protected_resource_metadata():
    return {
        "resource": settings.MCP_RESOURCE_URI,
        "authorization_servers": [settings.OAUTH_ISSUER],
        "scopes_supported": ["mentions:read", "mentions:write"],
        "bearer_methods_supported": ["header"],
    }


transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=settings.mcp_allowed_hosts,
    allowed_origins=settings.mcp_allowed_origins,
)
mcp_http_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    json_response=True,
    stateless_http=True,
    transport_security=transport_security,
    host="0.0.0.0",
)
mcp_http_app.add_middleware(
    ToolScopeMiddleware,
    verifier=mcp_token_verifier,
    transport_security=transport_security,
)
app.mount("/", mcp_http_app)
