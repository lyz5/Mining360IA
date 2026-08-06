import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from .external_data_browsers import (
    ExternalBrowserError,
    _column_name,
    _parameter_marker,
    _quote_identifier,
    _quote_object_name,
    external_browser_connection,
)
from .models import DataBrowser, DataBrowserWriteAuditLog, MiningProdUserMapping


class MiningProdWritePreviewError(ValueError):
    pass


def _json_safe(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _canonical_hash(payload: dict) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _boolean(value):
    if isinstance(value, bool):
        return -1 if value else 0
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "-1", "true", "yes", "active", "enabled"}:
        return -1
    if normalized in {"0", "false", "no", "inactive", "disabled"}:
        return 0
    raise MiningProdWritePreviewError(f"Invalid boolean value: {value}")


def _typed_value(column, value):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        if column.data_type == "Integer":
            return int(value)
        if column.data_type == "Decimal":
            return Decimal(str(value))
        if column.data_type == "Boolean":
            return _boolean(value)
        if column.data_type == "Date":
            return value if isinstance(value, date) else date.fromisoformat(str(value))
        if column.data_type == "DateTime":
            return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except (TypeError, ValueError, InvalidOperation) as exc:
        raise MiningProdWritePreviewError(
            f"{column.display_name} has an invalid {column.data_type.lower()} value."
        ) from exc
    text = str(value)
    if column.length and len(text) > column.length:
        raise MiningProdWritePreviewError(
            f"{column.display_name} exceeds the maximum length of {column.length}."
        )
    return text


