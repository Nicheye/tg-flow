from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "tg_user_id",
        "tg_username",
        "email",
        "full_name",
        "is_staff",
        "is_active",
        "created_at",
    )
    list_filter = ("is_staff", "is_active", "is_superuser", "created_at")
    search_fields = ("tg_user_id", "tg_username", "email", "full_name")
    ordering = ("-created_at",)

    fieldsets = BaseUserAdmin.fieldsets + (
        ("Telegram Info", {"fields": ("tg_user_id", "tg_username")}),
        ("Additional Info", {"fields": ("full_name", "created_at", "updated_at")}),
    )

    readonly_fields = ("created_at", "updated_at")
