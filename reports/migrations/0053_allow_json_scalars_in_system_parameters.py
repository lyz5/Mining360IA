from django.db import migrations


def remove_incompatible_sqlserver_json_checks(apps, schema_editor):
    if schema_editor.connection.vendor != "microsoft":
        return

    table_name = "SystemParameter"
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT cc.name
            FROM sys.check_constraints cc
            INNER JOIN sys.tables t ON t.object_id = cc.parent_object_id
            INNER JOIN sys.schemas s ON s.schema_id = t.schema_id
            WHERE s.name = SCHEMA_NAME()
              AND t.name = %s
              AND (
                    cc.name LIKE 'SystemParameter_value_json%%'
                 OR cc.name LIKE 'SystemParameter_default_value_json%%'
              )
            """,
            [table_name],
        )
        constraint_names = [row[0] for row in cursor.fetchall()]
        for constraint_name in constraint_names:
            quoted_table = schema_editor.quote_name(table_name)
            quoted_constraint = schema_editor.quote_name(constraint_name)
            cursor.execute(
                f"ALTER TABLE {quoted_table} DROP CONSTRAINT {quoted_constraint}"
            )


class Migration(migrations.Migration):
    dependencies = [("reports", "0052_normalize_ai_provider_model_codes")]

    operations = [
        migrations.RunPython(
            remove_incompatible_sqlserver_json_checks,
            migrations.RunPython.noop,
        ),
    ]