class MiningProdMetaFormWriteService:
    OPERATIONS = {"create", "edit", "delete"}

    def preview(self, *, browser, operation, values=None, record_id=None, user=None) -> dict:
        operation = str(operation or "").strip().lower()
        if operation not in self.OPERATIONS:
            raise MiningProdWritePreviewError("Operation must be create, edit or delete.")
        if browser.source_mode != "miningprod_metaform":
            raise MiningProdWritePreviewError("This preview is only available for MiningProd browsers.")
        try:
            mapping = browser.write_mapping
        except ObjectDoesNotExist as exc:
            raise MiningProdWritePreviewError("No write mapping is configured for this browser.") from exc
        if mapping.validation_status == "blocked":
            raise MiningProdWritePreviewError("The write mapping is blocked.")

        normalized = self._normalize_values(browser, values or {}, operation)
        self._validate_required(mapping, normalized, operation)
        before = (
            self._fetch_record(browser, record_id)
            if operation in {"edit", "delete"}
            else {}
        )
        if operation in {"edit", "delete"} and not before:
            raise MiningProdWritePreviewError("The selected MiningProd record was not found.")

        external_user = self._external_user(user)
        blockers = []
        if external_user is None:
            blockers.append("A validated MiningProd user mapping is required before execution.")
        if not getattr(mapping, f"allow_{operation}", False):
            blockers.append(f"{operation.title()} has not been approved for this mapping.")
        if not mapping.active or mapping.validation_status != "active":
            blockers.append("The mapping is not activated for production writes.")

        plan = self._build_plan(
            mapping=mapping,
            operation=operation,
            values=normalized,
            record_id=record_id,
            external_user=external_user,
        )
        after = {} if operation == "delete" else ({**before, **normalized} if before else normalized)
        request_id = uuid.uuid4()
        input_payload = {
            "browser_id": browser.id,
            "operation": operation,
            "record_id": record_id,
            "values": normalized,
        }
        with transaction.atomic():
            DataBrowserWriteAuditLog.objects.create(
                request_id=request_id,
                browser=browser,
                mapping=mapping,
                user=user if getattr(user, "is_authenticated", False) else None,
                operation=operation,
                dry_run=True,
                record_key=str(record_id or ""),
                input_hash=_canonical_hash(input_payload),
                before_json={key: _json_safe(value) for key, value in before.items()},
                after_json={key: _json_safe(value) for key, value in after.items()},
                execution_plan_json=plan,
                status="previewed",
            )
        return {
            "request_id": str(request_id),
            "dry_run": True,
            "execution_allowed": False,
            "preview_ready_for_approval": not blockers,
            "blockers": blockers,
            "operation": operation,
            "browser": {
                "id": browser.id,
                "name": browser.name,
                "meta_form_id": browser.external_form_id,
            },
            "mapping": {
                "strategy": mapping.strategy,
                "version": mapping.mapping_version,
                "validation_status": mapping.validation_status,
            },
            "before": {key: _json_safe(value) for key, value in before.items()},
            "after": {key: _json_safe(value) for key, value in after.items()},
            "plan": plan,
            "notice": "Preview only. No statement was executed against MiningProd.",
        }

    def _normalize_values(self, browser, values, operation):
        if not isinstance(values, dict):
            raise MiningProdWritePreviewError("Values must be a JSON object.")
        columns = list(browser.columns.all())
        try:
            configuration = browser.write_mapping.configuration_json
            configured_fields = (
                set(configuration.get("field_labels", {}))
                | set(configuration.get("root_fields", {}))
                | set(configuration.get("cmt_fields", {}))
            )
        except ObjectDoesNotExist:
            configured_fields = set()
        aliases = {}
        for column in columns:
            aliases[str(column.source_column_name or "").lower()] = column
            aliases[str(column.sql_name or "").lower()] = column
            aliases[str(column.display_name or "").lower()] = column
        normalized = {}
        unknown = []
        for key, value in values.items():
            column = aliases.get(str(key).strip().lower())
            if not column:
                unknown.append(str(key))
                continue
            source_name = str(column.source_column_name or column.sql_name)
            if not column.is_editable and source_name not in configured_fields and operation != "delete":
                continue
            normalized[source_name] = _typed_value(column, value)
        if unknown:
            raise MiningProdWritePreviewError(
                "Unknown browser fields: " + ", ".join(sorted(unknown))
            )
        return normalized

    def _validate_required(self, mapping, values, operation):
        if operation != "create":
            return
        labels = mapping.configuration_json.get("field_labels", {})
        missing = [
            labels.get(field, field)
            for field in mapping.configuration_json.get("required_fields", [])
            if values.get(str(field)) in {None, ""}
        ]
        if missing:
            raise MiningProdWritePreviewError(
                "Required fields are missing: " + ", ".join(missing)
            )

    def _fetch_record(self, browser, record_id):
        if record_id in {None, ""}:
            raise MiningProdWritePreviewError("record_id is required.")
        columns = list(browser.columns.all())
        selected = []
        seen = set()
        for name in [browser.primary_key_column] + [_column_name(column) for column in columns]:
            if name and name.lower() not in seen:
                seen.add(name.lower())
                selected.append(name)
        query_columns = ", ".join(_quote_identifier(name) for name in selected)
        source = _quote_object_name(browser.source_view_name)
        with external_browser_connection(browser) as connection:
            marker = _parameter_marker(connection)
            cursor = connection.cursor()
            cursor.execute(
                f"SELECT {query_columns} FROM {source} "
                f"WHERE {_quote_identifier(browser.primary_key_column)} = {marker}",
                (record_id,),
            )
            row = cursor.fetchone()
        if not row:
            return {}
        return {
            name: _json_safe(value)
            for name, value in zip(selected, row)
        }

    def _external_user(self, user):
        if not getattr(user, "is_authenticated", False):
            return None
        try:
            mapping = user.miningprod_user_mapping
        except AttributeError:
            return None
        if not mapping.active or mapping.validation_status != "validated":
            return None
        return {
            "user_id": mapping.external_user_id,
            "username": mapping.external_username,
        }

    def _build_plan(self, *, mapping, operation, values, record_id, external_user):
        if mapping.strategy == "direct_table":
            return self._direct_plan(mapping, operation, values, record_id, external_user)
        if mapping.strategy == "eventchain_eav":
            return self._eventchain_plan(mapping, operation, values, record_id, external_user)
        raise MiningProdWritePreviewError(
            f"Unsupported write strategy: {mapping.strategy}"
        )

    def _direct_plan(self, mapping, operation, values, record_id, external_user):
        config = mapping.configuration_json
        root_fields = config.get("root_fields", {})
        cmt_fields = config.get("cmt_fields", {})
        user_token = (external_user or {}).get("user_id", "<validated-user-id>")
        if operation == "create":
            root_values = {
                target: values[source]
                for source, target in root_fields.items()
                if source in values
            }
            root_values.update({
                "CREATED_BY": user_token,
                "USER_ID": user_token,
            })
            steps = [{
                "order": 1,
                "action": "insert",
                "table": mapping.root_table,
                "columns": list(root_values),
                "parameter_count": len(root_values),
                "capture_identity_as": mapping.root_primary_key,
            }]
            for source, definition in cmt_fields.items():
                if values.get(source) is None:
                    continue
                steps.append({
                    "order": len(steps) + 1,
                    "action": "insert",
                    "table": config["cmt_table"],
                    "columns": [
                        mapping.root_primary_key,
                        config["cmt_id_column"],
                        config["cmt_value_column"],
                        "ENABLED",
                        "CREATED_BY",
                        "USER_ID",
                    ],
                    "fixed_values": {
                        config["cmt_id_column"]: definition["cmt_id"],
                        "ENABLED": -1,
                    },
                    "parameter_count": 3,
                })
            return {"transaction": True, "strategy": mapping.strategy, "steps": steps}
        if operation == "edit":
            steps = []
            root_updates = [target for source, target in root_fields.items() if source in values]
            if root_updates:
                steps.append({
                    "order": 1,
                    "action": "update",
                    "table": mapping.root_table,
                    "columns": root_updates + ["LAST_MODIFIED", "USER_ID"],
                    "where": {mapping.root_primary_key: record_id},
                    "parameter_count": len(root_updates) + 3,
                })
            for source, definition in cmt_fields.items():
                if source not in values:
                    continue
                steps.append({
                    "order": len(steps) + 1,
                    "action": "upsert_or_disable",
                    "table": config["cmt_table"],
                    "match": {
                        mapping.root_primary_key: record_id,
                        config["cmt_id_column"]: definition["cmt_id"],
                    },
                    "value_column": config["cmt_value_column"],
                    "enabled_value": -1,
                })
            return {"transaction": True, "strategy": mapping.strategy, "steps": steps}
        return {
            "transaction": True,
            "strategy": mapping.strategy,
            "steps": [
                {
                    "order": 1,
                    "action": "delete",
                    "table": config["cmt_table"],
                    "where": {mapping.root_primary_key: record_id},
                },
                {
                    "order": 2,
                    "action": "delete",
                    "table": mapping.root_table,
                    "where": {mapping.root_primary_key: record_id},
                },
            ],
        }

    def _eventchain_plan(self, mapping, operation, values, record_id, external_user):
        config = mapping.configuration_json
        user_token = (external_user or {}).get("user_id", "<validated-user-id>")
        cmt_fields = config.get("cmt_fields", {})
        if operation == "create":
            steps = [
                {
                    "order": 1,
                    "action": "insert",
                    "table": "EVENTCHAIN",
                    "columns": ["EVENTCHAINTYPEID", "CREATED_BY", "USER_ID"],
                    "fixed_values": {"EVENTCHAINTYPEID": config["eventchain_type_id"]},
                    "parameter_count": 2,
                    "capture_identity_as": "EVENTCHAINID",
                },
                {
                    "order": 2,
                    "action": "insert",
                    "table": "EVENT",
                    "columns": [
                        "EVENTTYPEID",
                        "EVENTCHAINID",
                        "BUSINESS_UNIT_ID",
                        "ENABLED",
                        "CREATED_BY",
                        "USER_ID",
                    ],
                    "fixed_values": {
                        "EVENTTYPEID": config["event_type_id"],
                        "BUSINESS_UNIT_ID": config["business_unit_id"],
                        "ENABLED": -1,
                    },
                    "parameter_count": 2,
                },
            ]
            for source, definition in cmt_fields.items():
                if values.get(source) is None:
                    continue
                steps.append({
                    "order": len(steps) + 1,
                    "action": "insert",
                    "table": "EVENTCHAINCMTVAL",
                    "columns": [
                        "EVENTCHAINID",
                        "EVENTCHAINCMTID",
                        "EVENTCHAINCMTVAL",
                        "CREATED_BY",
                        "USER_ID",
                    ],
                    "fixed_values": {"EVENTCHAINCMTID": definition["cmt_id"]},
                    "parameter_count": 3,
                })
            return {"transaction": True, "strategy": mapping.strategy, "steps": steps}
        if operation == "edit":
            steps = []
            for source, definition in cmt_fields.items():
                if source not in values:
                    continue
                steps.append({
                    "order": len(steps) + 1,
                    "action": "upsert_or_delete",
                    "table": "EVENTCHAINCMTVAL",
                    "match": {
                        "EVENTCHAINID": record_id,
                        "EVENTCHAINCMTID": definition["cmt_id"],
                    },
                    "value_column": "EVENTCHAINCMTVAL",
                })
            return {"transaction": True, "strategy": mapping.strategy, "steps": steps}
        return {
            "transaction": True,
            "strategy": mapping.strategy,
            "steps": [
                {
                    "order": 1,
                    "action": "delete",
                    "table": "EVENTCHAINCMTVAL",
                    "where": {"EVENTCHAINID": record_id},
                },
                {
                    "order": 2,
                    "action": "delete",
                    "table": "EVENT",
                    "where": {
                        "EVENTCHAINID": record_id,
                        "BUSINESS_UNIT_ID": config["business_unit_id"],
                    },
                },
                {
                    "order": 3,
                    "action": "delete",
                    "table": "EVENTCHAIN",
                    "where": {"EVENTCHAINID": record_id},
                },
            ],
        }


