from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("users", "0002_oauthclient_alter_user_managers_and_more")]

    operations = [
        migrations.AlterField(
            model_name="user", name="created_at",
            field=models.DateTimeField(auto_now_add=True, help_text="User creation date", verbose_name="created at"),
        ),
        migrations.AlterField(
            model_name="user", name="email",
            field=models.EmailField(blank=True, help_text="User email address (optional)", max_length=254, null=True, unique=True, verbose_name="email address"),
        ),
        migrations.AlterField(
            model_name="user", name="full_name",
            field=models.CharField(blank=True, help_text="User's full name", max_length=255, null=True, verbose_name="full name"),
        ),
        migrations.AlterField(
            model_name="user", name="tg_user_id",
            field=models.BigIntegerField(help_text="Telegram user ID for authentication", unique=True, verbose_name="telegram user id"),
        ),
        migrations.AlterField(
            model_name="user", name="tg_username",
            field=models.CharField(blank=True, help_text="Telegram username (optional)", max_length=150, null=True, unique=True, verbose_name="telegram username"),
        ),
        migrations.AlterField(
            model_name="user", name="updated_at",
            field=models.DateTimeField(auto_now=True, help_text="Date of the last update", verbose_name="updated at"),
        ),
        migrations.AlterField(
            model_name="user", name="username",
            field=models.CharField(blank=True, help_text="Username (optional; defaults to tg_username)", max_length=150, null=True, unique=True, verbose_name="username"),
        ),
    ]
