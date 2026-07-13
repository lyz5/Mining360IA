import json
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand

from reports.powerbi import (
    DATASET_ROLE_ALIASES,
    DEFAULT_WORKSPACE_ID,
    POWERBI_ROOT,
    RLS_ROLE_OPTIONS,
    env_value,
    generate_report_embed_token,
    get_access_token,
    get_dataset_metadata,
    get_linked_powerbi_dataset_ids,
    get_report_hint_dataset_ids,
    list_workspace_reports,
    resolve_dataset_roles,
)


class Command(BaseCommand):
    help = "Build a local JSON inventory of Power BI report embed connection options."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default="powerbi_report_connections.json",
            help="Output JSON path relative to the Django project root.",
        )
        parser.add_argument(
            "--test-embed",
            action="store_true",
            help="Also test embed token generation for each report with the default role.",
        )

    def handle(self, *args, **options):
        workspace_id = env_value("POWERBI_WORKSPACE_ID", DEFAULT_WORKSPACE_ID)
        token = get_access_token()
        effective_username = ""
        try:
            effective_username = env_value("POWERBI_EFFECTIVE_USERNAME")
        except RuntimeError:
            pass
        default_roles = [
            role.strip()
            for role in env_value("POWERBI_EFFECTIVE_ROLES", "Global").split(",")
            if role.strip()
        ] or ["Global"]

        reports = list_workspace_reports()
        payload = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "workspace_id": workspace_id,
            "powerbi_root": POWERBI_ROOT,
            "effective_identity": {
                "username": effective_username,
                "default_roles": default_roles,
            },
            "ui_role_options": RLS_ROLE_OPTIONS,
            "reports": [],
        }

        for report in reports:
            dataset_ids = [report.dataset_id] if report.dataset_id else []
            for hinted_id in get_report_hint_dataset_ids(token, workspace_id, report.name):
                if hinted_id not in dataset_ids:
                    dataset_ids.append(hinted_id)
            for linked_id in get_linked_powerbi_dataset_ids(token, workspace_id, report.dataset_id):
                if linked_id not in dataset_ids:
                    dataset_ids.append(linked_id)

            datasets = []
            requires_identity = False
            requires_roles = False
            for dataset_id in dataset_ids:
                try:
                    metadata = get_dataset_metadata(token, workspace_id, dataset_id)
                except Exception as exc:
                    datasets.append(
                        {
                            "id": dataset_id,
                            "name": "",
                            "metadata_status": "error",
                            "metadata_error": str(exc),
                        }
                    )
                    continue

                identity_required = bool(metadata.get("isEffectiveIdentityRequired"))
                roles_required = bool(metadata.get("isEffectiveIdentityRolesRequired"))
                requires_identity = requires_identity or identity_required
                requires_roles = requires_roles or roles_required
                dataset_name = metadata.get("name", "")
                role_options = {
                    role: resolve_dataset_roles(dataset_name, [role])
                    for role in RLS_ROLE_OPTIONS
                }
                datasets.append(
                    {
                        "id": dataset_id,
                        "name": dataset_name,
                        "configured_by": "primary" if dataset_id == report.dataset_id else "linked_or_hint",
                        "is_effective_identity_required": identity_required,
                        "is_effective_identity_roles_required": roles_required,
                        "target_storage_mode": metadata.get("targetStorageMode", ""),
                        "role_aliases": DATASET_ROLE_ALIASES.get(dataset_name.lower(), {}),
                        "role_options": role_options,
                    }
                )

            report_item = {
                "name": report.name,
                "display_name": report.display_name,
                "report_id": report.id,
                "report_type": report.report_type,
                "web_url": report.web_url,
                "embed_url": report.embed_url,
                "primary_dataset_id": report.dataset_id,
                "dataset_ids": dataset_ids,
                "datasets": datasets,
                "embed": {
                    "requires_effective_identity": requires_identity,
                    "requires_roles": requires_roles,
                    "default_roles": default_roles,
                    "effective_username": effective_username if requires_identity else "",
                    "xmla_permissions": "ReadOnly",
                    "target_workspace_id": workspace_id,
                },
            }

            if options["test_embed"]:
                try:
                    embed_token = generate_report_embed_token(report, default_roles)
                    report_item["embed"]["token_test"] = {
                        "status": "success",
                        "token_received": bool(embed_token),
                    }
                except Exception as exc:
                    report_item["embed"]["token_test"] = {
                        "status": "failed",
                        "error": str(exc),
                    }

            payload["reports"].append(report_item)
            self.stdout.write(f"Configured: {report.name}")

        output_path = Path(options["output"])
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Power BI report connection config written: {output_path}"))