def preview_miningprod_browser_write(**kwargs):
    return MiningProdMetaFormWriteService().preview(**kwargs)


def _mapping_browser():
    return DataBrowser.objects.select_related("source_connection").get(external_form_id=36)


def search_miningprod_users(search: str, *, limit: int = 25) -> list[dict]:
    search = str(search or "").strip()
    if len(search) < 2:
        raise MiningProdWritePreviewError("Enter at least two characters to search MiningProd users.")
    browser = _mapping_browser()
    pattern = f"%{search[:100]}%"
    with external_browser_connection(browser) as connection:
        marker = _parameter_marker(connection)
        cursor = connection.cursor()
        cursor.execute(
            "SELECT TOP 25 EMPLOYEEID, USER_ID, USERNAME, USERFIRSTNAME, "
            "USERLASTNAME FROM dbo.TBLSYSTEMUSERS "
            f"WHERE enabled <> 0 AND (USERNAME LIKE {marker} "
            f"OR USERFIRSTNAME LIKE {marker} OR USERLASTNAME LIKE {marker}) "
            "ORDER BY USERNAME",
            (pattern, pattern, pattern),
        )
        rows = cursor.fetchall()
    return [
        {
            "employee_id": int(row[0]),
            "audit_user_id": int(row[1]),
            "username": str(row[2] or ""),
            "first_name": str(row[3] or ""),
            "last_name": str(row[4] or ""),
        }
        for row in rows[: max(1, min(int(limit), 25))]
    ]


