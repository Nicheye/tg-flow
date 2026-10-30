from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import CustomTokenObtainPairView, RegisterView, TelegramAuthView, get_current_user

urlpatterns = [
    path("telegram-auth/", TelegramAuthView.as_view(), name="telegram_auth"),
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", CustomTokenObtainPairView.as_view(), name="login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("me/", get_current_user, name="current_user"),
]
