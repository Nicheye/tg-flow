import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


class TelegramAuthenticationError(ValueError):
    pass


def _validate_auth_date(auth_date: int, max_age_seconds: int, now: int | None = None) -> None:
    current_time = int(time.time()) if now is None else now
    if auth_date > current_time + 30:
        raise TelegramAuthenticationError("Telegram authentication date is in the future")
    if current_time - auth_date > max_age_seconds:
        raise TelegramAuthenticationError("Telegram authentication data has expired")


def validate_login_widget(
    data: dict[str, object],
    bot_token: str,
    max_age_seconds: int,
    now: int | None = None,
) -> dict[str, object]:
    if not bot_token:
        raise TelegramAuthenticationError("Telegram authentication is not configured")

    received_hash = str(data.get("hash", ""))
    if not received_hash:
        raise TelegramAuthenticationError("Telegram authentication hash is required")

    try:
        auth_date = int(data["auth_date"])
        telegram_user_id = int(data["id"])
    except (KeyError, TypeError, ValueError) as error:
        raise TelegramAuthenticationError("Invalid Telegram authentication payload") from error

    values = {
        key: value
        for key, value in data.items()
        if key != "hash" and value is not None and value != ""
    }
    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        raise TelegramAuthenticationError("Invalid Telegram authentication signature")

    _validate_auth_date(auth_date, max_age_seconds, now)
    values["id"] = telegram_user_id
    values["auth_date"] = auth_date
    return values


def validate_web_app_init_data(
    init_data: str,
    bot_token: str,
    max_age_seconds: int,
    now: int | None = None,
) -> dict[str, object]:
    if not bot_token:
        raise TelegramAuthenticationError("Telegram authentication is not configured")

    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    if len(pairs) != len({key for key, _ in pairs}):
        raise TelegramAuthenticationError("Duplicate Telegram authentication fields")
    values = dict(pairs)
    received_hash = values.pop("hash", "")
    if not received_hash:
        raise TelegramAuthenticationError("Telegram authentication hash is required")

    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise TelegramAuthenticationError("Invalid Telegram Mini App signature")

    try:
        auth_date = int(values["auth_date"])
        user = json.loads(values["user"])
        user["id"] = int(user["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise TelegramAuthenticationError("Invalid Telegram Mini App payload") from error

    _validate_auth_date(auth_date, max_age_seconds, now)
    return user
