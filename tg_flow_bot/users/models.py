import uuid

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    def _create_user(self, tg_user_id, password, **extra_fields):
        if not tg_user_id:
            raise ValueError("The given tg_user_id must be set")
        if not extra_fields.get("username"):
            tg_username = extra_fields.get("tg_username")
            extra_fields["username"] = tg_username or str(tg_user_id)
        user = self.model(tg_user_id=tg_user_id, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, tg_user_id, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(tg_user_id, password, **extra_fields)

    def create_superuser(self, tg_user_id, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(tg_user_id, password, **extra_fields)


class User(AbstractUser):
    username = models.CharField(
        "username",
        max_length=150,
        unique=True,
        blank=True,
        null=True,
        help_text="Username (optional; defaults to tg_username)",
    )

    tg_user_id = models.BigIntegerField(
        "telegram user id",
        unique=True,
        blank=False,
        null=False,
        help_text="Telegram user ID for authentication",
    )

    tg_username = models.CharField(
        "telegram username",
        max_length=150,
        unique=True,
        blank=True,
        null=True,
        help_text="Telegram username (optional)",
    )

    email = models.EmailField(
        "email address",
        unique=True,
        blank=True,
        null=True,
        help_text="User email address (optional)",
    )

    full_name = models.CharField(
        "full name", max_length=255, blank=True, null=True, help_text="User's full name"
    )

    created_at = models.DateTimeField(
        "created at", auto_now_add=True, help_text="User creation date"
    )

    updated_at = models.DateTimeField(
        "updated at", auto_now=True, help_text="Date of the last update"
    )

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"
        db_table = "users"
        ordering = ["-created_at"]

    USERNAME_FIELD = "tg_user_id"
    REQUIRED_FIELDS = []
    objects = UserManager()

    def __str__(self):
        return f"{self.tg_username or 'No username'} ({self.tg_user_id})"


class OAuthClient(models.Model):
    client_id = models.CharField(max_length=255, unique=True)
    client_name = models.CharField(max_length=255)
    redirect_uris = models.JSONField(default=list)
    grant_types = models.JSONField(default=list)
    response_types = models.JSONField(default=list)
    token_endpoint_auth_method = models.CharField(max_length=50, default="none")
    client_secret_digest = models.CharField(max_length=64, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "oauth_clients"

    def __str__(self):
        return f"{self.client_name} ({self.client_id})"


class OAuthGrant(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="oauth_grants")
    client = models.ForeignKey(OAuthClient, on_delete=models.CASCADE, related_name="grants")
    scopes = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "oauth_grants"
        constraints = [
            models.UniqueConstraint(fields=("user", "client"), name="unique_oauth_user_client")
        ]


class OAuthAuthorizationCode(models.Model):
    code_digest = models.CharField(max_length=64, unique=True)
    client = models.ForeignKey(OAuthClient, on_delete=models.CASCADE, related_name="codes")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="oauth_codes")
    redirect_uri = models.URLField(max_length=2048)
    resource = models.URLField(max_length=2048)
    scope = models.TextField()
    code_challenge = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "oauth_authorization_codes"


class OAuthAccessToken(models.Model):
    token_digest = models.CharField(max_length=64, unique=True)
    family_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    client = models.ForeignKey(OAuthClient, on_delete=models.CASCADE, related_name="access_tokens")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="oauth_access_tokens")
    resource = models.URLField(max_length=2048)
    scope = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "oauth_access_tokens"


class OAuthRefreshToken(models.Model):
    token_digest = models.CharField(max_length=64, unique=True)
    family_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    client = models.ForeignKey(OAuthClient, on_delete=models.CASCADE, related_name="refresh_tokens")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="oauth_refresh_tokens")
    resource = models.URLField(max_length=2048)
    scope = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(blank=True, null=True)
    revoked_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "oauth_refresh_tokens"
