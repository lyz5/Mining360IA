from django.db import migrations, models


def seed_existing_admin_roles(apps, schema_editor):
    PlatformUser = apps.get_model("reports", "PlatformUser")
    User = apps.get_model("auth", "User")

    PlatformUser.objects.filter(is_platform_admin=True).update(
        can_access_reporting=True,
        can_access_ai=True,
        can_access_data=True,
        can_access_sources=True,
    )

    djibril = User.objects.filter(username="djibril").first()
    if djibril:
        PlatformUser.objects.update_or_create(
            user_principal_name="djibril@local.mining360ia",
            defaults={
                "azure_ad_id": "local-djibril",
                "email": "djibril@local.mining360ia",
                "display_name": "Djibril",
                "job_title": "Super Admin",
                "is_active": True,
                "is_platform_admin": True,
                "can_access_reporting": True,
                "can_access_ai": True,
                "can_access_data": True,
                "can_access_sources": True,
                "django_user": djibril,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0013_databrowser_identifier_visibility"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformuser",
            name="can_access_ai",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="platformuser",
            name="can_access_data",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="platformuser",
            name="can_access_reporting",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="platformuser",
            name="can_access_sources",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(seed_existing_admin_roles, migrations.RunPython.noop),
    ]
