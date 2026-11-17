"""Bounded BODEFM release operations. Secret configuration arrives on stdin only.

This is an operator tool, never an HTTP endpoint. Application/account data is
not imported from the local preview. Rollback retains the additive auth tables.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['inspect', 'backup', 'snapshot', 'migrate', 'configure', 'verify', 'restore-config', 'probe', 'delivery-status'])
    parser.add_argument('--backup', required=True)
    args = parser.parse_args()
    if os.environ.get('COMPUTERNAME', '').upper() != 'BODEFM':
        raise RuntimeError('Unexpected deployment host.')
    if not re.fullmatch(r'D:\\Mining360Backups\\EmailSignIn_[0-9]{8}_[0-9]{6}_[0-9a-f]{8}', args.backup):
        raise RuntimeError('Unapproved backup path.')
    backup = Path(args.backup)
    if not backup.is_dir():
        raise RuntimeError('Backup folder is missing.')
    sys.path.insert(0, r'C:\Mining360\app')
    os.chdir(r'C:\Mining360\app')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Mining360IA.settings')
    import django
    django.setup()
    from django.conf import settings
    from django.db import connection, transaction
    from django.contrib.auth import get_user_model
    from django.core import serializers
    from reports.models import PlatformUser, SystemIntegrationConfig, SystemDatabaseConfig

    if connection.vendor != 'microsoft' or connection.settings_dict['NAME'] != 'Mining360App':
        raise RuntimeError('Unexpected application database.')
    with connection.cursor() as cursor:
        cursor.execute("SELECT CAST(SERVERPROPERTY('MachineName') AS nvarchar(128)),DB_NAME()")
        machine, database = cursor.fetchone()
    if machine.upper() != 'BODEFM' or database != 'Mining360App':
        raise RuntimeError('SQL Server identity did not match BODEFM.')

    def write(name, data):
        (backup / name).write_text(json.dumps(data, indent=2, default=str), encoding='utf-8')

    def controls():
        with connection.cursor() as cursor:
            cursor.execute('SELECT YEAR(business_date),division,lob,COUNT_BIG(*),SUM(revenue_eur) FROM bm_revenue_source_snapshot WHERE active=1 GROUP BY YEAR(business_date),division,lob ORDER BY YEAR(business_date),division,lob')
            financial = [list(row) for row in cursor.fetchall()]
            cursor.execute("SELECT COUNT(*) FROM sys.indexes WHERE object_id=OBJECT_ID('bm_revenue_source_snapshot') AND name='bo_active_revenue_cover_20261010' AND is_disabled=0")
            if cursor.fetchone()[0] != 1:
                raise RuntimeError('Revenue covering index is unavailable.')
            cursor.execute("SELECT precision,scale FROM sys.columns WHERE object_id=OBJECT_ID('bm_revenue_source_snapshot') AND name='revenue_eur'")
            if tuple(cursor.fetchone()) != (28, 10):
                raise RuntimeError('Revenue monetary precision changed.')
        users = get_user_model()
        access = [list(PlatformUser.objects.order_by('pk').values()),
                  list(users.objects.order_by('pk').values('pk', 'is_active', 'is_staff', 'is_superuser', 'password')),
                  list(users.groups.through.objects.order_by('pk').values()),
                  list(users.user_permissions.through.objects.order_by('pk').values())]
        integrations = list(SystemIntegrationConfig.objects.exclude(code='email-signin').order_by('pk').values())
        databases = list(SystemDatabaseConfig.objects.order_by('pk').values())
        return {'financial_signature': signature(financial), 'access_signature': signature(access),
                'other_connections_signature': signature([integrations, databases]),
                'revenue_covering_index': True, 'revenue_precision': 'numeric(28,10)'}

    if args.operation == 'inspect':
        owner = PlatformUser.objects.filter(email__iexact='papa.diagne@neemba.com', is_active=True, django_user__is_active=True)
        if owner.count() != 1:
            raise RuntimeError('The authorized test mailbox must match one active existing account.')
        with connection.cursor() as cursor:
            cursor.execute("SELECT name,size*8192 AS allocated_bytes,FILEPROPERTY(name,'SpaceUsed')*8192 AS used_bytes FROM sys.database_files")
            files = [list(row) for row in cursor.fetchall()]
            cursor.execute("SELECT app,name FROM django_migrations WHERE app='reports' AND name LIKE '0150%' ORDER BY name")
            migrations = [list(row) for row in cursor.fetchall()]
        result = dict(controls(), database_files=files, migration_0150=migrations, authorized_test_account_unique=True)
        write('preparation-controls.json', result)
    elif args.operation == 'backup':
        filename = backup / 'Mining360App_before_email_signin.bak'
        if filename.exists():
            raise RuntimeError('Do not overwrite an existing database backup.')
        raw = connection.connection.cursor()
        try:
            raw.execute('BACKUP DATABASE [Mining360App] TO DISK=? WITH COPY_ONLY, COMPRESSION, CHECKSUM', str(filename))
            while raw.nextset():
                pass
            raw.execute('RESTORE VERIFYONLY FROM DISK=? WITH CHECKSUM', str(filename))
            while raw.nextset():
                pass
        finally:
            raw.close()
        result = {'database': database, 'path': str(filename), 'bytes': filename.stat().st_size, 'copy_only': True, 'checksum_verified': True}
        write('database-backup.json', result)
    elif args.operation == 'snapshot':
        result = controls()
        write('before-controls.json', result)
    elif args.operation == 'migrate':
        from django.db.migrations.executor import MigrationExecutor
        executor = MigrationExecutor(connection)
        target = ('reports', '0150_email_code_signin')
        plan = executor.migration_plan([target])
        if [(migration.app_label, migration.name, reverse) for migration, reverse in plan] != [('reports', '0150_email_code_signin', False)]:
            raise RuntimeError('Only the single tested auth migration may be applied.')
        if {'email_login_challenge', 'email_login_rate_lock'} & set(connection.introspection.table_names()):
            raise RuntimeError('Unexpected existing email authentication tables.')
        executor.migrate([target])
        result = {'applied_migration': '0150_email_code_signin', 'unrelated_migrations_run': False}
    elif args.operation == 'configure':
        from reports.email_signin_delivery import validate_flow_url, configuration_ready
        from reports.system_configuration_service import save_integration, decrypt_secrets
        payload = json.loads(sys.stdin.read(20000))
        flow = str(payload['flow_url'])
        sender = str(payload['sender_email'])
        validate_flow_url(flow)
        if sender != 'papa.diagne@neemba.com' or '/workflows/201425da92cb47d8897d17703c6f2bea/' not in flow:
            raise RuntimeError('Unexpected approved corporate email transport.')
        with transaction.atomic():
            item = SystemIntegrationConfig.objects.select_for_update().filter(code='email-signin').first()
            saved = backup / 'email-integration.encrypted.json'
            if saved.exists():
                raise RuntimeError('The integration backup already exists; do not overwrite it.')
            saved.write_text(serializers.serialize('json', [item] if item else []), encoding='utf-8')
            if item and item.integration_type != 'Notification':
                raise RuntimeError('An unrelated integration already uses the reserved code.')
            item = item or SystemIntegrationConfig(code='email-signin', integration_type='Notification')
            item = save_integration(item, {'code': 'email-signin', 'name': 'Mining360 sign-in codes - Office 365 Outlook',
                'integration_type': 'Notification', 'is_active': True,
                'settings': {'transport': 'Power Automate', 'sender_email': sender, 'flow_url': flow}})
            if not configuration_ready() or decrypt_secrets(item)['flow_url'] != flow or flow in str(item.settings_json):
                raise RuntimeError('Encrypted corporate delivery configuration failed validation.')
        result = {'email_transport_configured': True, 'secret_encrypted_with_server_key': True, 'users_changed': False}
    elif args.operation == 'restore-config':
        saved = backup / 'email-integration.encrypted.json'
        if saved.exists():
            with transaction.atomic():
                records = list(serializers.deserialize('json', saved.read_text(encoding='utf-8')))
                if records:
                    if len(records) != 1 or records[0].object.code != 'email-signin':
                        raise RuntimeError('Unexpected integration rollback record.')
                    records[0].save()
                else:
                    SystemIntegrationConfig.objects.filter(code='email-signin', integration_type='Notification').delete()
        result = {'email_integration_restored': True, 'additive_auth_tables_retained': True}
    elif args.operation == 'verify':
        from reports.email_signin_delivery import configuration_ready
        from reports.email_signin_service import EmailCodeBackend, profile_for_email
        from django.test import Client
        result = controls()
        before = json.loads((backup / 'before-controls.json').read_text(encoding='utf-8'))
        if result != before:
            raise RuntimeError('Financial, access or other-connection controls changed.')
        if not settings.MINING360_EMAIL_CODE_LOGIN_ENABLED or not configuration_ready():
            raise RuntimeError('Email sign-in is not enabled and configured.')
        profile = profile_for_email('papa.diagne@neemba.com')
        if not profile or EmailCodeBackend().get_user(profile.django_user_id) != profile.django_user:
            raise RuntimeError('Existing account could not be resolved by the new backend.')
        client = Client(enforce_csrf_checks=True, HTTP_HOST='bodefm', HTTP_X_FORWARDED_PROTO='https')
        if client.get('/login/', secure=True).status_code != 302:
            raise RuntimeError('The login route did not redirect to email sign-in.')
        if client.get('/email-sign-in/', secure=True).status_code != 200 or client.get('/login/?method=password', secure=True).status_code != 200:
            raise RuntimeError('The email or legacy sign-in page is unavailable.')
        if client.get('/system-config/', secure=True).status_code != 302:
            raise RuntimeError('Anonymous Config access was not rejected.')
        result.update(email_signin_ready=True, legacy_signin_available=True, anonymous_config_denied=True)
        write('after-controls.json', result)
    elif args.operation == 'delivery-status':
        from reports.email_signin_models import EmailLoginChallenge
        item = EmailLoginChallenge.objects.order_by('-created_at').first()
        result = {'delivery_status': item.delivery_status if item else 'none'}
    else:
        # QA uses normal CSRF/session/OTP views. It captures its own random code
        # in memory only, delegates the real send, then consumes and logs out.
        import time
        from unittest.mock import patch
        from django.test import Client
        from reports import email_signin_service as service
        from reports.email_signin_models import EmailLoginChallenge
        from django.contrib.sessions.models import Session
        original = service.queue_delivery
        captured = {}

        def deliver(challenge_id, address, code, user_id):
            captured.update(challenge_id=challenge_id, code=code, user_id=user_id)
            return original(challenge_id, address, code, user_id)

        client = Client(enforce_csrf_checks=True, HTTP_HOST='bodefm', HTTP_X_FORWARDED_PROTO='https')
        try:
            response = client.get('/email-sign-in/', secure=True)
            token = client.cookies[settings.CSRF_COOKIE_NAME].value
            with patch.object(service, 'queue_delivery', deliver):
                response = client.post('/email-sign-in/', {'email': 'papa.diagne@neemba.com', 'csrfmiddlewaretoken': token}, secure=True)
            if response.status_code != 302 or not captured:
                raise RuntimeError('The real email QA request did not issue a challenge.')
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                challenge = EmailLoginChallenge.objects.get(pk=captured['challenge_id'])
                if challenge.delivery_status != 'pending':
                    break
                time.sleep(.5)
            if challenge.delivery_status != 'issued':
                raise RuntimeError('Real Outlook email delivery failed.')
            response = client.post('/email-sign-in/', {'action': 'verify', 'code': captured['code'], 'remember': 'on', 'csrfmiddlewaretoken': token}, secure=True)
            if response.status_code != 302 or int(client.session.get('_auth_user_id', 0)) != captured['user_id']:
                raise RuntimeError('The genuine one-time code did not authenticate the existing user.')
            challenge.refresh_from_db()
            if not challenge.consumed_at or challenge.code_hash:
                raise RuntimeError('The one-time code was not securely consumed.')
            result = {'real_outlook_send_confirmed': True, 'existing_user_authenticated': True, 'code_consumed': True,
                      'remember_days': client.session.get_expiry_age() / 86400, 'inbox_receipt_independently_confirmed': False}
            write('real-email-probe.json', result)
        finally:
            if client.session.session_key:
                Session.objects.filter(session_key=client.session.session_key).delete()
            captured.clear()
    print(json.dumps(result, default=str), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # No exception text/traceback: provider URLs, accounts and code values
        # must never leak into deployment or process logs.
        import traceback
        location = traceback.extract_tb(error.__traceback__)[-1]
        print(json.dumps({'status': 'Failed', 'error_type': type(error).__name__,
                          'location': f'{Path(location.filename).name}:{location.lineno}'}), flush=True)
        raise SystemExit(1) from None
