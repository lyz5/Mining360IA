from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reports", "0128_link_order_lines_to_headers")]

    operations = [
        migrations.AddIndex(
            model_name="reconciliationorderline",
            index=models.Index(fields=["snapshot", "order_header"], name="rec_order_snapshot_header_idx"),
        ),
    ]
