from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from reports.email_signin_models import EmailLoginChallenge, EmailLoginRateLock


class Command(BaseCommand):
    help = 'Remove expired email sign-in challenges and stale rate buckets older than three days.'

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=3)
        counts = []
        for model, field in ((EmailLoginChallenge, 'expires_at'), (EmailLoginRateLock, 'window_start')):
            count = 0
            while True:
                ids = list(model.objects.filter(**{field+'__lt': cutoff}).order_by('pk').values_list('pk', flat=True)[:500])
                if not ids:
                    break
                deleted, _ = model.objects.filter(pk__in=ids).delete()
                count += deleted
            counts.append(count)
        self.stdout.write(f'Expired challenges removed: {counts[0]}; stale rate buckets removed: {counts[1]}.')
