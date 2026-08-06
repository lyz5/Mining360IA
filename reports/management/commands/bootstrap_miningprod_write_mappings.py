from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from reports.models import DataBrowser, DataBrowserWriteMapping


PILOT_MAPPINGS = {
    36: {
        "strategy": "direct_table",
        "root_table": "EQUIPTYPE",
        "root_primary_key": "EQUIPTYPEID",
        "required_fields": ["354", "355", "356"],
        "field_labels": {
            "354": "Description",
            "355": "Status",
            "356": "Model",
        },
        "root_fields": {
            "354": "DESCRIPTION",
            "355": "ENABLED",
            "356": "EQUIPTYPE",
        },
        "cmt_table": "EQUIPTYPECMTVAL",
        "cmt_id_column": "EQUIPTYPECMTID",
        "cmt_value_column": "EQUIPTYPECMTVAL",
        "cmt_fields": {
            "2433293": {"label": "Brand", "cmt_id": 7},
            "2433294": {"label": "Family", "cmt_id": 4},
            "2433295": {"label": "Priority", "cmt_id": 5},
            "2433296": {"label": "Type", "cmt_id": 6},
            "2435811": {"label": "Prime Movers", "cmt_id": 8},
        },
    },
    2405990: {
        "strategy": "eventchain_eav",
        "root_table": "EVENTCHAIN",
        "root_primary_key": "EVENTCHAINID",
        "eventchain_type_id": 2,
        "event_type_id": 2,
        "business_unit_id": 122756,
        "required_fields": ["2434454"],
        "field_labels": {"2434448": "Country", "2434454": "Mining Group"},
        "cmt_fields": {
            "2434448": {"label": "Country", "cmt_id": 4640},
            "2434454": {"label": "Mining Group", "cmt_id": 4643},
        },
    },
    2405989: {
        "strategy": "eventchain_eav",
        "root_table": "EVENTCHAIN",
        "root_primary_key": "EVENTCHAINID",
        "eventchain_type_id": 2,
        "event_type_id": 2,
        "business_unit_id": 122755,
        "required_fields": ["2434446"],
        "field_labels": {"2434440": "Country", "2434446": "Contractor"},
        "cmt_fields": {
            "2434440": {"label": "Country", "cmt_id": 4640},
            "2434446": {"label": "Contractor", "cmt_id": 4642},
        },
    },
    2406017: {
        "strategy": "eventchain_eav",
        "root_table": "EVENTCHAIN",
        "root_primary_key": "EVENTCHAINID",
        "eventchain_type_id": 2,
        "event_type_id": 2,
        "business_unit_id": 122772,
        "required_fields": ["2435788"],
        "field_labels": {
            "2435788": "Product Group Code",
            "2435789": "Product Group Description",
            "2435809": "Priority",
        },
        "cmt_fields": {
            "2435788": {"label": "Product Group Code", "cmt_id": 5773},
            "2435789": {"label": "Product Group Description", "cmt_id": 5772},
            "2435809": {"label": "Priority", "cmt_id": 5782},
        },
    },
    2406031: {
        "strategy": "eventchain_eav",
        "root_table": "EVENTCHAIN",
        "root_primary_key": "EVENTCHAINID",
        "eventchain_type_id": 2,
        "event_type_id": 2,
        "business_unit_id": 122784,
        "required_fields": ["2436197"],
        "field_labels": {
            "2436197": "Customer Code",
            "2436198": "Account",
            "2436199": "RA",
            "2436201": "Mine Site",
            "2436327": "Customer",
        },
        "cmt_fields": {
            "2436197": {"label": "Customer Code", "cmt_id": 6710},
            "2436198": {"label": "Account", "cmt_id": 6711},
            "2436199": {"label": "RA", "cmt_id": 6709},
            "2436201": {"label": "Mine Site", "cmt_id": 6713},
            "2436327": {"label": "Customer", "cmt_id": 6754},
        },
    },
}


class Command(BaseCommand):
    help = "Create preview-only write mappings for the five MiningProd pilot browsers."

    def add_arguments(self, parser):
        parser.add_argument("--preview", action="store_true")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--form-id", action="append", type=int, dest="form_ids")

    def handle(self, *args, **options):
        if options["preview"] == options["apply"]:
            raise CommandError("Choose exactly one mode: --preview or --apply.")
        selected = set(options.get("form_ids") or PILOT_MAPPINGS)
        unknown = selected.difference(PILOT_MAPPINGS)
        if unknown:
            raise CommandError(f"Unsupported pilot MetaForm IDs: {sorted(unknown)}")
        browsers = {
            browser.external_form_id: browser
            for browser in DataBrowser.objects.filter(external_form_id__in=selected)
        }
        missing = selected.difference(browsers)
        if missing:
            raise CommandError(
                "Synchronize these MiningProd browsers first: " + ", ".join(map(str, sorted(missing)))
            )
        existing_ids = set(
            DataBrowserWriteMapping.objects.filter(browser__external_form_id__in=selected)
            .values_list("browser__external_form_id", flat=True)
        )
        self.stdout.write(f"Pilot mappings selected: {len(selected)}")
        self.stdout.write(f"Mappings to create: {len(selected - existing_ids)}")
        self.stdout.write(f"Mappings to update: {len(selected & existing_ids)}")
        self.stdout.write("Write execution enabled: No")
        for form_id in sorted(selected):
            state = "UPDATE" if form_id in existing_ids else "CREATE"
            self.stdout.write(f"{state} MetaForm {form_id}: {browsers[form_id].name}")
        if options["preview"]:
            return

        with transaction.atomic():
            for form_id in sorted(selected):
                definition = dict(PILOT_MAPPINGS[form_id])
                strategy = definition.pop("strategy")
                root_table = definition.pop("root_table")
                root_primary_key = definition.pop("root_primary_key")
                mapping, created = DataBrowserWriteMapping.objects.get_or_create(
                    browser=browsers[form_id],
                    defaults={
                        "strategy": strategy,
                        "root_table": root_table,
                        "root_primary_key": root_primary_key,
                        "configuration_json": definition,
                        "mapping_version": "1.0",
                        "validation_status": "draft",
                        "allow_create": False,
                        "allow_edit": False,
                        "allow_delete": False,
                        "active": False,
                    },
                )
                mapping.strategy = strategy
                mapping.root_table = root_table
                mapping.root_primary_key = root_primary_key
                mapping.configuration_json = definition
                mapping.mapping_version = "1.0"
                mapping.save(update_fields=[
                    "strategy",
                    "root_table",
                    "root_primary_key",
                    "configuration_json",
                    "mapping_version",
                    "updated_at",
                ])
                browser = browsers[form_id]
                browser.migration_status = "write_validation"
                browser.save(update_fields=["migration_status", "updated_at"])
                mapped_fields = (
                    set(definition.get("field_labels", {}))
                    | set(definition.get("root_fields", {}))
                    | set(definition.get("cmt_fields", {}))
                )
                browser.columns.filter(source_column_name__in=mapped_fields).update(is_editable=True)
        self.stdout.write(self.style.SUCCESS("Preview-only MiningProd write mappings synchronized."))