def get_miningprod_user_mapping(user) -> dict | None:
    if not getattr(user, "is_authenticated", False):
        return None
    try:
        mapping = user.miningprod_user_mapping
    except ObjectDoesNotExist:
        return None
    return {
        "employee_id": mapping.external_employee_id,
        "audit_user_id": mapping.external_user_id,
        "username": mapping.external_username,
        "validation_status": mapping.validation_status,
        "active": mapping.active,
        "validated_at": mapping.validated_at.isoformat() if mapping.validated_at else None,
    }


def validate_miningprod_user_mapping(
    *,
    user,
    employee_id,
    username,
    validated_by,
) -> dict:
    try:
        employee_id = int(employee_id)
    except (TypeError, ValueError) as exc:
        raise MiningProdWritePreviewError("A valid MiningProd employee ID is required.") from exc
    username = str(username or "").strip()
    if not username:
        raise MiningProdWritePreviewError("MiningProd username is required.")

    browser = _mapping_browser()
    with external_browser_connection(browser) as connection:
        marker = _parameter_marker(connection)
        cursor = connection.cursor()
        cursor.execute(
            "SELECT EMPLOYEEID, USER_ID, USERNAME FROM dbo.TBLSYSTEMUSERS "
            f"WHERE EMPLOYEEID = {marker} AND USERNAME = {marker} AND enabled <> 0",
            (employee_id, username),
        )
        row = cursor.fetchone()
    if not row:
        raise MiningProdWritePreviewError(
            "The selected active MiningProd user could not be validated."
        )

    with transaction.atomic():
        conflicting = MiningProdUserMapping.objects.filter(
            external_employee_id=int(row[0])
        ).exclude(user=user)
        if conflicting.exists():
            raise MiningProdWritePreviewError(
                "This MiningProd account is already assigned to another Mining360 user."
            )
        mapping, _ = MiningProdUserMapping.objects.update_or_create(
            user=user,
            defaults={
                "external_employee_id": int(row[0]),
                "external_user_id": int(row[1]),
                "external_username": str(row[2]),
                "validation_status": "validated",
                "active": True,
                "validated_by": validated_by,
                "validated_at": timezone.now(),
            },
        )
    return get_miningprod_user_mapping(mapping.user)


