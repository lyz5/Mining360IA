import uuid
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    # 0148/0149 are retained in some deployed SQL migration ledgers; this branch
    # has the exported 0147 source graph. No existing migration is overwritten.
    dependencies = [('reports', '0147_remove_openai_usage'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name='EmailLoginRateLock',
            fields=[
                ('key', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('window_start', models.DateTimeField(default=django.utils.timezone.now)),
                ('last_request_at', models.DateTimeField(null=True)),
                ('requests', models.PositiveIntegerField(default=0)),
            ], options={'db_table': 'email_login_rate_lock'},
        ),
        migrations.CreateModel(
            name='EmailLoginChallenge',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('email_digest', models.CharField(db_index=True, max_length=64)),
                ('session_digest', models.CharField(max_length=64)),
                ('code_hash', models.CharField(max_length=255)),
                ('created_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('attempts', models.PositiveSmallIntegerField(default=0)),
                ('consumed_at', models.DateTimeField(null=True)),
                ('delivery_status', models.CharField(default='pending', max_length=16)),
                ('user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ], options={'db_table': 'email_login_challenge'},
        ),
    ]
