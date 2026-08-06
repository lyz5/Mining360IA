from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from reports.models import KnowledgeSynonym


class Command(BaseCommand):
    help = "Audit Synonym Library normalization, duplicates and potential ambiguities."

    def handle(self, *args, **options):
        queryset = KnowledgeSynonym.objects.all()
        missing = queryset.filter(
            Q(normalized_value="") | Q(normalized_synonym_key="")
        ).count()
        duplicate_groups = queryset.values(
            "section_id", "entity_type", "language", "normalized_synonym_key"
        ).annotate(
            rows=Count("id"),
            canonical_terms=Count("canonical_term", distinct=True),
        ).filter(rows__gt=1)
        potential_ambiguities = duplicate_groups.filter(canonical_terms__gt=1)
        invalid = queryset.filter(
            Q(confidence__lt=0)
            | Q(confidence__gt=100)
            | Q(resolution_priority__lt=1)
            | Q(resolution_priority__gt=100)
        ).count()
        self.stdout.write(f"Total rows: {queryset.count()}")
        self.stdout.write(
            f"Migrated rows: {queryset.exclude(normalized_synonym_key='').count()}"
        )
        self.stdout.write(f"Duplicate normalized groups: {duplicate_groups.count()}")
        self.stdout.write(f"Missing normalized values: {missing}")
        self.stdout.write(
            f"Potential ambiguous groups: {potential_ambiguities.count()}"
        )
        self.stdout.write(f"Validation errors: {invalid}")
        for group in potential_ambiguities[:20]:
            self.stdout.write(
                "  - section={section_id}, type={entity_type}, language={language}, "
                "key={normalized_synonym_key}, canonical_terms={canonical_terms}".format(**group)
            )