def run_equipment_models_rollback_test(*, user, confirmation: str) -> dict:
    if confirmation != "RUN ROLLBACK TEST":
        raise MiningProdWritePreviewError(
            "The rollback test requires the exact confirmation RUN ROLLBACK TEST."
        )
    browser = DataBrowser.objects.select_related("write_mapping").get(external_form_id=36)
    try:
        user_mapping = user.miningprod_user_mapping
    except ObjectDoesNotExist as exc:
        raise MiningProdWritePreviewError(
            "Validate your MiningProd audit user before running the rollback test."
        ) from exc
    if (
        not user_mapping.active
        or user_mapping.validation_status != "validated"
        or not user_mapping.external_employee_id
    ):
        raise MiningProdWritePreviewError(
            "A validated MiningProd audit user is required."
        )

    marker_value = f"M360_ROLLBACK_{uuid.uuid4().hex[:12].upper()}"
    audit_user_id = user_mapping.external_user_id
    inserted_id = None
    observed_root = 0
    observed_cmt = 0
    request_id = uuid.uuid4()
    plan = {
        "transaction": True,
        "forced_rollback": True,
        "steps": [
            {"order": 1, "action": "insert", "table": "EQUIPTYPE"},
            {"order": 2, "action": "insert", "table": "EQUIPTYPECMTVAL"},
            {"order": 3, "action": "verify_inside_transaction", "table": "EQUIPTYPE"},
            {"order": 4, "action": "rollback", "table": "MiningProd transaction"},
            {"order": 5, "action": "verify_after_rollback", "table": "EQUIPTYPE"},
        ],
    }
    try:
        with external_browser_connection(browser) as connection:
            marker = _parameter_marker(connection)
            cursor = connection.cursor()
            cursor.execute(
                "SELECT COUNT_BIG(1) FROM dbo.EQUIPTYPE "
                f"WHERE EQUIPTYPE = {marker}",
                (marker_value,),
            )
            if int(cursor.fetchone()[0]) != 0:
                raise MiningProdWritePreviewError("The rollback test marker already exists.")
            cursor.execute(
                "INSERT INTO dbo.EQUIPTYPE "
                "(EQUIPTYPE, DESCRIPTION, ENABLED, CREATED_BY, USER_ID) "
                "OUTPUT INSERTED.EQUIPTYPEID "
                f"VALUES ({marker}, {marker}, -1, {marker}, {marker})",
                (
                    marker_value,
                    "Mining360 rollback validation; must not persist",
                    audit_user_id,
                    audit_user_id,
                ),
            )
            inserted_id = int(cursor.fetchone()[0])
            cursor.execute(
                "INSERT INTO dbo.EQUIPTYPECMTVAL "
                "(EQUIPTYPECMTVAL, EQUIPTYPECMTID, EQUIPTYPEID, ENABLED, CREATED_BY, USER_ID) "
                f"VALUES ({marker}, 7, {marker}, -1, {marker}, {marker})",
                ("M360-ROLLBACK", inserted_id, audit_user_id, audit_user_id),
            )
            cursor.execute(
                "SELECT COUNT_BIG(1) FROM dbo.EQUIPTYPE "
                f"WHERE EQUIPTYPEID = {marker}",
                (inserted_id,),
            )
            observed_root = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT COUNT_BIG(1) FROM dbo.EQUIPTYPECMTVAL "
                f"WHERE EQUIPTYPEID = {marker}",
                (inserted_id,),
            )
            observed_cmt = int(cursor.fetchone()[0])
            if observed_root != 1 or observed_cmt != 1:
                raise MiningProdWritePreviewError(
                    "The inserted test rows could not be verified inside the transaction."
                )
            connection.rollback()

        with external_browser_connection(browser) as verification_connection:
            marker = _parameter_marker(verification_connection)
            cursor = verification_connection.cursor()
            cursor.execute(
                "SELECT COUNT_BIG(1) FROM dbo.EQUIPTYPE "
                f"WHERE EQUIPTYPE = {marker} OR EQUIPTYPEID = {marker}",
                (marker_value, inserted_id),
            )
            persisted_root = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT COUNT_BIG(1) FROM dbo.EQUIPTYPECMTVAL "
                f"WHERE EQUIPTYPEID = {marker}",
                (inserted_id,),
            )
            persisted_cmt = int(cursor.fetchone()[0])
        if persisted_root or persisted_cmt:
            raise MiningProdWritePreviewError(
                "Rollback verification failed: test data is still present."
            )
        status = "validated"
        error_message = ""
    except Exception as exc:
        status = "failed"
        error_message = str(exc)
        raise
    finally:
        DataBrowserWriteAuditLog.objects.create(
            request_id=request_id,
            browser=browser,
            mapping=browser.write_mapping,
            user=user,
            operation="rollback_test",
            dry_run=True,
            record_key=str(inserted_id or ""),
            input_hash=_canonical_hash({
                "browser_id": browser.id,
                "operation": "rollback_test",
                "marker": marker_value,
            }),
            before_json={},
            after_json={},
            execution_plan_json=plan,
            status=status,
            error_message=error_message,
            completed_at=timezone.now(),
        )
    return {
        "request_id": str(request_id),
        "browser": browser.name,
        "transaction_insert_verified": observed_root == 1 and observed_cmt == 1,
        "rollback_verified": True,
        "persisted_root_rows": 0,
        "persisted_cmt_rows": 0,
        "write_activation_changed": False,
        "notice": "The test transaction was rolled back and no test row remains in MiningProd.",
    }
