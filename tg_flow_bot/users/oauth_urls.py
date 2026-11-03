from django.urls import path

from .oauth import (
    authorize,
    authorize_decision,
    introspect,
    register_client,
    revoke,
    telegram_session,
    web_session,
    token,
)

urlpatterns = [
    path("authorize", authorize, name="oauth_authorize"),
    path("authorize/decision", authorize_decision, name="oauth_authorize_decision"),
    path("session/telegram", telegram_session, name="oauth_telegram_session"),
    path("session/web", web_session, name="oauth_web_session"),
    path("register", register_client, name="oauth_register"),
    path("token", token, name="oauth_token"),
    path("introspect", introspect, name="oauth_introspect"),
    path("revoke", revoke, name="oauth_revoke"),
]
