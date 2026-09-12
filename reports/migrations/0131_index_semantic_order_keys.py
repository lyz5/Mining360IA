from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("reports", "0130_semantic_order_header_keys")]

    operations = [
        migrations.AddIndex(
            model_name="reconciliationorderline",
            index=models.Index(
                fields=["snapshot", "semantic_order_key"],
                name="rec_order_snapshot_semkey_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="reconciliationorderheader",
            index=models.Index(
                fields=["snapshot", "semantic_order_key"],
                name="rec_header_snapshot_semkey_idx",
            ),
        ),
    ]
