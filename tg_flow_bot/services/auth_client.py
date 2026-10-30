import hashlib
import hmac
import time

import httpx

from config import settings
from schemas import AuthResponse, TelegramUser
from services.auth_transport import auth_http_client, auth_url


class AuthClient:
    def __init__(self):
        self.base_url = settings.AUTH_API_URL
        self.timeout = settings.AUTH_API_TIMEOUT

    async def register(self, user: TelegramUser) -> AuthResponse | None:
        """
        Register or authenticate a Telegram user via Auth API.

        POST /api/auth/telegram-auth/
        """
        # Generate hash for telegram auth (simplified for internal use)
        auth_date = int(time.time())
        payload = {
            "tg_user_id": user.tg_user_id,
            "tg_username": user.tg_username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "auth_date": auth_date,
        }
        telegram_payload = {
            "id": user.tg_user_id,
            "username": user.tg_username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "auth_date": auth_date,
        }
        payload["hash"] = self._generate_hash(telegram_payload)

        try:
            async with auth_http_client() as client:
                response = await client.post(
                    auth_url(f"{self.base_url}/telegram-auth/", "/api/auth/telegram-auth/"),
                    json=payload,
                )

                if response.status_code == 200:
                    data = response.json()
                    return AuthResponse(
                        user_id=data["user"]["id"],
                        access=data["access"],
                        refresh=data["refresh"],
                        created=data.get("created", True),
                    )
                else:
                    print(f"Auth API error: {response.status_code} - {response.text}")
                    return None

        except httpx.RequestError as e:
            print(f"Auth API connection error: {e}")
            return None

    def _generate_hash(self, values: dict[str, object]) -> str:
        data_check_string = "\n".join(
            f"{key}={values[key]}"
            for key in sorted(values)
            if values[key] is not None and values[key] != ""
        )
        secret_key = hashlib.sha256(settings.BOT_TOKEN.encode()).digest()
        return hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()


auth_client = AuthClient()
