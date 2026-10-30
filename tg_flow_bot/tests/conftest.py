from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from tortoise import Tortoise

from models import Chat, MentionedMessage, UserChatSubscription
from routers.chats import router as chats_router
from routers.mentions import router as mentions_router
from services.security import TokenPayload, get_current_user


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="function")
async def db():
    """Initialize test database"""
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["models"]},
    )
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


@pytest.fixture
async def chat(db):
    """Create test chat"""
    return await Chat.create(
        id=-1001234567890,
        chat_type="supergroup",
        title="Test Group",
        username="testgroup",
    )


@pytest.fixture
async def another_chat(db):
    """Create another test chat"""
    return await Chat.create(
        id=-1009876543210,
        chat_type="supergroup",
        title="Another Group",
        username="anothergroup",
    )


@pytest.fixture
async def subscription(db, chat):
    """Create test subscription"""
    return await UserChatSubscription.create(
        user_id=1,
        chat=chat,
        tg_user_id=123456789,
        tg_username="testuser",
    )


@pytest.fixture
async def mentions(db, chat, subscription):
    """Create multiple test mentions"""
    base_date = datetime.now()
    result = []
    for i in range(5):
        mention = await MentionedMessage.create(
            user_id=1,  # matches auth_user.user_id
            chat=chat,
            subscription=subscription,
            message_id=1000 + i,
            from_user_id=111111,
            from_username="sender",
            text=f"Test mention {i} @testuser",
            message_date=base_date - timedelta(hours=i),
        )
        result.append(mention)
    return result


@pytest.fixture
async def mentions_in_another_chat(db, another_chat):
    """Create mentions in another chat"""
    base_date = datetime.now()
    result = []
    for i in range(3):
        mention = await MentionedMessage.create(
            user_id=1,  # matches auth_user.user_id
            chat=another_chat,
            subscription=None,
            message_id=2000 + i,
            from_user_id=222222,
            from_username="othersender",
            text=f"Another chat mention {i} @testuser",
            message_date=base_date - timedelta(hours=i + 10),
        )
        result.append(mention)
    return result


# === API Client ===


@pytest.fixture
def auth_user():
    """Mock authenticated user (TokenPayload for API)"""
    return TokenPayload(
        user_id=1,
        tg_user_id=123456789,
        scopes=["mentions:read", "mentions:write"],
    )


@pytest.fixture
async def client(db, auth_user):
    """Async HTTP client with auth"""
    app = FastAPI()
    app.include_router(mentions_router, prefix="/api")
    app.include_router(chats_router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: auth_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def client_no_auth(db):
    """Async HTTP client without auth"""
    app = FastAPI()
    app.include_router(mentions_router, prefix="/api")
    app.include_router(chats_router, prefix="/api")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# === Telegram Bot Mocks ===


@pytest.fixture
def mock_user():
    """Mock Telegram user"""
    user = MagicMock()
    user.id = 123456789
    user.username = "testuser"
    user.first_name = "Test"
    user.last_name = "User"
    return user


@pytest.fixture
def mock_context():
    """Mock Telegram Context"""
    context = MagicMock()
    context.user_data = {}
    context.bot = MagicMock()
    full_chat = MagicMock()
    full_chat.title = "Test Group"
    full_chat.username = "testgroup"
    full_chat.photo = None
    context.bot.get_chat = AsyncMock(return_value=full_chat)
    return context


@pytest.fixture
def make_update():
    """Factory for creating mock updates"""

    def _make_update(
        text: str,
        chat_id: int = -1001234567890,
        chat_type: str = "supergroup",
        mentions: list[tuple[int, int, str]] | None = None,
        from_user_id: int = 111111,
        from_username: str = "sender",
    ):
        message = MagicMock()
        message.text = text
        message.message_id = 12345
        message.date = datetime.now()
        message.from_user.id = from_user_id
        message.from_user.username = from_username
        message.reply_text = AsyncMock()

        if mentions:
            entities = []
            for offset, length, entity_type in mentions:
                entity = MagicMock()
                entity.type = entity_type
                entity.offset = offset
                entity.length = length
                if entity_type == "text_mention":
                    entity.user.id = 999999
                entities.append(entity)
            message.entities = entities
        else:
            message.entities = None

        update = MagicMock()
        update.message = message
        update.effective_message = message
        update.effective_chat.type = chat_type
        update.effective_chat.id = chat_id
        update.effective_chat.title = "Test Group"
        update.effective_chat.username = "testgroup"
        update.effective_user = MagicMock()
        update.effective_user.id = from_user_id
        update.effective_user.username = from_username
        update.effective_user.first_name = "Sender"
        update.effective_user.last_name = "User"

        return update

    return _make_update
