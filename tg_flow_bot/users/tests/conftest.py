import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from .constants import USER_REGISTRATION_DATA

User = get_user_model()


@pytest.fixture(autouse=True)
def telegram_auth_settings(settings):
    settings.DEBUG = True
    settings.TELEGRAM_BOT_TOKEN = "123456:test-bot-token"
    settings.TELEGRAM_AUTH_MAX_AGE_SECONDS = 600


@pytest.fixture
def api_client():
    """Фикстура для создания APIClient."""
    return APIClient()


@pytest.fixture
def user(db):
    """Фикстура для создания тестового пользователя."""
    user = User.objects.create_user(
        username="987654321",
        tg_user_id=987654321,
        tg_username="testuser",
        email="test@example.com",
        full_name="Test User",
    )
    user.set_unusable_password()
    user.save()
    return user


@pytest.fixture
def user_data():
    """Фикстура с данными для регистрации пользователя.

    Возвращает копию словаря, чтобы модификации в одном тесте
    не влияли на другие тесты.
    """
    return USER_REGISTRATION_DATA.copy()


@pytest.fixture
def admin_user(db):
    """Фикстура для создания администратора."""
    return User.objects.create_superuser(
        username="111111111",
        tg_user_id=111111111,
        tg_username="admin",
        email="admin@example.com",
    )
