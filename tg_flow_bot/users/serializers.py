from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .telegram import (
    TelegramAuthenticationError,
    validate_login_widget,
    validate_web_app_init_data,
)

User = get_user_model()


class TelegramAuthSerializer(serializers.Serializer):
    tg_user_id = serializers.IntegerField(required=False)
    tg_username = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    first_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    last_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    photo_url = serializers.URLField(required=False, allow_blank=True, allow_null=True)
    auth_date = serializers.IntegerField(required=False)
    hash = serializers.CharField(required=False)
    init_data = serializers.CharField(required=False, write_only=True)

    def validate(self, attrs):
        try:
            if attrs.get("init_data"):
                verified = validate_web_app_init_data(
                    attrs["init_data"],
                    settings.TELEGRAM_BOT_TOKEN,
                    settings.TELEGRAM_AUTH_MAX_AGE_SECONDS,
                )
            else:
                login_payload = {
                    "id": attrs.get("tg_user_id"),
                    "username": attrs.get("tg_username"),
                    "first_name": attrs.get("first_name"),
                    "last_name": attrs.get("last_name"),
                    "photo_url": attrs.get("photo_url"),
                    "auth_date": attrs.get("auth_date"),
                    "hash": attrs.get("hash"),
                }
                verified = validate_login_widget(
                    login_payload,
                    settings.TELEGRAM_BOT_TOKEN,
                    settings.TELEGRAM_AUTH_MAX_AGE_SECONDS,
                )
        except TelegramAuthenticationError as error:
            raise serializers.ValidationError(str(error)) from error

        tg_user_id = verified["id"]
        tg_username = verified.get("username")
        first_name = verified.get("first_name", "")
        last_name = verified.get("last_name", "")

        full_name = f"{first_name} {last_name}".strip() if first_name or last_name else None

        user, created = User.objects.get_or_create(
            tg_user_id=tg_user_id,
            defaults={
                "username": str(tg_user_id),
                "tg_username": tg_username or None,
                "full_name": full_name,
                "email": f"tg_{tg_user_id}@telegram.local",
            },
        )
        if created:
            user.set_unusable_password()
            user.save()

        if not created:
            if tg_username:
                user.tg_username = tg_username
            if full_name:
                user.full_name = full_name
            user.save()

        attrs["user"] = user
        attrs["created"] = created
        return attrs


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tg_user_id"] = serializers.IntegerField()
        if "username" in self.fields:
            del self.fields["username"]
        if "password" in self.fields:
            del self.fields["password"]

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        return token

    def validate(self, attrs):
        tg_user_id = attrs.pop("tg_user_id", None)
        if tg_user_id:
            try:
                user = User.objects.get(tg_user_id=tg_user_id)
                refresh = self.get_token(user)
                return {
                    "refresh": str(refresh),
                    "access": str(refresh.access_token),
                }
            except User.DoesNotExist as err:
                raise serializers.ValidationError("User not found") from err
        raise serializers.ValidationError("tg_user_id is required")


class UserRegistrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("tg_user_id", "tg_username", "email", "full_name")

    def create(self, validated_data):
        tg_user_id = validated_data.get("tg_user_id")
        if not validated_data.get("email"):
            validated_data["email"] = f"tg_{tg_user_id}@telegram.local"
        username = str(tg_user_id)
        user = User.objects.create_user(username=username, **validated_data)
        user.set_unusable_password()
        user.save()
        return user


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id",
            "tg_user_id",
            "tg_username",
            "email",
            "full_name",
            "created_at",
            "is_active",
        )
        read_only_fields = ("id", "created_at", "is_active")
