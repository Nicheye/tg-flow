import hashlib
import hmac
import time

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


def signed_telegram_data(settings, **overrides):
    values = {
        "id": 555555555,
        "username": "telegramuser",
        "first_name": "Telegram",
        "last_name": "User",
        "auth_date": int(time.time()),
    }
    values.update(overrides)
    check_string = "\n".join(
        f"{key}={values[key]}"
        for key in sorted(values)
        if values[key] is not None and values[key] != ""
    )
    secret = hashlib.sha256(settings.TELEGRAM_BOT_TOKEN.encode()).digest()
    signature = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return {
        "tg_user_id": values["id"],
        "tg_username": values.get("username"),
        "first_name": values.get("first_name"),
        "last_name": values.get("last_name"),
        "auth_date": values["auth_date"],
        "hash": signature,
    }


def test_register_user_success(db, api_client, user_data):
    url = "/api/auth/register/"
    response = api_client.post(url, data=user_data, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    assert "user" in response.data
    assert "access" in response.data
    assert "refresh" in response.data
    assert response.data["user"]["tg_user_id"] == user_data["tg_user_id"]
    assert response.data["user"]["tg_username"] == user_data["tg_username"]

    assert User.objects.filter(tg_user_id=user_data["tg_user_id"]).exists()


def test_register_user_duplicate_tg_user_id(db, api_client, user, user_data):
    user_data["tg_user_id"] = user.tg_user_id
    url = "/api/auth/register/"
    response = api_client.post(url, data=user_data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_register_user_duplicate_email(db, api_client, user, user_data):
    user_data["email"] = user.email
    url = "/api/auth/register/"
    response = api_client.post(url, data=user_data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_login_success(db, api_client, user):
    url = "/api/auth/login/"
    data = {"tg_user_id": user.tg_user_id}
    response = api_client.post(url, data=data, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert "access" in response.data
    assert "refresh" in response.data
    assert "user" in response.data
    assert response.data["user"]["tg_user_id"] == user.tg_user_id


def test_login_nonexistent_user(db, api_client):
    url = "/api/auth/login/"
    data = {"tg_user_id": 999999999}
    response = api_client.post(url, data=data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_telegram_auth_success(db, api_client, settings):
    url = "/api/auth/telegram-auth/"
    data = signed_telegram_data(settings)
    response = api_client.post(url, data=data, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert "user" in response.data
    assert "access" in response.data
    assert "refresh" in response.data
    assert response.data["user"]["tg_user_id"] == 555555555


def test_telegram_auth_existing_user(db, api_client, user, settings):
    url = "/api/auth/telegram-auth/"
    data = signed_telegram_data(
        settings,
        id=user.tg_user_id,
        username="updated_username",
        first_name="Updated",
        last_name="Name",
    )
    response = api_client.post(url, data=data, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["user"]["tg_user_id"] == user.tg_user_id


def test_telegram_auth_rejects_invalid_signature(db, api_client, settings):
    data = signed_telegram_data(settings)
    data["hash"] = "0" * 64
    response = api_client.post("/api/auth/telegram-auth/", data=data, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not User.objects.filter(tg_user_id=data["tg_user_id"]).exists()


def test_telegram_auth_rejects_stale_payload(db, api_client, settings):
    data = signed_telegram_data(settings, auth_date=int(time.time()) - 601)
    response = api_client.post("/api/auth/telegram-auth/", data=data, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_refresh_token_success(db, api_client, user):
    refresh = RefreshToken.for_user(user)
    url = "/api/auth/token/refresh/"
    data = {"refresh": str(refresh)}
    response = api_client.post(url, data=data, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert "access" in response.data


def test_refresh_token_invalid(db, api_client):
    url = "/api/auth/token/refresh/"
    data = {"refresh": "invalid_token"}
    response = api_client.post(url, data=data, format="json")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_current_user_success(db, api_client, user):
    refresh = RefreshToken.for_user(user)
    access_token = str(refresh.access_token)

    url = "/api/auth/me/"
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["tg_user_id"] == user.tg_user_id
    assert response.data["email"] == user.email
    assert response.data["id"] == user.id


def test_get_current_user_unauthorized(db, api_client):
    url = "/api/auth/me/"
    response = api_client.get(url)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_current_user_invalid_token(db, api_client):
    url = "/api/auth/me/"
    api_client.credentials(HTTP_AUTHORIZATION="Bearer invalid_token")
    response = api_client.get(url)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
