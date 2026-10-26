# Resolves the local development graph after the independent BODEFM-safe
# Downtime Checking migration branched from the BODEFM 0149 baseline.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0155_vims_dictionary_reference_source_row_key"),
        ("reports", "0156_downtime_checking"),
    ]

    operations = []
