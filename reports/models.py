import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.contrib.auth.models import Group, User


class DataQualityRun(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    source_key = models.CharField(max_length=120, db_index=True)
    source_name = models.CharField(max_length=255)
    object_kind = models.CharField(max_length=40)
    object_name = models.CharField(max_length=512)
    run_type = models.CharField(max_length=20, default="all")
    status = models.CharField(max_length=20, default="Completed")
    score = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    total_rows = models.IntegerField(default=0)
    controls_count = models.IntegerField(default=0)
    summary = models.JSONField(default=dict, blank=True)
    results = models.JSONField(default=list, blank=True)
    request_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.source_name} - {self.object_name} ({self.created_at:%Y-%m-%d %H:%M})"


class PlatformUser(models.Model):
    ROLE_CHOICES = [
        ("reporting", "Reporting"),
        ("ai", "IA"),
        ("data", "Data"),
        ("sources", "Data Source"),
    ]

    azure_ad_id = models.CharField(max_length=128, unique=True)
    entra_tenant_id = models.CharField(max_length=128, blank=True)
    user_principal_name = models.EmailField(unique=True)
    email = models.EmailField(blank=True)
    display_name = models.CharField(max_length=255)
    job_title = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    is_platform_admin = models.BooleanField(default=False)
    can_access_reporting = models.BooleanField(default=False)
    can_access_ai = models.BooleanField(default=False)
    can_access_data = models.BooleanField(default=False)
    can_access_sources = models.BooleanField(default=False)
    BUSINESS_PERFORMANCE_ROLES = [
        ("", "No access"),
        ("Executive", "Executive"),
        ("Business Manager", "Business Manager"),
        ("Country Manager", "Country Manager"),
        ("Account Manager", "Account Manager"),
        ("Viewer", "Viewer"),
        ("Administrator", "Administrator"),
    ]
    business_performance_role = models.CharField(
        max_length=40, choices=BUSINESS_PERFORMANCE_ROLES, blank=True, default=""
    )
    business_performance_scope = models.JSONField(default=dict, blank=True)
    django_user = models.OneToOneField(User, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_entra_authenticated_at = models.DateTimeField(null=True, blank=True)
    AUTH_SOURCES = [
        ("local", "Local"),
        ("microsoft_entra", "Microsoft Entra"),
        ("active_directory", "Active Directory"),
    ]
    auth_source = models.CharField(max_length=30, choices=AUTH_SOURCES, default="local", db_index=True)
    directory_object_id = models.CharField(max_length=255, blank=True, db_index=True)
    directory_username = models.CharField(max_length=255, blank=True, db_index=True)
    directory_distinguished_name = models.TextField(blank=True)
    directory_groups_json = models.JSONField(default=list, blank=True)
    directory_roles_managed = models.BooleanField(default=True)
    last_directory_sync_at = models.DateTimeField(null=True, blank=True)
    last_directory_authenticated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["display_name", "user_principal_name"]

    def __str__(self) -> str:
        return f"{self.display_name} ({self.user_principal_name})"

    def has_module_access(self, module_code: str) -> bool:
        if not self.is_active:
            return False
        if self.is_platform_admin:
            return True
        return bool(getattr(self, f"can_access_{module_code}", False))


class HomepageConfiguration(models.Model):
    PERIOD_CHOICES = [
        ("ytd", "Year to Date"),
        ("last_12_months", "Last 12 Months"),
    ]
    BREAKDOWN_CHOICES = [
        ("overall", "Overall"),
        ("minesite", "Mine Site"),
        ("model", "Model"),
        ("equipment", "Equipment"),
    ]
    ANIMATION_CHOICES = [
        ("subtle", "Subtle"),
        ("standard", "Standard"),
        ("reduced", "Reduced"),
    ]

    code = models.SlugField(max_length=120, unique=True, default="availability-command-center")
    default_kpi = models.CharField(max_length=120, default="availability")
    default_period = models.CharField(max_length=30, choices=PERIOD_CHOICES, default="ytd")
    default_breakdown = models.CharField(max_length=30, choices=BREAKDOWN_CHOICES, default="overall")
    show_target = models.BooleanField(default=True)
    show_comparison = models.BooleanField(default=True)
    show_top_performers = models.BooleanField(default=True)
    show_bottom_performers = models.BooleanField(default=True)
    show_ai_insight = models.BooleanField(default=False)
    maximum_cards = models.PositiveSmallIntegerField(default=5)
    equipment_page_size = models.PositiveSmallIntegerField(default=25)
    animation_enabled = models.BooleanField(default=True)
    animation_intensity = models.CharField(max_length=20, choices=ANIMATION_CHOICES, default="standard")
    cache_duration_seconds = models.PositiveIntegerField(default=300)
    freshness_threshold_hours = models.PositiveIntegerField(default=24)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        db_table = "homepage_configuration"

    def __str__(self) -> str:
        return "Availability Command Center"


class HomepageInteractionEvent(models.Model):
    EVENT_TYPES = [
        ("page_view", "Page view"),
        ("period_change", "Period change"),
        ("breakdown_change", "Breakdown change"),
        ("filter_change", "Filter change"),
        ("drill_down", "Drill down"),
        ("ask_ai", "Ask AI"),
        ("open_report", "Open report"),
        ("open_downtime", "Open downtime drivers"),
    ]

    user = models.ForeignKey(
        User,
        related_name="homepage_interaction_events",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    event_type = models.CharField(max_length=40, choices=EVENT_TYPES, db_index=True)
    context_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "homepage_interaction_event"

    def __str__(self) -> str:
        return f"{self.event_type} at {self.created_at:%Y-%m-%d %H:%M}"


class ActiveDirectorySyncRun(models.Model):
    STATUSES = [(value, value) for value in ("Running", "Completed", "Partially Completed", "Failed")]

    integration = models.ForeignKey("SystemIntegrationConfig", null=True, blank=True, on_delete=models.SET_NULL)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=30, choices=STATUSES, default="Running", db_index=True)
    discovered_users = models.PositiveIntegerField(default=0)
    created_users = models.PositiveIntegerField(default=0)
    updated_users = models.PositiveIntegerField(default=0)
    disabled_users = models.PositiveIntegerField(default=0)
    skipped_users = models.PositiveIntegerField(default=0)
    failed_users = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        db_table = "ActiveDirectorySyncRun"
        permissions = [("synchronize_active_directory", "Can synchronize Active Directory")]


class ActiveDirectoryAuthenticationAuditLog(models.Model):
    STATUSES = [("success", "Success"), ("failed", "Failed"), ("blocked", "Blocked")]

    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    username = models.CharField(max_length=255, blank=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUSES, db_index=True)
    reason_code = models.CharField(max_length=80, blank=True, db_index=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "ActiveDirectoryAuthenticationAuditLog"


class UserAccessAuditLog(models.Model):
    ACTIONS = [
        ("user_added", "User added"),
        ("access_changed", "Access changed"),
        ("user_enabled", "User enabled"),
        ("user_disabled", "User disabled"),
    ]

    platform_user = models.ForeignKey(
        PlatformUser, on_delete=models.CASCADE, related_name="access_audit_logs"
    )
    actor = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="user_access_changes"
    )
    action = models.CharField(max_length=40, choices=ACTIONS, db_index=True)
    before_json = models.JSONField(default=dict, blank=True)
    after_json = models.JSONField(default=dict, blank=True)
    metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "UserAccessAuditLog"
        permissions = [("view_user_access_audit", "Can view user access audit history")]


class DataBrowser(models.Model):
    SOURCE_MODES = [
        ("managed_table", "Mining 360 Managed Table"),
        ("external_view", "External Database View"),
        ("miningprod_metaform", "MiningProd MetaForm"),
    ]
    WRITE_STRATEGIES = [
        ("managed_table", "Mining 360 Managed Table"),
        ("read_only", "Read Only"),
        ("miningprod_metaform", "MiningProd MetaForm Service"),
    ]
    MIGRATION_STATUSES = [
        ("not_started", "Not Started"),
        ("read_only", "Read Only Validation"),
        ("write_validation", "Write Validation"),
        ("ready", "Ready for Cutover"),
        ("migrated", "Migrated"),
        ("blocked", "Blocked"),
    ]

    name = models.CharField(max_length=255)
    display_order = models.PositiveIntegerField(default=0)
    section = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    table_name = models.CharField(max_length=255, unique=True)
    source_view_name = models.CharField(max_length=255)
    source_mode = models.CharField(max_length=30, choices=SOURCE_MODES, default="managed_table")
    source_connection = models.ForeignKey(
        "SystemIntegrationConfig",
        related_name="data_browsers",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    external_form_id = models.PositiveIntegerField(null=True, blank=True, unique=True)
    primary_key_column = models.CharField(max_length=128, default="BrowserRecordId")
    write_strategy = models.CharField(max_length=30, choices=WRITE_STRATEGIES, default="managed_table")
    allow_create = models.BooleanField(default=True)
    allow_edit = models.BooleanField(default=True)
    allow_delete = models.BooleanField(default=True)
    allow_import = models.BooleanField(default=True)
    allow_export = models.BooleanField(default=True)
    default_page_size = models.PositiveIntegerField(default=50)
    maximum_page_size = models.PositiveIntegerField(default=500)
    default_sort_json = models.JSONField(default=list, blank=True)
    source_metadata_json = models.JSONField(default=dict, blank=True)
    migration_status = models.CharField(
        max_length=30,
        choices=MIGRATION_STATUSES,
        default="not_started",
    )
    is_active = models.BooleanField(default=True)
    show_browser_record_id = models.BooleanField(default=True)
    show_eventchain_id = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=30, blank=True)
    last_sync_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "name"]
        db_table = "BrowserList"

    def __str__(self) -> str:
        return self.name


class DataBrowserColumn(models.Model):
    DATA_TYPES = [
        ("Text", "Text"),
        ("Integer", "Integer"),
        ("Decimal", "Decimal"),
        ("Date", "Date"),
        ("DateTime", "DateTime"),
        ("Boolean", "Boolean"),
    ]

    browser = models.ForeignKey(DataBrowser, related_name="columns", on_delete=models.CASCADE)
    display_name = models.CharField(max_length=255)
    sql_name = models.CharField(max_length=128)
    source_column_name = models.CharField(max_length=128, blank=True)
    source_field_id = models.PositiveIntegerField(null=True, blank=True)
    data_type = models.CharField(max_length=20, choices=DATA_TYPES)
    length = models.PositiveIntegerField(null=True, blank=True)
    is_required = models.BooleanField(default=False)
    is_unique = models.BooleanField(default=False)
    default_value = models.CharField(max_length=255, blank=True)
    display_order = models.PositiveIntegerField(default=0)
    is_visible = models.BooleanField(default=True)
    is_editable = models.BooleanField(default=True)
    is_filterable = models.BooleanField(default=True)
    is_sortable = models.BooleanField(default=True)
    is_searchable = models.BooleanField(default=True)
    is_exportable = models.BooleanField(default=True)
    is_lookup = models.BooleanField(default=False)
    lookup_source_name = models.CharField(max_length=255, blank=True)
    lookup_value_column = models.CharField(max_length=128, blank=True)
    lookup_label_column = models.CharField(max_length=128, blank=True)
    lookup_filter = models.CharField(max_length=255, blank=True)
    source_metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "display_name"]
        constraints = [
            models.UniqueConstraint(fields=["browser", "sql_name"], name="unique_browser_sql_column"),
        ]

    def __str__(self) -> str:
        return f"{self.browser.name} - {self.display_name}"


class DataBrowserSyncLog(models.Model):
    browser = models.ForeignKey(DataBrowser, related_name="sync_logs", on_delete=models.CASCADE)
    action = models.CharField(max_length=80)
    status = models.CharField(max_length=30)
    message = models.TextField(blank=True)
    sql_statement = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.browser.name} - {self.action} - {self.status}"


class DataBrowserWriteMapping(models.Model):
    STRATEGIES = [
        ("direct_table", "Direct Table"),
        ("eventchain_eav", "EventChain EAV"),
        ("metaform_adapter", "MetaForm Adapter"),
    ]
    VALIDATION_STATUSES = [
        ("draft", "Draft"),
        ("preview_validated", "Preview Validated"),
        ("write_validated", "Write Validated"),
        ("active", "Active"),
        ("blocked", "Blocked"),
    ]

    browser = models.OneToOneField(
        DataBrowser,
        related_name="write_mapping",
        on_delete=models.CASCADE,
    )
    strategy = models.CharField(max_length=30, choices=STRATEGIES)
    root_table = models.CharField(max_length=128)
    root_primary_key = models.CharField(max_length=128)
    configuration_json = models.JSONField(default=dict, blank=True)
    mapping_version = models.CharField(max_length=30, default="1.0")
    validation_status = models.CharField(
        max_length=30,
        choices=VALIDATION_STATUSES,
        default="draft",
    )
    allow_create = models.BooleanField(default=False)
    allow_edit = models.BooleanField(default=False)
    allow_delete = models.BooleanField(default=False)
    active = models.BooleanField(default=False)
    preview_validated_at = models.DateTimeField(null=True, blank=True)
    preview_validated_by = models.ForeignKey(
        User,
        related_name="preview_validated_browser_mappings",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    activated_by = models.ForeignKey(
        User,
        related_name="activated_browser_mappings",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["browser__display_order", "browser__name"]
        db_table = "DataBrowserWriteMapping"

    def __str__(self) -> str:
        return f"{self.browser.name} ({self.strategy})"


class MiningProdUserMapping(models.Model):
    VALIDATION_STATUSES = [
        ("draft", "Draft"),
        ("validated", "Validated"),
        ("rejected", "Rejected"),
    ]

    user = models.OneToOneField(
        User,
        related_name="miningprod_user_mapping",
        on_delete=models.CASCADE,
    )
    external_employee_id = models.PositiveIntegerField(null=True, blank=True, unique=True)
    external_user_id = models.PositiveIntegerField()
    external_username = models.CharField(max_length=150, unique=True)
    validation_status = models.CharField(
        max_length=20,
        choices=VALIDATION_STATUSES,
        default="draft",
    )
    active = models.BooleanField(default=True)
    validated_by = models.ForeignKey(
        User,
        related_name="validated_miningprod_user_mappings",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["external_username"]
        db_table = "MiningProdUserMapping"

    def __str__(self) -> str:
        return f"{self.user.get_username()} -> {self.external_username}"


class DataBrowserWriteAuditLog(models.Model):
    OPERATIONS = [
        ("create", "Create"),
        ("edit", "Edit"),
        ("delete", "Delete"),
        ("rollback_test", "Rollback Test"),
    ]
    STATUSES = [
        ("previewed", "Previewed"),
        ("validated", "Validated"),
        ("completed", "Completed"),
        ("failed", "Failed"),
        ("rejected", "Rejected"),
    ]

    request_id = models.UUIDField(unique=True)
    browser = models.ForeignKey(
        DataBrowser,
        related_name="write_audit_logs",
        on_delete=models.PROTECT,
    )
    mapping = models.ForeignKey(
        DataBrowserWriteMapping,
        related_name="audit_logs",
        on_delete=models.PROTECT,
    )
    user = models.ForeignKey(
        User,
        related_name="data_browser_write_audit_logs",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    operation = models.CharField(max_length=20, choices=OPERATIONS)
    dry_run = models.BooleanField(default=True)
    record_key = models.CharField(max_length=255, blank=True)
    input_hash = models.CharField(max_length=64)
    before_json = models.JSONField(default=dict, blank=True)
    after_json = models.JSONField(default=dict, blank=True)
    execution_plan_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUSES, default="previewed")
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "DataBrowserWriteAuditLog"
        indexes = [
            models.Index(fields=["browser", "operation", "created_at"], name="browser_write_audit_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.browser.name} {self.operation} {self.request_id}"


class AIConfigSection(models.Model):
    name = models.CharField(max_length=120)
    code = models.SlugField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    synonym_ambiguity_threshold = models.PositiveSmallIntegerField(default=90)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        db_table = "ai_config_sections"

    def __str__(self) -> str:
        return self.name


class AIQuestionExample(models.Model):
    section = models.ForeignKey(AIConfigSection, related_name="question_examples", on_delete=models.CASCADE)
    question_text = models.TextField()
    language = models.CharField(max_length=16, default="fr")
    expected_json_intent = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "question_text"]
        db_table = "ai_question_examples"

    def __str__(self) -> str:
        return f"{self.section.code}: {self.question_text[:50]}"


class AISynonym(models.Model):
    ENTITY_TYPES = [
        ("metric", "Metric"),
        ("minesite", "Minesite"),
        ("model", "Model"),
        ("family", "Family"),
        ("period", "Period"),
        ("customer", "Customer"),
        ("component", "Component"),
        ("measure", "Measure"),
        ("field", "Field"),
    ]

    section = models.ForeignKey(AIConfigSection, related_name="synonyms", on_delete=models.CASCADE)
    entity_type = models.CharField(max_length=20, choices=ENTITY_TYPES)
    canonical_value = models.CharField(max_length=255)
    synonym_value = models.CharField(max_length=255)
    language = models.CharField(max_length=16, default="fr")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["entity_type", "canonical_value", "synonym_value"]
        db_table = "ai_synonyms"
        constraints = [
            models.UniqueConstraint(
                fields=["section", "entity_type", "canonical_value", "synonym_value", "language"],
                name="unique_ai_synonym_entry",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.section.code} - {self.entity_type} - {self.synonym_value}"


class AIMetricMapping(models.Model):
    section = models.ForeignKey(AIConfigSection, related_name="metric_mappings", on_delete=models.CASCADE)
    metric_code = models.CharField(max_length=120)
    metric_label = models.CharField(max_length=255)
    powerbi_measure_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["metric_label", "metric_code"]
        db_table = "ai_metric_mapping"
        constraints = [
            models.UniqueConstraint(fields=["section", "metric_code"], name="unique_ai_metric_code_per_section"),
        ]

    def __str__(self) -> str:
        return f"{self.section.code} - {self.metric_code}"


class AIFilterMapping(models.Model):
    section = models.ForeignKey(AIConfigSection, related_name="filter_mappings", on_delete=models.CASCADE)
    filter_code = models.CharField(max_length=120)
    filter_label = models.CharField(max_length=255)
    powerbi_table_name = models.CharField(max_length=255)
    powerbi_column_name = models.CharField(max_length=255)
    data_type = models.CharField(max_length=50)
    is_required = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["filter_label", "filter_code"]
        db_table = "ai_filter_mapping"
        constraints = [
            models.UniqueConstraint(fields=["section", "filter_code"], name="unique_ai_filter_code_per_section"),
        ]

    def __str__(self) -> str:
        return f"{self.section.code} - {self.filter_code}"


class AIDaxTemplate(models.Model):
    section = models.ForeignKey(AIConfigSection, related_name="dax_templates", on_delete=models.CASCADE)
    template_name = models.CharField(max_length=255)
    template_code = models.CharField(max_length=120)
    dax_template = models.TextField()
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["template_name", "template_code"]
        db_table = "ai_dax_templates"
        constraints = [
            models.UniqueConstraint(fields=["section", "template_code"], name="unique_ai_dax_template_code_per_section"),
        ]

    def __str__(self) -> str:
        return f"{self.section.code} - {self.template_code}"


class AIResponseTemplate(models.Model):
    VALIDATION_STATUSES = [
        ("Draft", "Draft"),
        ("To Review", "To Review"),
        ("Validated", "Validated"),
        ("Rejected", "Rejected"),
    ]

    code = models.SlugField(max_length=120, unique=True)
    name = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    domain = models.CharField(max_length=80, default="machine_performance", db_index=True)
    supported_intent_types = models.JSONField(default=list, blank=True)
    supported_scope_types = models.JSONField(default=list, blank=True)
    primary_component = models.CharField(max_length=120, default="generic_result")
    component_order_json = models.JSONField(default=list, blank=True)
    required_data_fields_json = models.JSONField(default=list, blank=True)
    optional_data_fields_json = models.JSONField(default=list, blank=True)
    fallback_template_code = models.CharField(max_length=120, blank=True)
    active = models.BooleanField(default=True)
    validation_status = models.CharField(
        max_length=30,
        choices=VALIDATION_STATUSES,
        default="To Review",
    )
    version = models.CharField(max_length=30, default="1.0")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["domain", "name", "code"]
        db_table = "ai_response_template"

    def __str__(self) -> str:
        return f"{self.domain} - {self.code}"


class AIIntentResponseTemplateMapping(models.Model):
    VALIDATION_STATUSES = AIResponseTemplate.VALIDATION_STATUSES

    domain = models.CharField(max_length=80, default="machine_performance", db_index=True)
    intent_type = models.CharField(max_length=100, db_index=True)
    scope_type = models.CharField(max_length=100, blank=True, db_index=True)
    metric_code = models.CharField(max_length=120, blank=True, db_index=True)
    response_template = models.ForeignKey(
        AIResponseTemplate,
        related_name="intent_mappings",
        on_delete=models.PROTECT,
    )
    priority = models.PositiveIntegerField(default=100)
    active = models.BooleanField(default=True)
    validation_status = models.CharField(
        max_length=30,
        choices=VALIDATION_STATUSES,
        default="To Review",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "domain", "intent_type", "scope_type", "metric_code"]
        db_table = "ai_intent_response_template_mapping"
        constraints = [
            models.UniqueConstraint(
                fields=["domain", "intent_type", "scope_type", "metric_code", "response_template"],
                name="unique_ai_intent_response_template_mapping",
            ),
        ]

    def __str__(self) -> str:
        scope = self.scope_type or "any scope"
        return f"{self.intent_type} / {scope} -> {self.response_template.code}"


class AISemanticTable(models.Model):
    VALIDATION_STATUSES = [
        ("Draft", "Draft"),
        ("To Review", "To Review"),
        ("Validated", "Validated"),
        ("Rejected", "Rejected"),
        ("Deprecated", "Deprecated"),
        ("Imported", "Imported"),
    ]

    section = models.ForeignKey(AIConfigSection, related_name="semantic_tables", on_delete=models.CASCADE)
    table_name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    source_report = models.CharField(max_length=255, blank=True)
    dataset_id = models.CharField(max_length=128, blank=True)
    workspace_id = models.CharField(max_length=128, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    business_description = models.TextField(blank=True)
    validated_by_business = models.CharField(max_length=255, blank=True)
    validation_status = models.CharField(max_length=30, choices=VALIDATION_STATUSES, default="Imported")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_name", "table_name"]
        db_table = "ai_semantic_tables"
        constraints = [
            models.UniqueConstraint(fields=["section", "table_name"], name="unique_ai_semantic_table_per_section"),
        ]

    def __str__(self) -> str:
        return f"{self.section.code} - {self.table_name}"


class AISemanticColumn(models.Model):
    VALIDATION_STATUSES = AISemanticTable.VALIDATION_STATUSES

    section = models.ForeignKey(AIConfigSection, related_name="semantic_columns", on_delete=models.CASCADE)
    table_name = models.CharField(max_length=255)
    column_name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255)
    data_type = models.CharField(max_length=80, blank=True)
    description = models.TextField(blank=True)
    source_report = models.CharField(max_length=255, blank=True)
    dataset_id = models.CharField(max_length=128, blank=True)
    workspace_id = models.CharField(max_length=128, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    business_description = models.TextField(blank=True)
    validated_by_business = models.CharField(max_length=255, blank=True)
    validation_status = models.CharField(max_length=30, choices=VALIDATION_STATUSES, default="Imported")
    is_filter = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["table_name", "display_name", "column_name"]
        db_table = "ai_semantic_columns"
        constraints = [
            models.UniqueConstraint(fields=["section", "table_name", "column_name"], name="unique_ai_semantic_column_per_section"),
        ]

    def __str__(self) -> str:
        return f"{self.table_name}[{self.column_name}]"


class AISemanticMeasure(models.Model):
    VALIDATION_STATUSES = AISemanticTable.VALIDATION_STATUSES

    section = models.ForeignKey(AIConfigSection, related_name="semantic_measures", on_delete=models.CASCADE)
    measure_name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    dax_name = models.CharField(max_length=255)
    unit = models.CharField(max_length=80, blank=True)
    category = models.CharField(max_length=120, blank=True)
    source_report = models.CharField(max_length=255, blank=True)
    dataset_id = models.CharField(max_length=128, blank=True)
    workspace_id = models.CharField(max_length=128, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    business_description = models.TextField(blank=True)
    validated_by_business = models.CharField(max_length=255, blank=True)
    validation_status = models.CharField(max_length=30, choices=VALIDATION_STATUSES, default="Imported")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "display_name", "measure_name"]
        db_table = "ai_semantic_measures"
        constraints = [
            models.UniqueConstraint(fields=["section", "measure_name"], name="unique_ai_semantic_measure_per_section"),
        ]

    def __str__(self) -> str:
        return f"{self.section.code} - {self.measure_name}"


class AISemanticRelationship(models.Model):
    VALIDATION_STATUSES = AISemanticTable.VALIDATION_STATUSES

    section = models.ForeignKey(AIConfigSection, related_name="semantic_relationships", on_delete=models.CASCADE)
    parent_table = models.CharField(max_length=255)
    parent_column = models.CharField(max_length=255)
    child_table = models.CharField(max_length=255)
    child_column = models.CharField(max_length=255)
    relationship_type = models.CharField(max_length=120, blank=True)
    source_report = models.CharField(max_length=255, blank=True)
    dataset_id = models.CharField(max_length=128, blank=True)
    workspace_id = models.CharField(max_length=128, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    business_description = models.TextField(blank=True)
    validated_by_business = models.CharField(max_length=255, blank=True)
    validation_status = models.CharField(max_length=30, choices=VALIDATION_STATUSES, default="Imported")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["parent_table", "child_table"]
        db_table = "ai_semantic_relationships"

    def __str__(self) -> str:
        return f"{self.parent_table}[{self.parent_column}] -> {self.child_table}[{self.child_column}]"


class AIBusinessVocabulary(models.Model):
    section = models.ForeignKey(AIConfigSection, related_name="business_vocabulary", on_delete=models.CASCADE)
    business_term = models.CharField(max_length=255)
    business_definition = models.TextField()
    category = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "business_term"]
        db_table = "ai_business_vocabulary"
        constraints = [
            models.UniqueConstraint(fields=["section", "business_term"], name="unique_ai_business_term_per_section"),
        ]

    def __str__(self) -> str:
        return self.business_term


class AIFewShotExample(models.Model):
    section = models.ForeignKey(AIConfigSection, related_name="few_shot_examples", on_delete=models.CASCADE)
    question = models.TextField()
    expected_json_intent = models.JSONField(default=dict, blank=True)
    expected_dax = models.TextField(blank=True)
    expected_response = models.TextField(blank=True)
    explanation = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        db_table = "ai_few_shot_examples"

    def __str__(self) -> str:
        return self.question[:80]


class AIPromptTemplate(models.Model):
    PROMPT_TYPES = [
        ("intent_extraction", "Intent Extraction"),
        ("response_generation", "Response Generation"),
        ("business_explanation", "Business Explanation"),
        ("recommendation", "Recommendation"),
        ("executive_summary", "Executive Summary"),
        ("comparison", "Comparison"),
        ("trend_analysis", "Trend Analysis"),
    ]

    section = models.ForeignKey(AIConfigSection, related_name="prompt_templates", on_delete=models.CASCADE)
    prompt_type = models.CharField(max_length=80, choices=PROMPT_TYPES)
    template_name = models.CharField(max_length=255)
    prompt_template = models.TextField()
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["prompt_type", "template_name"]
        db_table = "ai_prompt_templates"
        constraints = [
            models.UniqueConstraint(fields=["section", "prompt_type", "template_name"], name="unique_ai_prompt_template"),
        ]

    def __str__(self) -> str:
        return f"{self.section.code} - {self.prompt_type}"


class AIBusinessRule(models.Model):
    section = models.ForeignKey(AIConfigSection, related_name="business_rules", on_delete=models.CASCADE)
    metric_code = models.CharField(max_length=120)
    rule_name = models.CharField(max_length=255)
    condition = models.TextField()
    action = models.TextField()
    default_value = models.CharField(max_length=255, blank=True)
    priority = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["metric_code", "priority", "rule_name"]
        db_table = "ai_business_rules"

    def __str__(self) -> str:
        return f"{self.metric_code} - {self.rule_name}"


class AIPowerBIPage(models.Model):
    section = models.ForeignKey(AIConfigSection, related_name="powerbi_pages", on_delete=models.CASCADE)
    page_name = models.CharField(max_length=255)
    report_name = models.CharField(max_length=255)
    report_id = models.CharField(max_length=128, blank=True)
    page_display_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_default_page = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["report_name", "page_display_name"]
        db_table = "ai_powerbi_pages"

    def __str__(self) -> str:
        return f"{self.report_name} - {self.page_display_name}"


POWERBI_VALIDATION_STATUSES = [
    ("Imported", "Imported"),
    ("To Review", "To Review"),
    ("Validated", "Validated"),
    ("Deprecated", "Deprecated"),
]


class PowerBIReport(models.Model):
    AUTHENTICATION_MODES = [
        ("app_owns_data", "App owns data"),
        ("user_owns_data", "User owns data"),
    ]
    LAUNCH_MODES = [
        ("generic_powerbi", "Generic Power BI viewer"),
    ]
    DISPLAY_OPTIONS = [
        ("fit_to_page", "Fit to page"),
        ("fit_to_width", "Fit to width"),
        ("actual_size", "Actual size"),
    ]
    BACKGROUND_TYPES = [
        ("default", "Default"),
        ("transparent", "Transparent"),
    ]
    OPEN_BEHAVIORS = [
        ("inside_mining360", "Inside Mining 360"),
        ("new_mining360_page", "New Mining 360 page"),
        ("fullscreen", "Full screen"),
        ("external_powerbi", "External Power BI"),
    ]
    CONFIGURATION_STATUSES = [
        ("incomplete", "Incomplete"),
        ("needs_review", "Needs Review"),
        ("complete", "Complete"),
        ("invalid", "Invalid"),
    ]
    VIEWER_PERIODS = [
        ("ytd", "Year to Date"),
        ("mtd", "Month to Date"),
        ("last_month", "Last Month"),
        ("last_30_days", "Last 30 Days"),
        ("last_12_months", "Last 12 Months"),
        ("custom", "Custom"),
    ]
    VIEWER_RESET_BEHAVIORS = [
        ("defaults", "Restore configured defaults"),
        ("clear", "Clear Mining 360 filters"),
    ]

    section = models.ForeignKey(AIConfigSection, related_name="interaction_reports", on_delete=models.CASCADE)
    workspace_id = models.CharField(max_length=128)
    report_id = models.CharField(max_length=128, unique=True)
    report_name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255)
    semantic_model_id = models.CharField(max_length=128, blank=True)
    embed_url = models.TextField(blank=True)
    description = models.TextField(blank=True)
    authentication_mode = models.CharField(
        max_length=30,
        choices=AUTHENTICATION_MODES,
        default="app_owns_data",
    )
    contains_powerapps_visual = models.BooleanField(default=False)
    requires_user_identity = models.BooleanField(default=False)
    allow_service_principal_metadata_access = models.BooleanField(default=True)
    required_entra_tenant_id = models.CharField(max_length=128, blank=True)
    powerapps_app_name = models.CharField(max_length=255, blank=True)
    powerapps_environment = models.CharField(max_length=255, blank=True)
    access_instructions = models.TextField(blank=True)
    launch_mode = models.CharField(max_length=40, choices=LAUNCH_MODES, default="generic_powerbi")
    opening_profile_name = models.CharField(max_length=120, blank=True, default="Standard Power BI")
    default_page_internal_name = models.CharField(max_length=255, blank=True)
    display_option = models.CharField(max_length=30, choices=DISPLAY_OPTIONS, default="fit_to_page")
    viewer_show_filter_bar = models.BooleanField(default=True)
    viewer_default_period = models.CharField(max_length=30, choices=VIEWER_PERIODS, default="ytd")
    viewer_available_periods = models.JSONField(default=list, blank=True)
    viewer_auto_apply_presets = models.BooleanField(default=True)
    viewer_custom_range_enabled = models.BooleanField(default=True)
    viewer_external_page_navigation = models.BooleanField(default=False)
    viewer_focus_mode_enabled = models.BooleanField(default=True)
    viewer_fullscreen_enabled = models.BooleanField(default=True)
    viewer_allow_open_powerbi = models.BooleanField(default=False)
    viewer_reset_behavior = models.CharField(
        max_length=20,
        choices=VIEWER_RESET_BEHAVIORS,
        default="defaults",
    )
    viewer_date_table = models.CharField(max_length=255, blank=True, default="Date")
    viewer_date_column = models.CharField(max_length=255, blank=True, default="Date")
    viewer_help_text = models.TextField(blank=True)
    filter_pane_visible = models.BooleanField(default=False)
    page_navigation_visible = models.BooleanField(default=True)
    bookmarks_pane_visible = models.BooleanField(default=False)
    background_type = models.CharField(max_length=20, choices=BACKGROUND_TYPES, default="default")
    default_rls_role = models.CharField(max_length=128, blank=True, default="Global")
    open_behavior = models.CharField(max_length=40, choices=OPEN_BEHAVIORS, default="inside_mining360")
    troubleshooting_enabled = models.BooleanField(default=True)
    troubleshooting_prompt = models.TextField(blank=True)
    troubleshooting_instructions = models.TextField(blank=True)
    supports_chatbot_navigation = models.BooleanField(default=True)
    supports_embedded_filtering = models.BooleanField(default=True)
    configuration_status = models.CharField(max_length=30, choices=CONFIGURATION_STATUSES, default="needs_review")
    configuration_version = models.PositiveIntegerField(default=1)
    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_test_status = models.CharField(max_length=30, blank=True)
    updated_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="updated_powerbi_report_configurations",
    )
    published_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="published_powerbi_report_configurations",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    validation_status = models.CharField(max_length=30, choices=POWERBI_VALIDATION_STATUSES, default="To Review")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["section__name", "display_name"]
        db_table = "ai_powerbi_interaction_reports"

    def __str__(self) -> str:
        return self.display_name

    @classmethod
    def opening_parameter_fields(cls):
        return (
            "authentication_mode",
            "contains_powerapps_visual",
            "requires_user_identity",
            "allow_service_principal_metadata_access",
            "required_entra_tenant_id",
            "launch_mode",
            "opening_profile_name",
            "default_page_internal_name",
            "display_option",
            "filter_pane_visible",
            "page_navigation_visible",
            "bookmarks_pane_visible",
            "background_type",
            "default_rls_role",
            "open_behavior",
            "supports_chatbot_navigation",
            "supports_embedded_filtering",
            "viewer_show_filter_bar",
            "viewer_default_period",
            "viewer_available_periods",
            "viewer_auto_apply_presets",
            "viewer_custom_range_enabled",
            "viewer_external_page_navigation",
            "viewer_focus_mode_enabled",
            "viewer_fullscreen_enabled",
            "viewer_allow_open_powerbi",
            "viewer_reset_behavior",
            "viewer_date_table",
            "viewer_date_column",
            "viewer_help_text",
        )

    def copy_opening_parameters_from(self, source):
        for field_name in self.opening_parameter_fields():
            setattr(self, field_name, getattr(source, field_name))

    def clean(self):
        super().clean()
        allowed_periods = {code for code, _label in self.VIEWER_PERIODS}
        periods = self.viewer_available_periods or ["ytd", "last_12_months", "custom"]
        if not isinstance(periods, list) or not periods or any(item not in allowed_periods for item in periods):
            raise ValidationError({"viewer_available_periods": "Select one or more governed period presets."})
        if self.viewer_default_period not in periods:
            raise ValidationError({"viewer_default_period": "The default period must be available in the viewer."})
        if "custom" in periods and self.viewer_custom_range_enabled and not (
            self.viewer_date_table and self.viewer_date_column
        ):
            raise ValidationError({"viewer_date_column": "Custom date ranges require a configured Power BI date mapping."})
        if self.requires_user_identity and self.authentication_mode != "user_owns_data":
            raise ValidationError({
                "authentication_mode": "Reports requiring a user identity must use User owns data."
            })
        if self.contains_powerapps_visual and self.authentication_mode != "user_owns_data":
            raise ValidationError({
                "authentication_mode": "Power Apps visuals require User owns data embedding."
            })


class ReportContextParameter(models.Model):
    SOURCES = [
        ("chatbot", "Chatbot context"),
        ("homepage", "Homepage context"),
        ("reporting_hub", "Reporting Hub context"),
        ("query_string", "Query string"),
        ("user_profile", "User profile"),
        ("fixed_default", "Fixed default"),
        ("powerbi_filter", "Power BI filter"),
        ("powerapps_context", "Power Apps launch context"),
    ]
    DATA_TYPES = [("text", "Text"), ("number", "Number"), ("date", "Date"), ("boolean", "Boolean")]
    OPERATORS = [("In", "In"), ("Equals", "Equals"), ("Contains", "Contains")]

    report = models.ForeignKey(PowerBIReport, related_name="context_parameters", on_delete=models.CASCADE)
    code = models.SlugField(max_length=120)
    display_name = models.CharField(max_length=180)
    source = models.CharField(max_length=40, choices=SOURCES)
    data_type = models.CharField(max_length=20, choices=DATA_TYPES, default="text")
    required = models.BooleanField(default=False)
    default_value = models.CharField(max_length=500, blank=True)
    powerbi_table = models.CharField(max_length=255, blank=True)
    powerbi_column = models.CharField(max_length=255, blank=True)
    operator = models.CharField(max_length=20, choices=OPERATORS, default="In")
    supports_multiple_values = models.BooleanField(default=False)
    display_order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "report_context_parameters"
        ordering = ["display_order", "display_name"]
        constraints = [models.UniqueConstraint(fields=["report", "code"], name="unique_report_context_parameter")]


class ReportConfigurationVersion(models.Model):
    report = models.ForeignKey(PowerBIReport, related_name="configuration_versions", on_delete=models.CASCADE)
    version = models.PositiveIntegerField()
    payload_snapshot = models.JSONField(default=dict)
    change_summary = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    published = models.BooleanField(default=False)
    restored_from_version = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "report_configuration_versions"
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["report", "version"], name="unique_report_configuration_version")]


class ReportConfigurationTestRun(models.Model):
    STATUSES = [("passed", "Passed"), ("warning", "Warning"), ("failed", "Failed")]
    report = models.ForeignKey(PowerBIReport, related_name="configuration_test_runs", on_delete=models.CASCADE)
    test_code = models.CharField(max_length=120)
    status = models.CharField(max_length=20, choices=STATUSES)
    duration_ms = models.PositiveIntegerField(default=0)
    result_json = models.JSONField(default=dict)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "report_configuration_test_runs"
        ordering = ["-created_at"]


class ReportConfigurationAuditLog(models.Model):
    report = models.ForeignKey(PowerBIReport, related_name="configuration_audit_logs", on_delete=models.CASCADE)
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=80)
    before_json = models.JSONField(default=dict)
    after_json = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "report_configuration_audit_logs"
        ordering = ["-created_at"]


class PowerBIAuthenticationAuditLog(models.Model):
    EVENT_TYPES = [
        ("connect_started", "Connect started"),
        ("connect_succeeded", "Connect succeeded"),
        ("connect_failed", "Connect failed"),
        ("token_refreshed", "Token refreshed"),
        ("embed_requested", "Embed requested"),
        ("embed_denied", "Embed denied"),
        ("disconnected", "Disconnected"),
    ]

    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="powerbi_authentication_events",
    )
    report = models.ForeignKey(
        PowerBIReport,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="authentication_events",
    )
    event_type = models.CharField(max_length=40, choices=EVENT_TYPES)
    status = models.CharField(max_length=30, default="success")
    error_code = models.CharField(max_length=120, blank=True)
    message = models.TextField(blank=True)
    metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "PowerBIAuthenticationAuditLog"
        indexes = [
            models.Index(fields=["user", "created_at"], name="pbi_auth_user_time_idx"),
            models.Index(fields=["report", "created_at"], name="pbi_auth_report_time_idx"),
        ]


class UserExternalIdentity(models.Model):
    PROVIDERS = [("microsoft_entra", "Microsoft Entra")]
    MAPPING_STATUSES = [
        ("pending", "Pending"),
        ("validated", "Validated"),
        ("conflict", "Conflict"),
        ("disabled", "Disabled"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="external_identities")
    provider = models.CharField(max_length=40, choices=PROVIDERS, default="microsoft_entra")
    tenant_id = models.CharField(max_length=128)
    external_object_id = models.CharField(max_length=128)
    upn = models.EmailField(blank=True)
    windows_identity = models.CharField(max_length=255, blank=True)
    display_name = models.CharField(max_length=255, blank=True)
    mapping_status = models.CharField(max_length=20, choices=MAPPING_STATUSES, default="pending")
    last_verified_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "UserExternalIdentity"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "tenant_id", "external_object_id"],
                name="unique_external_identity_object",
            ),
        ]
        indexes = [models.Index(fields=["user", "provider", "active"], name="ext_identity_user_idx")]


class ReportingReportPreference(models.Model):
    CATEGORIES = [
        ("fleet_performance", "Fleet Performance"),
        ("maintenance_reliability", "Maintenance & Reliability"),
        ("operations", "Operations"),
        ("fuel_connectivity", "Fuel & Connectivity"),
        ("parts_aftermarket", "Parts & Aftermarket"),
        ("management_reports", "Management Reports"),
        ("lifecycle_cost", "Lifecycle Cost"),
        ("customer_performance", "Customer Performance"),
        ("other", "Other"),
    ]
    THUMBNAIL_STATUSES = [
        ("fallback", "Category fallback"),
        ("configured", "Configured"),
        ("pending", "Pending"),
        ("failed", "Failed"),
    ]
    THUMBNAIL_SOURCES = [
        ("automatic", "Automatic fallback"),
        ("manual_thumbnail", "Manual thumbnail"),
        ("powerbi_screenshot", "Power BI screenshot"),
        ("report_illustration", "Report illustration"),
        ("category_illustration", "Category illustration"),
    ]
    ACCENTS = [
        ("yellow", "Mining 360 Yellow"),
        ("emerald", "Emerald"),
        ("blue", "Blue"),
        ("purple", "Purple"),
        ("cyan", "Cyan"),
        ("amber", "Amber"),
        ("rose", "Rose"),
        ("slate", "Slate"),
    ]
    CARD_STYLES = [("standard", "Standard"), ("compact", "Compact")]
    VISUAL_IDENTITY_STATUSES = [
        ("complete", "Complete"),
        ("partial", "Partial"),
        ("default", "Default"),
        ("needs_review", "Needs Review"),
        ("invalid", "Invalid"),
    ]

    report_id = models.CharField(max_length=128, unique=True)
    report_name = models.CharField(max_length=255, blank=True)
    display_name = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    short_description = models.CharField(max_length=180, blank=True)
    long_description = models.TextField(blank=True)
    business_purpose = models.TextField(blank=True)
    category = models.CharField(max_length=64, choices=CATEGORIES, default="other")
    secondary_categories_json = models.JSONField(default=list, blank=True)
    tags_json = models.JSONField(default=list, blank=True)
    business_owner = models.CharField(max_length=255, blank=True)
    technical_owner = models.CharField(max_length=255, blank=True)
    thumbnail_url = models.URLField(blank=True)
    thumbnail = models.FileField(upload_to="report_visuals/thumbnails/%Y/%m/", blank=True)
    selected_visual_asset = models.ForeignKey(
        "ReportVisualAsset",
        related_name="report_preferences",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    powerbi_screenshot_url = models.URLField(blank=True)
    thumbnail_source = models.CharField(max_length=32, choices=THUMBNAIL_SOURCES, default="automatic")
    thumbnail_status = models.CharField(
        max_length=20,
        choices=THUMBNAIL_STATUSES,
        default="fallback",
    )
    thumbnail_updated_at = models.DateTimeField(null=True, blank=True)
    thumbnail_focal_x = models.PositiveSmallIntegerField(default=50)
    thumbnail_focal_y = models.PositiveSmallIntegerField(default=50)
    illustration_code = models.CharField(max_length=64, blank=True)
    icon_code = models.CharField(max_length=64, blank=True)
    accent_code = models.CharField(max_length=20, choices=ACCENTS, blank=True)
    card_badge = models.CharField(max_length=40, blank=True)
    card_style = models.CharField(max_length=20, choices=CARD_STYLES, default="standard")
    visual_identity_status = models.CharField(
        max_length=24,
        choices=VISUAL_IDENTITY_STATUSES,
        default="needs_review",
    )
    featured = models.BooleanField(default=False)
    freshness_threshold_hours = models.PositiveIntegerField(null=True, blank=True)
    validation_status = models.CharField(
        max_length=30,
        choices=POWERBI_VALIDATION_STATUSES,
        default="To Review",
    )
    is_visible = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    updated_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_reporting_report_preferences",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "display_name", "report_name"]
        db_table = "reporting_report_preferences"

    def __str__(self) -> str:
        return self.display_name or self.report_name or self.report_id

    def clean(self):
        super().clean()
        if not 0 <= self.thumbnail_focal_x <= 100 or not 0 <= self.thumbnail_focal_y <= 100:
            raise ValidationError("Thumbnail focal position must be between 0 and 100.")


class ReportCategory(models.Model):
    code = models.SlugField(max_length=64, unique=True)
    display_name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    icon_code = models.CharField(max_length=64, blank=True)
    illustration_code = models.CharField(max_length=64, blank=True)
    accent_code = models.CharField(max_length=20, choices=ReportingReportPreference.ACCENTS, default="slate")
    display_order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    validation_status = models.CharField(
        max_length=30,
        choices=POWERBI_VALIDATION_STATUSES,
        default="To Review",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "report_categories"
        ordering = ["display_order", "display_name"]

    def __str__(self):
        return self.display_name


class ReportVisualAsset(models.Model):
    ASSET_TYPES = [
        ("report_thumbnail", "Report thumbnail"),
        ("report_illustration", "Report illustration"),
        ("category_illustration", "Category illustration"),
        ("category_icon", "Category icon"),
    ]

    name = models.CharField(max_length=180)
    asset_type = models.CharField(max_length=32, choices=ASSET_TYPES)
    file = models.FileField(upload_to="report_visuals/assets/%Y/%m/")
    category = models.ForeignKey(
        ReportCategory,
        related_name="visual_assets",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    illustration_code = models.CharField(max_length=64, blank=True)
    mime_type = models.CharField(max_length=80, blank=True)
    file_size = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    validation_status = models.CharField(
        max_length=30,
        choices=POWERBI_VALIDATION_STATUSES,
        default="To Review",
    )
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "report_visual_assets"
        ordering = ["name"]

    def __str__(self):
        return self.name


class UserReportFavorite(models.Model):
    user = models.ForeignKey(User, related_name="report_favorites", on_delete=models.CASCADE)
    report = models.ForeignKey(
        ReportingReportPreference,
        related_name="user_favorites",
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reporting_user_favorites"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "report"], name="unique_user_report_favorite"),
        ]


class UserReportActivity(models.Model):
    SOURCES = [
        ("reporting_hub", "Reporting Hub"),
        ("chatbot", "Chatbot"),
        ("homepage", "Homepage"),
        ("direct", "Direct"),
    ]

    user = models.ForeignKey(User, related_name="report_activities", on_delete=models.CASCADE)
    report = models.ForeignKey(
        ReportingReportPreference,
        related_name="user_activities",
        on_delete=models.CASCADE,
    )
    opened_at = models.DateTimeField(auto_now_add=True)
    launch_mode = models.CharField(max_length=40, blank=True)
    source = models.CharField(max_length=30, choices=SOURCES, default="reporting_hub")
    context_json = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "reporting_user_activity"
        ordering = ["-opened_at"]
        indexes = [
            models.Index(fields=["user", "-opened_at"], name="report_activity_user_time_idx"),
            models.Index(fields=["report", "-opened_at"], name="report_act_report_time_idx"),
        ]


class PowerBIPage(models.Model):
    report = models.ForeignKey(PowerBIReport, related_name="pages", on_delete=models.CASCADE)
    page_internal_name = models.CharField(max_length=255)
    page_display_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    page_order = models.PositiveIntegerField(default=0)
    section = models.ForeignKey(AIConfigSection, related_name="interaction_pages", on_delete=models.CASCADE)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    validation_status = models.CharField(max_length=30, choices=POWERBI_VALIDATION_STATUSES, default="To Review")
    imported_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["report", "page_order", "page_display_name"]
        db_table = "ai_powerbi_interaction_pages"
        constraints = [
            models.UniqueConstraint(fields=["report", "page_internal_name"], name="unique_interaction_page_per_report"),
        ]

    def __str__(self) -> str:
        return f"{self.report.display_name} - {self.page_display_name}"


class PowerBIVisual(models.Model):
    page = models.ForeignKey(PowerBIPage, related_name="visuals", on_delete=models.CASCADE)
    visual_internal_name = models.CharField(max_length=255)
    visual_title = models.CharField(max_length=255, blank=True)
    visual_type = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    supported_actions = models.JSONField(default=list, blank=True)
    section = models.ForeignKey(AIConfigSection, related_name="interaction_visuals", on_delete=models.CASCADE)
    related_metric_code = models.CharField(max_length=120, blank=True)
    is_primary_visual = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    validation_status = models.CharField(max_length=30, choices=POWERBI_VALIDATION_STATUSES, default="To Review")
    imported_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["page", "visual_title", "visual_internal_name"]
        db_table = "ai_powerbi_interaction_visuals"
        constraints = [
            models.UniqueConstraint(fields=["page", "visual_internal_name"], name="unique_interaction_visual_per_page"),
        ]


class PowerBISlicer(models.Model):
    page = models.ForeignKey(PowerBIPage, related_name="slicers", on_delete=models.CASCADE)
    visual = models.ForeignKey(PowerBIVisual, related_name="slicer_configurations", null=True, blank=True, on_delete=models.SET_NULL)
    slicer_internal_name = models.CharField(max_length=255)
    slicer_title = models.CharField(max_length=255, blank=True)
    powerbi_table_name = models.CharField(max_length=255)
    powerbi_column_name = models.CharField(max_length=255)
    filter_code = models.CharField(max_length=120)
    value_mapping = models.JSONField(default=dict, blank=True)
    data_type = models.CharField(max_length=50, default="Text")
    supports_multiple_values = models.BooleanField(default=False)
    is_required = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    validation_status = models.CharField(max_length=30, choices=POWERBI_VALIDATION_STATUSES, default="To Review")
    imported_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["page", "slicer_title", "slicer_internal_name"]
        db_table = "ai_powerbi_interaction_slicers"
        constraints = [
            models.UniqueConstraint(fields=["page", "slicer_internal_name"], name="unique_interaction_slicer_per_page"),
        ]


class KPIPageMapping(models.Model):
    section = models.ForeignKey(AIConfigSection, related_name="kpi_page_mappings", on_delete=models.CASCADE)
    metric_code = models.CharField(max_length=120)
    report = models.ForeignKey(PowerBIReport, related_name="kpi_page_mappings", on_delete=models.CASCADE)
    page = models.ForeignKey(PowerBIPage, related_name="kpi_mappings", on_delete=models.CASCADE)
    priority = models.PositiveIntegerField(default=100)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["section", "metric_code", "priority"]
        db_table = "ai_kpi_page_mappings"
        constraints = [
            models.UniqueConstraint(fields=["section", "metric_code", "page"], name="unique_kpi_page_mapping"),
        ]


class KPIVisualMapping(models.Model):
    section = models.ForeignKey(AIConfigSection, related_name="kpi_visual_mappings", on_delete=models.CASCADE)
    metric_code = models.CharField(max_length=120)
    page = models.ForeignKey(PowerBIPage, related_name="kpi_visual_mappings", on_delete=models.CASCADE)
    visual = models.ForeignKey(PowerBIVisual, related_name="kpi_mappings", on_delete=models.CASCADE)
    interaction_action = models.CharField(max_length=50, default="focus")
    priority = models.PositiveIntegerField(default=100)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["section", "metric_code", "priority"]
        db_table = "ai_kpi_visual_mappings"
        constraints = [
            models.UniqueConstraint(fields=["section", "metric_code", "visual"], name="unique_kpi_visual_mapping"),
        ]


class IntentNavigationMapping(models.Model):
    section = models.ForeignKey(AIConfigSection, related_name="intent_navigation_mappings", on_delete=models.CASCADE)
    intent_type = models.CharField(max_length=80)
    metric_code = models.CharField(max_length=120, blank=True)
    report = models.ForeignKey(PowerBIReport, related_name="intent_mappings", on_delete=models.CASCADE)
    page = models.ForeignKey(PowerBIPage, related_name="intent_mappings", null=True, blank=True, on_delete=models.SET_NULL)
    visual = models.ForeignKey(PowerBIVisual, related_name="intent_mappings", null=True, blank=True, on_delete=models.SET_NULL)
    priority = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["section", "intent_type", "priority"]
        db_table = "ai_intent_navigation_mappings"


class SupportedPowerBIAction(models.Model):
    action_code = models.SlugField(max_length=80, unique=True)
    display_name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    target_type = models.CharField(max_length=50, default="visual")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["target_type", "display_name"]
        db_table = "ai_powerbi_supported_actions"


class AIConversationContext(models.Model):
    conversation_id = models.CharField(max_length=128, db_index=True)
    user = models.ForeignKey(User, related_name="ai_conversation_contexts", null=True, blank=True, on_delete=models.SET_NULL)
    validated_intent = models.JSONField(default=dict, blank=True)
    active_agent = models.CharField(max_length=100, blank=True, db_index=True)
    last_agent = models.CharField(max_length=100, blank=True)
    active_intent = models.CharField(max_length=120, blank=True)
    performance_context = models.JSONField(default=dict, blank=True)
    knowledge_context = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        db_table = "ai_conversation_contexts"
        constraints = [
            models.UniqueConstraint(fields=["conversation_id", "user"], name="unique_ai_context_per_user"),
        ]


class AIConversation(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("archived", "Archived"),
        ("deleted", "Deleted"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, related_name="ai_conversations", on_delete=models.CASCADE)
    title = models.CharField(max_length=200, default="New conversation")
    title_is_manual = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active", db_index=True)
    active_agent_code = models.CharField(max_length=100, blank=True)
    last_agent_code = models.CharField(max_length=100, blank=True)
    conversation_context_json = models.JSONField(default=dict, blank=True)
    performance_context_json = models.JSONField(default=dict, blank=True)
    knowledge_context_json = models.JSONField(default=dict, blank=True)
    active_analysis_json = models.JSONField(default=dict, blank=True)
    message_count = models.PositiveIntegerField(default=0)
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_conversations"
        ordering = ["-last_message_at", "-updated_at"]
        indexes = [
            models.Index(
                fields=["user", "status", "-last_message_at"],
                name="ai_conv_user_status_activity",
            ),
        ]


class AIConversationMessage(models.Model):
    ROLE_CHOICES = [
        ("user", "User"),
        ("assistant", "Assistant"),
        ("system", "System"),
        ("tool", "Tool"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("completed", "Completed"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        AIConversation,
        related_name="messages",
        on_delete=models.CASCADE,
    )
    role = models.CharField(max_length=30, choices=ROLE_CHOICES)
    message_type = models.CharField(max_length=50, default="text")
    content = models.TextField(blank=True)
    language = models.CharField(max_length=10, blank=True)
    agent_code = models.CharField(max_length=100, blank=True)
    intent_code = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="completed", db_index=True)
    client_message_id = models.CharField(max_length=128, null=True, blank=True)
    request_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    metadata_json = models.JSONField(default=dict, blank=True)
    parent_message = models.ForeignKey(
        "self",
        related_name="response_versions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    version_number = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_conversation_messages"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["conversation", "-created_at"], name="ai_msg_conv_created"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "client_message_id"],
                condition=Q(client_message_id__isnull=False),
                name="unique_ai_client_message_per_conversation",
            ),
        ]


class AIConversationArtifact(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("superseded", "Superseded"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        AIConversation,
        related_name="artifacts",
        on_delete=models.CASCADE,
    )
    message = models.ForeignKey(
        AIConversationMessage,
        related_name="artifacts",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    artifact_type = models.CharField(max_length=80, db_index=True)
    title = models.CharField(max_length=255, blank=True)
    payload_json = models.JSONField(default=dict, blank=True)
    source_type = models.CharField(max_length=80, blank=True)
    source_reference = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    artifact_version = models.PositiveIntegerField(default=1)
    refreshed_at = models.DateTimeField(null=True, blank=True)
    supersedes_artifact = models.ForeignKey(
        "self",
        related_name="newer_versions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_conversation_artifacts"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["conversation", "message"], name="ai_art_conv_message"),
            models.Index(fields=["conversation", "artifact_type"], name="ai_art_conv_type"),
        ]


AI_AGENT_VALIDATION_STATUSES = [
    ("Draft", "Draft"),
    ("To Review", "To Review"),
    ("Validated", "Validated"),
    ("Rejected", "Rejected"),
]


class AIAgent(models.Model):
    AGENT_TYPES = [
        ("machine_performance", "Machine Performance"),
        ("mining_knowledge", "Mining Knowledge"),
    ]
    ROUTING_MODES = [
        ("automatic", "Automatic"),
        ("manual", "Manual"),
        ("disabled", "Disabled"),
    ]

    code = models.SlugField(max_length=100, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    agent_type = models.CharField(max_length=50, choices=AGENT_TYPES)
    system_instructions = models.TextField(blank=True)
    response_instructions = models.TextField(blank=True)
    clarification_instructions = models.TextField(blank=True)
    combined_execution_instructions = models.TextField(blank=True)
    default_language = models.CharField(max_length=10, default="auto")
    routing_mode = models.CharField(max_length=20, choices=ROUTING_MODES, default="automatic")
    routing_keywords = models.JSONField(default=list, blank=True)
    exclusion_keywords = models.JSONField(default=list, blank=True)
    clarification_message = models.TextField(blank=True)
    priority = models.PositiveIntegerField(default=50)
    minimum_confidence = models.DecimalField(max_digits=5, decimal_places=2, default=85)
    active = models.BooleanField(default=True, db_index=True)
    is_default = models.BooleanField(default=False)
    allow_combined_execution = models.BooleanField(default=True)
    validation_status = models.CharField(
        max_length=20,
        choices=AI_AGENT_VALIDATION_STATUSES,
        default="To Review",
        db_index=True,
    )
    version = models.CharField(max_length=50, default="1.0")
    owner = models.CharField(max_length=150, blank=True)
    created_by = models.ForeignKey(
        User, null=True, blank=True, related_name="created_ai_agents", on_delete=models.SET_NULL
    )
    updated_by = models.ForeignKey(
        User, null=True, blank=True, related_name="updated_ai_agents", on_delete=models.SET_NULL
    )
    validated_by = models.ForeignKey(
        User, null=True, blank=True, related_name="validated_ai_agents", on_delete=models.SET_NULL
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "name"]
        db_table = "AIAgent"
        permissions = [
            ("validate_ai_agent", "Can validate AI agents"),
            ("test_ai_agent", "Can test AI agents"),
            ("view_agent_logs", "Can view AI agent logs"),
            ("view_agent_costs", "Can view AI agent costs"),
            ("manage_agent_router", "Can manage the AI agent router"),
        ]

    def __str__(self):
        return self.name


class AIAgentCapability(models.Model):
    agent = models.ForeignKey(AIAgent, related_name="capabilities", on_delete=models.CASCADE)
    capability_code = models.SlugField(max_length=120)
    display_name = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    enabled = models.BooleanField(default=True)
    configuration_json = models.JSONField(default=dict, blank=True)
    priority = models.PositiveIntegerField(default=50)
    validation_status = models.CharField(
        max_length=20, choices=AI_AGENT_VALIDATION_STATUSES, default="To Review"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "display_name"]
        db_table = "AIAgentCapability"
        constraints = [
            models.UniqueConstraint(
                fields=["agent", "capability_code"], name="unique_ai_agent_capability"
            ),
        ]


class AIAgentDataSource(models.Model):
    agent = models.ForeignKey(AIAgent, related_name="data_sources", on_delete=models.CASCADE)
    source_type = models.CharField(max_length=80, db_index=True)
    source_reference = models.CharField(max_length=500)
    source_name = models.CharField(max_length=255)
    enabled = models.BooleanField(default=True)
    read_only = models.BooleanField(default=True)
    priority = models.PositiveIntegerField(default=50)
    filters_json = models.JSONField(default=dict, blank=True)
    validation_status = models.CharField(
        max_length=20, choices=AI_AGENT_VALIDATION_STATUSES, default="To Review"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "source_name"]
        db_table = "AIAgentDataSource"
        constraints = [
            models.UniqueConstraint(
                fields=["agent", "source_type", "source_reference"],
                name="unique_ai_agent_data_source",
            ),
        ]


class AIAgentIntent(models.Model):
    agent = models.ForeignKey(AIAgent, related_name="intents", on_delete=models.CASCADE)
    intent_code = models.SlugField(max_length=120)
    display_name = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    examples_json = models.JSONField(default=list, blank=True)
    required_entities_json = models.JSONField(default=list, blank=True)
    optional_entities_json = models.JSONField(default=list, blank=True)
    priority = models.PositiveIntegerField(default=50)
    enabled = models.BooleanField(default=True)
    validation_status = models.CharField(
        max_length=20, choices=AI_AGENT_VALIDATION_STATUSES, default="To Review"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "display_name"]
        db_table = "AIAgentIntent"
        constraints = [
            models.UniqueConstraint(fields=["agent", "intent_code"], name="unique_ai_agent_intent"),
        ]


class AIAgentTool(models.Model):
    agent = models.ForeignKey(AIAgent, related_name="tools", on_delete=models.CASCADE)
    tool_code = models.SlugField(max_length=120)
    display_name = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    service_path = models.CharField(max_length=500)
    enabled = models.BooleanField(default=True)
    requires_confirmation = models.BooleanField(default=False)
    timeout_seconds = models.PositiveIntegerField(default=120)
    priority = models.PositiveIntegerField(default=50)
    configuration_json = models.JSONField(default=dict, blank=True)
    validation_status = models.CharField(
        max_length=20, choices=AI_AGENT_VALIDATION_STATUSES, default="To Review"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "display_name"]
        db_table = "AIAgentTool"
        constraints = [
            models.UniqueConstraint(fields=["agent", "tool_code"], name="unique_ai_agent_tool"),
        ]


class AIAgentPrompt(models.Model):
    PROMPT_TYPES = [
        ("system", "System"),
        ("intent", "Intent"),
        ("response", "Response"),
        ("clarification", "Clarification"),
        ("combined", "Combined"),
    ]
    agent = models.ForeignKey(AIAgent, related_name="prompts", on_delete=models.CASCADE)
    prompt_code = models.SlugField(max_length=120)
    prompt_type = models.CharField(max_length=30, choices=PROMPT_TYPES)
    name = models.CharField(max_length=180)
    content = models.TextField()
    version = models.CharField(max_length=50, default="1.0")
    enabled = models.BooleanField(default=True)
    validation_status = models.CharField(
        max_length=20, choices=AI_AGENT_VALIDATION_STATUSES, default="To Review"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["prompt_type", "name"]
        db_table = "AIAgentPrompt"
        constraints = [
            models.UniqueConstraint(fields=["agent", "prompt_code"], name="unique_ai_agent_prompt"),
        ]


class AIAgentPermission(models.Model):
    agent = models.OneToOneField(AIAgent, related_name="permission_config", on_delete=models.CASCADE)
    allowed_roles = models.ManyToManyField(Group, related_name="permitted_ai_agents", blank=True)
    allowed_users = models.ManyToManyField(User, related_name="permitted_ai_agents", blank=True)
    allowed_minesites = models.JSONField(default=list, blank=True)
    allowed_customers = models.JSONField(default=list, blank=True)
    can_export = models.BooleanField(default=False)
    can_access_comments = models.BooleanField(default=False)
    can_access_debug = models.BooleanField(default=False)
    configuration_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "AIAgentPermission"


class AIAgentRoutingConfiguration(models.Model):
    FEATURE_MODES = [
        ("Disabled", "Disabled"),
        ("Admin Only", "Admin Only"),
        ("Pilot Users", "Pilot Users"),
        ("Production", "Production"),
    ]
    name = models.CharField(max_length=120, unique=True, default="Default")
    feature_mode = models.CharField(max_length=20, choices=FEATURE_MODES, default="Admin Only")
    routing_enabled = models.BooleanField(default=True)
    deterministic_routing_enabled = models.BooleanField(default=True)
    ai_fallback_enabled = models.BooleanField(default=False)
    default_agent = models.ForeignKey(
        AIAgent, null=True, blank=True, related_name="default_router_configs", on_delete=models.SET_NULL
    )
    minimum_confidence = models.DecimalField(max_digits=5, decimal_places=2, default=85)
    combined_execution_enabled = models.BooleanField(default=True)
    manual_selection_enabled = models.BooleanField(default=True)
    clarification_behavior = models.TextField(blank=True)
    routing_timeout_seconds = models.PositiveIntegerField(default=30)
    routing_prompt = models.TextField(blank=True)
    pilot_users = models.ManyToManyField(User, related_name="pilot_agent_router_configs", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "AIAgentRoutingConfiguration"


class AIAgentRoutingRule(models.Model):
    SELECTED_AGENT_CHOICES = [
        ("machine_performance", "Machine Performance"),
        ("mining_knowledge", "Mining Knowledge"),
        ("combined", "Combined"),
        ("clarification_required", "Clarification Required"),
    ]
    rule_code = models.SlugField(max_length=120, unique=True)
    name = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    condition_json = models.JSONField(default=dict, blank=True)
    selected_agent = models.CharField(max_length=50, choices=SELECTED_AGENT_CHOICES)
    priority = models.PositiveIntegerField(default=50)
    active = models.BooleanField(default=True)
    validation_status = models.CharField(
        max_length=20, choices=AI_AGENT_VALIDATION_STATUSES, default="To Review"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "name"]
        db_table = "AIAgentRoutingRule"


class AIAgentExecutionLog(models.Model):
    STATUS_CHOICES = [
        ("Completed", "Completed"),
        ("Partial", "Partial"),
        ("Clarification Required", "Clarification Required"),
        ("Failed", "Failed"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    conversation_id = models.CharField(max_length=255, blank=True, db_index=True)
    question = models.TextField()
    selected_agent = models.ForeignKey(
        AIAgent, null=True, blank=True, related_name="execution_logs", on_delete=models.SET_NULL
    )
    selected_agent_code = models.CharField(max_length=100, blank=True, db_index=True)
    routing_method = models.CharField(max_length=40, blank=True)
    routing_confidence = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    routing_reason = models.TextField(blank=True)
    matched_rules_json = models.JSONField(default=list, blank=True)
    intent = models.CharField(max_length=120, blank=True, db_index=True)
    entities_json = models.JSONField(default=dict, blank=True)
    tools_used_json = models.JSONField(default=list, blank=True)
    sources_used_json = models.JSONField(default=list, blank=True)
    execution_status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="Completed")
    response_time_ms = models.PositiveIntegerField(default=0)
    input_tokens = models.PositiveBigIntegerField(default=0)
    output_tokens = models.PositiveBigIntegerField(default=0)
    estimated_cost = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    error_code = models.CharField(max_length=160, blank=True)
    error_message = models.TextField(blank=True)
    parent_execution = models.ForeignKey(
        "self", null=True, blank=True, related_name="child_executions", on_delete=models.SET_NULL
    )
    execution_order = models.PositiveSmallIntegerField(default=1)
    is_test = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "AIAgentExecutionLog"


AI_PROVIDER_CAPABILITIES = [
    "text_generation",
    "structured_output",
    "tool_calling",
    "embeddings",
    "audio_transcription",
    "text_to_speech",
    "vision",
    "document_analysis",
    "streaming",
    "long_context",
    "json_mode",
    "function_calling",
]


class AIProvider(models.Model):
    PROVIDER_TYPES = [
        ("openai", "OpenAI"),
        ("anthropic_claude", "Claude AI"),
        ("google_gemini", "Google Gemini"),
        ("glm_5", "GLM-5"),
        ("custom", "Custom Provider"),
    ]
    AUTH_TYPES = [
        ("api_key", "API Key"),
        ("bearer_token", "Bearer Token"),
        ("oauth2", "OAuth 2.0"),
        ("custom_header", "Custom Header"),
    ]
    STATUS_CHOICES = [
        ("not_configured", "Not Configured"),
        ("active", "Healthy"),
        ("inactive", "Inactive"),
        ("degraded", "Degraded"),
        ("unavailable", "Unavailable"),
        ("invalid_credentials", "Invalid Credentials"),
    ]
    SELECTION_MODES = [
        ("fixed", "Fixed"),
        ("priority", "Priority Based"),
        ("cost", "Cost Optimized"),
        ("performance", "Performance Optimized"),
        ("manual", "Manual"),
    ]

    code = models.SlugField(max_length=100, unique=True)
    name = models.CharField(max_length=150)
    provider_type = models.CharField(max_length=50, choices=PROVIDER_TYPES)
    description = models.TextField(blank=True)
    base_url = models.URLField(blank=True)
    api_version = models.CharField(max_length=100, blank=True)
    auth_type = models.CharField(max_length=30, choices=AUTH_TYPES, default="api_key")
    priority = models.PositiveIntegerField(default=50, db_index=True)
    selection_mode = models.CharField(max_length=20, choices=SELECTION_MODES, default="priority")
    is_default = models.BooleanField(default=False, db_index=True)
    active = models.BooleanField(default=False, db_index=True)
    allow_fallback = models.BooleanField(default=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="not_configured", db_index=True)
    timeout_seconds = models.PositiveIntegerField(default=60)
    retry_count = models.PositiveIntegerField(default=2)
    retry_backoff_seconds = models.PositiveIntegerField(default=2)
    requests_per_minute = models.PositiveIntegerField(null=True, blank=True)
    tokens_per_minute = models.PositiveIntegerField(null=True, blank=True)
    maximum_concurrent_requests = models.PositiveIntegerField(default=5)
    daily_budget = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    monthly_budget = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    budget_warning_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=80)
    budget_critical_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=95)
    block_when_budget_exceeded = models.BooleanField(default=False)
    currency = models.CharField(max_length=10, default="USD")
    capabilities_json = models.JSONField(default=list, blank=True)
    configuration_json = models.JSONField(default=dict, blank=True)
    last_health_check_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_failure_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=150, blank=True)
    last_error_message = models.TextField(blank=True)
    created_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_ai_providers"
    )
    updated_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="updated_ai_providers"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "name"]
        db_table = "AIProvider"
        permissions = [
            ("set_default_ai_provider", "Can set the default AI provider"),
            ("manage_ai_provider_credentials", "Can manage AI provider credentials"),
            ("test_ai_provider", "Can test AI providers"),
            ("view_ai_provider_usage", "Can view AI provider usage"),
            ("view_ai_provider_costs", "Can view AI provider costs"),
            ("manage_ai_use_case_routing", "Can manage AI use case routing"),
            ("manage_ai_provider_budgets", "Can manage AI provider budgets"),
        ]

    def __str__(self):
        return self.name


class AIProviderCredential(models.Model):
    provider = models.ForeignKey(AIProvider, related_name="credentials", on_delete=models.CASCADE)
    credential_type = models.CharField(max_length=60, default="api_key")
    encrypted_value = models.TextField(blank=True)
    secret_reference = models.CharField(max_length=500, blank=True)
    key_identifier = models.CharField(max_length=160, blank=True)
    last_four_characters = models.CharField(max_length=4, blank=True)
    active = models.BooleanField(default=True)
    rotated_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["provider", "credential_type"]
        db_table = "AIProviderCredential"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "credential_type"], name="unique_ai_provider_credential_type"
            ),
        ]


class AIProviderModel(models.Model):
    VALIDATION_STATUSES = [
        ("Draft", "Draft"),
        ("To Review", "To Review"),
        ("Validated", "Validated"),
        ("Deprecated", "Deprecated"),
    ]

    provider = models.ForeignKey(AIProvider, related_name="models", on_delete=models.CASCADE)
    model_code = models.CharField(max_length=180)
    display_name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    model_family = models.CharField(max_length=120, blank=True)
    context_window = models.PositiveBigIntegerField(null=True, blank=True)
    maximum_output_tokens = models.PositiveIntegerField(null=True, blank=True)
    capabilities_json = models.JSONField(default=list, blank=True)
    supports_streaming = models.BooleanField(default=False)
    supports_structured_output = models.BooleanField(default=False)
    supports_tool_calling = models.BooleanField(default=False)
    supports_vision = models.BooleanField(default=False)
    supports_embeddings = models.BooleanField(default=False)
    supports_audio_transcription = models.BooleanField(default=False)
    supports_text_to_speech = models.BooleanField(default=False)
    input_cost_per_million = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    output_cost_per_million = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    cached_input_cost_per_million = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    currency = models.CharField(max_length=10, default="USD")
    pricing_notes = models.TextField(blank=True)
    active = models.BooleanField(default=True, db_index=True)
    is_default_for_provider = models.BooleanField(default=False)
    validation_status = models.CharField(
        max_length=20, choices=VALIDATION_STATUSES, default="To Review"
    )
    configuration_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["provider", "-is_default_for_provider", "display_name"]
        db_table = "AIProviderModel"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "model_code"], name="unique_ai_provider_model"
            ),
        ]

    def __str__(self):
        return f"{self.provider.name} / {self.display_name}"


class AIUseCaseConfiguration(models.Model):
    VALIDATION_STATUSES = [
        ("Draft", "Draft"),
        ("To Review", "To Review"),
        ("Validated", "Validated"),
        ("Rejected", "Rejected"),
    ]

    use_case_code = models.SlugField(max_length=140, unique=True)
    display_name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    primary_provider = models.ForeignKey(
        AIProvider, null=True, blank=True, related_name="primary_use_cases", on_delete=models.SET_NULL
    )
    primary_model = models.ForeignKey(
        AIProviderModel, null=True, blank=True, related_name="primary_use_cases", on_delete=models.SET_NULL
    )
    selection_mode = models.CharField(
        max_length=20, choices=AIProvider.SELECTION_MODES, default="priority"
    )
    fallback_enabled = models.BooleanField(default=True)
    fallback_providers_json = models.JSONField(default=list, blank=True)
    required_capabilities_json = models.JSONField(default=list, blank=True)
    temperature = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    maximum_output_tokens = models.PositiveIntegerField(default=2048)
    timeout_seconds = models.PositiveIntegerField(default=60)
    retry_count = models.PositiveIntegerField(default=1)
    structured_output_required = models.BooleanField(default=False)
    streaming_enabled = models.BooleanField(default=False)
    active = models.BooleanField(default=True, db_index=True)
    validation_status = models.CharField(
        max_length=20, choices=VALIDATION_STATUSES, default="To Review"
    )
    configuration_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_name"]
        db_table = "AIUseCaseConfiguration"

    def __str__(self):
        return self.display_name


class AIAgentProviderConfiguration(models.Model):
    agent = models.ForeignKey(AIAgent, related_name="provider_configurations", on_delete=models.CASCADE)
    use_case = models.ForeignKey(
        AIUseCaseConfiguration, related_name="agent_configurations", on_delete=models.CASCADE
    )
    provider = models.ForeignKey(AIProvider, related_name="agent_configurations", on_delete=models.CASCADE)
    model = models.ForeignKey(
        AIProviderModel, null=True, blank=True, related_name="agent_configurations", on_delete=models.SET_NULL
    )
    priority = models.PositiveIntegerField(default=100)
    fallback_enabled = models.BooleanField(default=True)
    active = models.BooleanField(default=True)
    configuration_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["agent", "use_case", "-priority"]
        db_table = "AIAgentProviderConfiguration"
        constraints = [
            models.UniqueConstraint(
                fields=["agent", "use_case", "provider"],
                name="unique_ai_agent_use_case_provider",
            ),
        ]


class AIProviderUsageLog(models.Model):
    request_id = models.CharField(max_length=255, default=uuid.uuid4, db_index=True)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    conversation_id = models.CharField(max_length=255, blank=True, db_index=True)
    agent = models.ForeignKey(
        AIAgent, null=True, blank=True, related_name="provider_usage_logs", on_delete=models.SET_NULL
    )
    use_case = models.CharField(max_length=140, db_index=True)
    provider = models.ForeignKey(
        AIProvider, null=True, blank=True, related_name="usage_logs", on_delete=models.SET_NULL
    )
    provider_code = models.CharField(max_length=100, db_index=True)
    model = models.CharField(max_length=180, blank=True, db_index=True)
    primary_provider_code = models.CharField(max_length=100, blank=True)
    fallback_used = models.BooleanField(default=False, db_index=True)
    fallback_reason = models.CharField(max_length=160, blank=True)
    status = models.CharField(max_length=40, default="completed", db_index=True)
    input_tokens = models.PositiveBigIntegerField(default=0)
    output_tokens = models.PositiveBigIntegerField(default=0)
    cached_tokens = models.PositiveBigIntegerField(default=0)
    total_tokens = models.PositiveBigIntegerField(default=0)
    audio_seconds = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    image_count = models.PositiveIntegerField(default=0)
    estimated_cost = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    currency = models.CharField(max_length=10, default="USD")
    latency_ms = models.PositiveIntegerField(default=0)
    retry_count = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=160, blank=True)
    error_message = models.TextField(blank=True)
    metadata_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "AIProviderUsageLog"
        indexes = [
            models.Index(fields=["provider_code", "created_at"], name="ai_provider_usage_time"),
            models.Index(fields=["use_case", "created_at"], name="ai_use_case_usage_time"),
        ]


class AIProviderHealthLog(models.Model):
    provider = models.ForeignKey(AIProvider, related_name="health_logs", on_delete=models.CASCADE)
    status = models.CharField(max_length=30)
    latency_ms = models.PositiveIntegerField(default=0)
    model = models.CharField(max_length=180, blank=True)
    error_code = models.CharField(max_length=160, blank=True)
    error_message = models.TextField(blank=True)
    checked_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-checked_at"]
        db_table = "AIProviderHealthLog"


class AIProviderCircuitState(models.Model):
    provider = models.OneToOneField(AIProvider, related_name="circuit_state", on_delete=models.CASCADE)
    failure_count = models.PositiveIntegerField(default=0)
    window_started_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    open_until = models.DateTimeField(null=True, blank=True)
    last_failure_code = models.CharField(max_length=160, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "AIProviderCircuitState"


class AIProviderAuditLog(models.Model):
    provider = models.ForeignKey(
        AIProvider, null=True, blank=True, related_name="audit_logs", on_delete=models.SET_NULL
    )
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=100, db_index=True)
    changes_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "AIProviderAuditLog"


class PowerBIInteractionLog(models.Model):
    user = models.ForeignKey(User, related_name="powerbi_interaction_logs", null=True, blank=True, on_delete=models.SET_NULL)
    question_text = models.TextField(blank=True)
    extracted_intent = models.JSONField(default=dict, blank=True)
    validated_intent = models.JSONField(default=dict, blank=True)
    generated_dax = models.TextField(blank=True)
    dax_result = models.JSONField(default=dict, blank=True)
    report = models.ForeignKey(PowerBIReport, null=True, blank=True, on_delete=models.SET_NULL)
    page = models.ForeignKey(PowerBIPage, null=True, blank=True, on_delete=models.SET_NULL)
    visual = models.ForeignKey(PowerBIVisual, null=True, blank=True, on_delete=models.SET_NULL)
    resolved_filters = models.JSONField(default=list, blank=True)
    navigation_payload = models.JSONField(default=dict, blank=True)
    frontend_events = models.JSONField(default=list, blank=True)
    final_answer = models.TextField(blank=True)
    status = models.CharField(max_length=40, default="Completed")
    errors = models.TextField(blank=True)
    execution_time_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "ai_powerbi_interaction_logs"


class RootCauseDimension(models.Model):
    VALIDATION_STATUSES = [
        ("Draft", "Draft"),
        ("To Review", "To Review"),
        ("Validated", "Validated"),
        ("Rejected", "Rejected"),
        ("Deprecated", "Deprecated"),
    ]

    section = models.ForeignKey(
        AIConfigSection,
        related_name="root_cause_dimensions",
        on_delete=models.CASCADE,
    )
    code = models.SlugField(max_length=120)
    display_name = models.CharField(max_length=255)
    semantic_table = models.CharField(max_length=255)
    semantic_column = models.CharField(max_length=255)
    parent_dimension = models.ForeignKey(
        "self",
        related_name="child_dimensions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    hierarchy_level = models.PositiveSmallIntegerField(default=0)
    sort_order = models.PositiveIntegerField(default=100)
    entity_type = models.CharField(max_length=120, default="Downtime")
    is_filterable = models.BooleanField(default=True)
    is_clickable = models.BooleanField(default=True)
    available_for_breakdown = models.BooleanField(default=True)
    available_for_comments = models.BooleanField(default=True)
    available_for_repetition_analysis = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    validation_status = models.CharField(
        max_length=40,
        choices=VALIDATION_STATUSES,
        default="To Review",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["section", "sort_order", "display_name"]
        db_table = "ai_root_cause_dimensions"
        constraints = [
            models.UniqueConstraint(
                fields=["section", "code"],
                name="unique_root_cause_dimension_code",
            ),
        ]


class RootCauseTheme(models.Model):
    section = models.ForeignKey(
        AIConfigSection,
        related_name="root_cause_themes",
        on_delete=models.CASCADE,
    )
    code = models.SlugField(max_length=120)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    synonyms = models.JSONField(default=list, blank=True)
    examples = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    validation_status = models.CharField(
        max_length=40,
        choices=RootCauseDimension.VALIDATION_STATUSES,
        default="To Review",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["section", "name"]
        db_table = "ai_root_cause_themes"
        constraints = [
            models.UniqueConstraint(
                fields=["section", "code"],
                name="unique_root_cause_theme_code",
            ),
        ]


class CommentQualityRule(models.Model):
    code = models.SlugField(max_length=120, unique=True)
    name = models.CharField(max_length=255)
    classification = models.CharField(max_length=80)
    minimum_length = models.PositiveIntegerField(default=0)
    generic_phrases = models.JSONField(default=list, blank=True)
    priority = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    validation_status = models.CharField(
        max_length=40,
        choices=RootCauseDimension.VALIDATION_STATUSES,
        default="To Review",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority", "name"]
        db_table = "ai_comment_quality_rules"


class RepeatFailureRule(models.Model):
    name = models.CharField(max_length=255)
    dimension_codes = models.JSONField(default=list)
    window_days = models.PositiveIntegerField(default=90)
    minimum_occurrences = models.PositiveIntegerField(default=2)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    validation_status = models.CharField(
        max_length=40,
        choices=RootCauseDimension.VALIDATION_STATUSES,
        default="To Review",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["window_days", "name"]
        db_table = "ai_repeat_failure_rules"


class SMCSCode(models.Model):
    code = models.CharField(max_length=20, unique=True, db_index=True)
    description = models.CharField(max_length=500, db_index=True)
    display_name = models.CharField(max_length=500, blank=True)
    system = models.CharField(max_length=255, blank=True, db_index=True)
    component = models.CharField(max_length=255, blank=True, db_index=True)
    subcomponent = models.CharField(max_length=255, blank=True)
    parent = models.ForeignKey(
        "self",
        related_name="children",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    hierarchy_level = models.PositiveSmallIntegerField(default=0)
    equipment_family = models.CharField(max_length=255, blank=True)
    applicable_models_json = models.JSONField(default=list, blank=True)
    keywords_json = models.JSONField(default=list, blank=True)
    synonyms_json = models.JSONField(default=list, blank=True)
    common_field_expressions_json = models.JSONField(default=list, blank=True)
    exclusion_terms_json = models.JSONField(default=list, blank=True)
    reference_version = models.CharField(max_length=40, default="1.0")
    source = models.CharField(max_length=120, default="CAT SMCS Codes")
    source_file = models.CharField(max_length=500, blank=True)
    validation_status = models.CharField(
        max_length=40,
        choices=RootCauseDimension.VALIDATION_STATUSES,
        default="To Review",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        db_table = "ai_smcs_codes"
        indexes = [
            models.Index(
                fields=["is_active", "validation_status"],
                name="smcs_active_status_idx",
            ),
        ]

    def __str__(self):
        return f"{self.code} - {self.description}"


class SMCSSynonym(models.Model):
    SYNONYM_TYPES = [
        ("Official Alias", "Official Alias"),
        ("Field Expression", "Field Expression"),
        ("Abbreviation", "Abbreviation"),
        ("Spelling Variant", "Spelling Variant"),
        ("Imported", "Imported"),
        ("AI Suggested", "AI Suggested"),
        ("Manual", "Manual"),
    ]

    smcs_reference = models.ForeignKey(
        SMCSCode,
        related_name="smcs_synonyms",
        on_delete=models.CASCADE,
    )
    synonym = models.CharField(max_length=500)
    normalized_synonym = models.CharField(max_length=500, db_index=True)
    language = models.CharField(max_length=12, default="en")
    synonym_type = models.CharField(
        max_length=40,
        choices=SYNONYM_TYPES,
        default="Manual",
    )
    source = models.CharField(max_length=120, default="Manual")
    confidence = models.DecimalField(max_digits=5, decimal_places=2, default=100)
    validation_status = models.CharField(
        max_length=40,
        choices=RootCauseDimension.VALIDATION_STATUSES,
        default="To Review",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["smcs_reference__code", "synonym"]
        db_table = "ai_smcs_synonyms"
        constraints = [
            models.UniqueConstraint(
                fields=["smcs_reference", "language", "normalized_synonym"],
                name="unique_smcs_synonym_key",
            ),
        ]


class SMCSClassificationConfig(models.Model):
    EXECUTION_MODES = [
        ("Disabled", "Disabled"),
        ("Preview", "Preview"),
        ("Admin Only", "Admin Only"),
        ("Production", "Production"),
    ]

    name = models.CharField(max_length=120, unique=True, default="Default")
    execution_mode = models.CharField(
        max_length=20,
        choices=EXECUTION_MODES,
        default="Preview",
    )
    auto_accept_threshold = models.PositiveSmallIntegerField(default=85)
    review_threshold = models.PositiveSmallIntegerField(default=70)
    candidate_score_gap = models.PositiveSmallIntegerField(default=10)
    max_candidates = models.PositiveSmallIntegerField(default=12)
    default_batch_size = models.PositiveSmallIntegerField(default=12)
    prompt_code = models.CharField(
        max_length=120,
        default="SMCS_COMMENT_CLASSIFICATION_V1",
    )
    prompt_version = models.CharField(max_length=40, default="1.0")
    config_version = models.CharField(max_length=40, default="1.0")
    generic_comments_json = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        db_table = "ai_smcs_classification_config"


class DowntimeSMCSClassification(models.Model):
    CLASSIFICATION_STATUSES = [
        ("matched", "Matched"),
        ("probable", "Probable"),
        ("unresolved", "Unresolved"),
        ("failed_validation", "Failed Validation"),
    ]
    MATCH_METHODS = [
        ("Explicit SMCS Code", "Explicit SMCS Code"),
        ("Exact Description", "Exact Description"),
        ("Synonym Match", "Synonym Match"),
        ("AI Semantic Classification", "AI Semantic Classification"),
        ("Manual Validation", "Manual Validation"),
        ("Unresolved", "Unresolved"),
    ]

    idempotency_key = models.CharField(max_length=64, unique=True, db_index=True)
    event_external_id = models.CharField(max_length=160, db_index=True)
    semantic_model = models.CharField(max_length=255, blank=True)
    source_system = models.CharField(max_length=120, default="Power BI")
    comment_hash = models.CharField(max_length=64, db_index=True)
    comment_snapshot = models.TextField(blank=True)
    normalized_comment = models.TextField(blank=True)
    minesite = models.CharField(max_length=255, blank=True)
    equipment_id = models.CharField(max_length=160, blank=True)
    serial_number = models.CharField(max_length=160, blank=True)
    model = models.CharField(max_length=160, blank=True)
    equipment_family = models.CharField(max_length=255, blank=True)
    downtime_driver = models.CharField(max_length=255, blank=True)
    event_start = models.DateTimeField(null=True, blank=True)
    event_end = models.DateTimeField(null=True, blank=True)
    downtime_hours = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    smcs_reference = models.ForeignKey(
        SMCSCode,
        related_name="downtime_classifications",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    smcs_code_snapshot = models.CharField(max_length=20, blank=True)
    smcs_description_snapshot = models.CharField(max_length=500, blank=True)
    system = models.CharField(max_length=255, blank=True)
    component = models.CharField(max_length=255, blank=True)
    subcomponent = models.CharField(max_length=255, blank=True)
    classification_status = models.CharField(
        max_length=30,
        choices=CLASSIFICATION_STATUSES,
        default="unresolved",
    )
    match_method = models.CharField(
        max_length=40,
        choices=MATCH_METHODS,
        default="Unresolved",
    )
    confidence = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    requires_review = models.BooleanField(default=True)
    review_reason = models.TextField(blank=True)
    reason = models.TextField(blank=True)
    evidence_phrases_json = models.JSONField(default=list, blank=True)
    secondary_mentions_json = models.JSONField(default=list, blank=True)
    alternative_candidates_json = models.JSONField(default=list, blank=True)
    detected_symptoms_json = models.JSONField(default=list, blank=True)
    detected_causes_json = models.JSONField(default=list, blank=True)
    detected_actions_json = models.JSONField(default=list, blank=True)
    detected_delays_json = models.JSONField(default=list, blank=True)
    candidate_list_json = models.JSONField(default=list, blank=True)
    prompt_code = models.CharField(max_length=120, blank=True)
    prompt_version = models.CharField(max_length=40, blank=True)
    config_version = models.CharField(max_length=40, blank=True)
    openai_model = models.CharField(max_length=120, blank=True)
    openai_request_id = models.CharField(max_length=160, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    estimated_cost = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    processing_duration_ms = models.PositiveIntegerField(default=0)
    validation_status = models.CharField(
        max_length=40,
        choices=RootCauseDimension.VALIDATION_STATUSES,
        default="To Review",
    )
    validated_by = models.ForeignKey(
        User,
        related_name="validated_smcs_classifications",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    manual_override = models.BooleanField(default=False)
    manual_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        db_table = "ai_downtime_smcs_classifications"
        indexes = [
            models.Index(
                fields=["classification_status", "requires_review"],
                name="smcs_class_review_idx",
            ),
        ]


class SMCSClassificationJob(models.Model):
    STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("Processing", "Processing"),
        ("Partially Completed", "Partially Completed"),
        ("Completed", "Completed"),
        ("Failed", "Failed"),
        ("Cancelled", "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        related_name="smcs_classification_jobs",
        on_delete=models.CASCADE,
    )
    explorer_session = models.ForeignKey(
        "DowntimeExplorerSession",
        related_name="smcs_classification_jobs",
        on_delete=models.CASCADE,
    )
    mode = models.CharField(max_length=20, default="Preview")
    scope = models.CharField(max_length=40, default="unmatched")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="Pending")
    total_events = models.PositiveIntegerField(default=0)
    processed_events = models.PositiveIntegerField(default=0)
    matched_events = models.PositiveIntegerField(default=0)
    probable_events = models.PositiveIntegerField(default=0)
    unresolved_events = models.PositiveIntegerField(default=0)
    failed_events = models.PositiveIntegerField(default=0)
    deterministic_matches = models.PositiveIntegerField(default=0)
    ai_matches = models.PositiveIntegerField(default=0)
    estimated_cost = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    actual_cost = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    result_json = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "ai_smcs_classification_jobs"


class DowntimeExplorerSession(models.Model):
    STATUS_CHOICES = [
        ("Active", "Active"),
        ("Completed", "Completed"),
        ("Expired", "Expired"),
        ("Failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        related_name="downtime_explorer_sessions",
        on_delete=models.CASCADE,
    )
    conversation = models.ForeignKey(
        AIConversationContext,
        related_name="downtime_explorer_sessions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    semantic_model_name = models.CharField(
        max_length=255,
        default="FPR Global DB + RLS",
    )
    semantic_model_id = models.CharField(max_length=128, blank=True)
    report = models.ForeignKey(
        PowerBIReport,
        related_name="downtime_explorer_sessions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    source_question = models.TextField(blank=True)
    kpi = models.CharField(max_length=120, default="availability")
    context_json = models.JSONField(default=dict)
    context_hash = models.CharField(max_length=64, db_index=True)
    selected_driver = models.CharField(max_length=255)
    selected_subcategory = models.CharField(max_length=255, blank=True)
    selected_component = models.CharField(max_length=255, blank=True)
    selected_subcomponent = models.CharField(max_length=255, blank=True)
    selected_cause = models.CharField(max_length=255, blank=True)
    current_level = models.CharField(max_length=80, default="overview")
    navigation_stack = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Active",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ["-updated_at"]
        db_table = "ai_downtime_explorer_sessions"
        indexes = [
            models.Index(
                fields=["user", "context_hash", "status"],
                name="dt_explorer_context_idx",
            ),
        ]


class DowntimeExplorerInteraction(models.Model):
    session = models.ForeignKey(
        DowntimeExplorerSession,
        related_name="interactions",
        on_delete=models.CASCADE,
    )
    interaction_type = models.CharField(max_length=80)
    selected_entity_type = models.CharField(max_length=120, blank=True)
    selected_value = models.CharField(max_length=500, blank=True)
    previous_context = models.JSONField(default=dict, blank=True)
    new_context = models.JSONField(default=dict, blank=True)
    query_execution_id = models.CharField(max_length=128, blank=True)
    execution_time_ms = models.PositiveIntegerField(default=0)
    result_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "ai_downtime_explorer_interactions"


class DowntimeExplorerAIAnalysis(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        DowntimeExplorerSession,
        related_name="ai_analyses",
        on_delete=models.CASCADE,
    )
    context_json = models.JSONField(default=dict)
    event_ids = models.JSONField(default=list, blank=True)
    model_name = models.CharField(max_length=120, blank=True)
    prompt_version = models.CharField(max_length=40, default="1.0")
    result_json = models.JSONField(default=dict, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    estimated_cost = models.DecimalField(
        max_digits=18,
        decimal_places=8,
        null=True,
        blank=True,
    )
    coverage_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
    )
    status = models.CharField(max_length=40, default="Completed")
    error_message = models.TextField(blank=True)
    execution_time_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "ai_downtime_explorer_ai_analyses"


class AIVisualMapping(models.Model):
    section = models.ForeignKey(AIConfigSection, related_name="visual_mappings", on_delete=models.CASCADE)
    metric_code = models.CharField(max_length=120)
    recommended_visual = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    priority = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["metric_code", "priority", "recommended_visual"]
        db_table = "ai_visual_mappings"

    def __str__(self) -> str:
        return f"{self.metric_code} -> {self.recommended_visual}"


class AIKPITarget(models.Model):
    section = models.ForeignKey(AIConfigSection, related_name="kpi_targets", on_delete=models.CASCADE)
    metric_code = models.CharField(max_length=120)
    target = models.DecimalField(max_digits=18, decimal_places=4)
    warning_threshold = models.DecimalField(max_digits=18, decimal_places=4)
    critical_threshold = models.DecimalField(max_digits=18, decimal_places=4)
    unit = models.CharField(max_length=80, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["metric_code"]
        db_table = "ai_kpi_targets"
        constraints = [
            models.UniqueConstraint(fields=["section", "metric_code"], name="unique_ai_kpi_target_per_section"),
        ]

    def __str__(self) -> str:
        return f"{self.metric_code} target"


class AIRecommendedAction(models.Model):
    section = models.ForeignKey(AIConfigSection, related_name="recommended_actions", on_delete=models.CASCADE)
    metric_code = models.CharField(max_length=120)
    condition = models.CharField(max_length=255)
    recommendations = models.TextField()
    priority = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["metric_code", "priority"]
        db_table = "ai_recommended_actions"

    def __str__(self) -> str:
        return f"{self.metric_code} - {self.condition}"


class AIDebugRun(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    question_text = models.TextField()
    detected_section = models.CharField(max_length=120, blank=True)
    extracted_intent = models.JSONField(default=dict, blank=True)
    prompt_sent = models.TextField(blank=True)
    generated_json = models.JSONField(default=dict, blank=True)
    generated_dax = models.TextField(blank=True)
    powerbi_response = models.JSONField(default=dict, blank=True)
    formatted_response = models.TextField(blank=True)
    execution_time_ms = models.PositiveIntegerField(default=0)
    token_usage = models.JSONField(default=dict, blank=True)
    errors = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "ai_debug_runs"

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M:%S} - {self.detected_section}"


class KnowledgeBaseMixin(models.Model):
    VALIDATION_STATUSES = [
        ("Draft", "Draft"),
        ("To Review", "To Review"),
        ("Validated", "Validated"),
        ("Rejected", "Rejected"),
        ("Deprecated", "Deprecated"),
    ]

    section = models.ForeignKey(AIConfigSection, related_name="%(class)s_items", on_delete=models.CASCADE)
    validation_status = models.CharField(max_length=30, choices=VALIDATION_STATUSES, default="To Review")
    owner = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class KnowledgeBusinessGlossary(KnowledgeBaseMixin):
    term = models.CharField(max_length=255)
    business_definition = models.TextField()
    category = models.CharField(max_length=120, blank=True)
    related_kpi = models.CharField(max_length=120, blank=True)
    related_powerbi_measure = models.CharField(max_length=255, blank=True)
    related_table = models.CharField(max_length=255, blank=True)
    related_column = models.CharField(max_length=255, blank=True)
    example_usage = models.TextField(blank=True)

    class Meta:
        ordering = ["category", "term"]
        db_table = "kb_business_glossary"
        constraints = [
            models.UniqueConstraint(fields=["section", "term"], name="unique_kb_business_glossary_term"),
        ]

    def __str__(self) -> str:
        return self.term


class KnowledgeKPIDictionary(KnowledgeBaseMixin):
    BUSINESS_CATEGORIES = [
        ("Reliability", "Reliability"),
        ("Maintenance", "Maintenance"),
        ("Operations", "Operations"),
        ("Productivity", "Productivity"),
        ("Fuel", "Fuel"),
        ("Parts Sales", "Parts Sales"),
        ("Component Rebuild", "Component Rebuild"),
        ("Financial", "Financial"),
        ("Other", "Other"),
    ]
    CALCULATION_TYPES = [
        (value, value) for value in [
            "Ratio", "Percentage", "Sum", "Average", "Weighted Average",
            "Count", "Duration", "Rate", "Index", "Custom",
        ]
    ]
    NULL_HANDLING_RULES = [
        (value, value) for value in [
            "Ignore Nulls", "Treat as Zero", "Return Blank",
            "Use Previous Value", "Custom",
        ]
    ]
    ZERO_DENOMINATOR_BEHAVIORS = [
        (value, value) for value in ["Return Blank", "Return Zero", "Return Error", "Custom"]
    ]
    COMPARISON_TYPES = [
        (value, value) for value in [
            "None", "Previous Period", "Previous Month", "Previous Year",
            "Target", "Budget", "Benchmark", "Custom",
        ]
    ]
    RANKING_DIRECTIONS = [
        (value, value) for value in ["Highest First", "Lowest First", "Not Applicable"]
    ]
    THRESHOLD_DIRECTIONS = [
        (value, value) for value in ["Higher Is Better", "Lower Is Better"]
    ]
    TARGET_SOURCES = [
        (value, value) for value in [
            "Fixed Value", "Power BI Measure", "Site Target", "Customer Target",
            "Model Target", "External Benchmark",
        ]
    ]
    REVIEW_FREQUENCIES = [
        (value, value) for value in ["Monthly", "Quarterly", "Semi-Annual", "Annual", "On Change"]
    ]

    kpi_code = models.CharField(max_length=120)
    kpi_name = models.CharField(max_length=255)
    business_definition = models.TextField()
    formula_description = models.TextField(blank=True)
    powerbi_measure_name = models.CharField(max_length=255)
    unit = models.CharField(max_length=80, blank=True)
    target = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    warning_threshold = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    critical_threshold = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    aggregation_rule = models.CharField(max_length=255, blank=True)
    default_time_grain = models.CharField(max_length=80, blank=True)
    business_purpose = models.TextField(blank=True)
    business_category = models.CharField(max_length=80, choices=BUSINESS_CATEGORIES, default="Other")
    business_interpretation = models.TextField(blank=True)
    higher_is_better = models.BooleanField(default=False)
    lower_is_better = models.BooleanField(default=False)
    numerator_description = models.TextField(blank=True)
    denominator_description = models.TextField(blank=True)
    calculation_type = models.CharField(max_length=80, choices=CALCULATION_TYPES, default="Custom")
    null_handling_rule = models.CharField(max_length=80, choices=NULL_HANDLING_RULES, default="Ignore Nulls")
    zero_denominator_behavior = models.CharField(
        max_length=80, choices=ZERO_DENOMINATOR_BEHAVIORS, default="Return Blank"
    )
    decimal_precision = models.PositiveSmallIntegerField(default=2)
    display_format = models.CharField(max_length=80, blank=True)
    powerbi_workspace_id = models.CharField(max_length=120, blank=True)
    powerbi_report_id = models.CharField(max_length=120, blank=True)
    powerbi_semantic_model_id = models.CharField(max_length=120, blank=True)
    powerbi_measure_table = models.CharField(max_length=255, blank=True)
    powerbi_measure_full_reference = models.CharField(max_length=520, blank=True)
    source_report_name = models.CharField(max_length=255, blank=True)
    source_page_name = models.CharField(max_length=255, blank=True)
    source_page_internal_name = models.CharField(max_length=255, blank=True)
    primary_visual_name = models.CharField(max_length=255, blank=True)
    primary_visual_internal_name = models.CharField(max_length=255, blank=True)
    default_comparison_type = models.CharField(
        max_length=80, choices=COMPARISON_TYPES, default="None"
    )
    default_comparison_period = models.CharField(max_length=120, blank=True)
    default_ranking_direction = models.CharField(
        max_length=80, choices=RANKING_DIRECTIONS, default="Not Applicable"
    )
    default_top_n = models.PositiveIntegerField(default=10)
    trend_supported = models.BooleanField(default=False)
    comparison_supported = models.BooleanField(default=False)
    ranking_supported = models.BooleanField(default=False)
    root_cause_supported = models.BooleanField(default=False)
    forecast_supported = models.BooleanField(default=False)
    supported_dimensions = models.JSONField(default=list, blank=True)
    default_drill_down_dimension = models.CharField(max_length=120, blank=True)
    required_filters = models.JSONField(default=list, blank=True)
    optional_filters = models.JSONField(default=list, blank=True)
    related_kpis = models.JSONField(default=list, blank=True)
    diagnostic_kpis = models.JSONField(default=list, blank=True)
    parent_kpi = models.CharField(max_length=120, blank=True)
    child_kpis = models.JSONField(default=list, blank=True)
    default_answer_template = models.TextField(blank=True)
    business_explanation_template = models.TextField(blank=True)
    clarification_message = models.TextField(blank=True)
    ai_usage_instructions = models.TextField(blank=True)
    threshold_direction = models.CharField(
        max_length=80, choices=THRESHOLD_DIRECTIONS, default="Higher Is Better"
    )
    target_source = models.CharField(max_length=80, choices=TARGET_SOURCES, default="Fixed Value")
    target_measure_name = models.CharField(max_length=255, blank=True)
    threshold_evaluation_rule = models.TextField(blank=True)
    minimum_data_completeness = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    minimum_equipment_count = models.PositiveIntegerField(null=True, blank=True)
    freshness_requirement = models.CharField(max_length=255, blank=True)
    data_quality_warning_message = models.TextField(blank=True)
    business_owner = models.CharField(max_length=255, blank=True)
    technical_owner = models.CharField(max_length=255, blank=True)
    approved_by = models.CharField(max_length=255, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    version = models.CharField(max_length=40, default="1.0")
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    review_frequency = models.CharField(
        max_length=40, choices=REVIEW_FREQUENCIES, default="On Change"
    )
    last_reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["kpi_code"]
        db_table = "kb_kpi_dictionary"
        constraints = [
            models.UniqueConstraint(fields=["section", "kpi_code"], name="unique_kb_kpi_code"),
        ]

    def __str__(self) -> str:
        return self.kpi_code

    def clean(self):
        from django.core.exceptions import ValidationError
        import re

        errors = {}
        self.kpi_code = str(self.kpi_code or "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", self.kpi_code):
            errors["kpi_code"] = "KPI Code must use lowercase snake_case."
        required_fields = {
            "business_definition": "Business Definition is required.",
            "formula_description": "Formula Description is required.",
            "unit": "Unit is required.",
            "aggregation_rule": "Aggregation Rule is required.",
            "default_time_grain": "Default Time Grain is required.",
        }
        for field_name, message in required_fields.items():
            if not str(getattr(self, field_name, "") or "").strip():
                errors[field_name] = message
        if self.validation_status == "Validated" and not str(self.powerbi_measure_name or "").strip():
            errors["powerbi_measure_name"] = (
                "Power BI Measure Name is required before a KPI can be Validated."
            )
        if self.higher_is_better and self.lower_is_better:
            errors["higher_is_better"] = (
                "Higher Is Better and Lower Is Better cannot both be selected."
            )
        higher = self.higher_is_better or (
            not self.lower_is_better and self.threshold_direction == "Higher Is Better"
        )
        lower = self.lower_is_better or self.threshold_direction == "Lower Is Better"
        if all(value is not None for value in [self.target, self.warning_threshold]):
            if higher and self.target <= self.warning_threshold:
                errors["target"] = "Target must be greater than Warning Threshold."
            if lower and self.target >= self.warning_threshold:
                errors["target"] = "Target must be lower than Warning Threshold."
        if all(value is not None for value in [self.warning_threshold, self.critical_threshold]):
            if higher and self.warning_threshold <= self.critical_threshold:
                errors["warning_threshold"] = (
                    "Warning Threshold must be greater than Critical Threshold."
                )
            if lower and self.warning_threshold >= self.critical_threshold:
                errors["warning_threshold"] = (
                    "Warning Threshold must be lower than Critical Threshold."
                )
        if self.target_source == "Power BI Measure" and not self.target_measure_name.strip():
            errors["target_measure_name"] = (
                "Target Measure Name is required when Target Source is Power BI Measure."
            )
        if self.default_drill_down_dimension and (
            self.default_drill_down_dimension not in (self.supported_dimensions or [])
        ):
            errors["default_drill_down_dimension"] = (
                "Default Drill-Down Dimension must belong to Supported Dimensions."
            )
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            errors["effective_to"] = "Effective To must be on or after Effective From."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.powerbi_measure_table and self.powerbi_measure_name:
            table = self.powerbi_measure_table.replace("'", "''").strip()
            measure = self.powerbi_measure_name.strip().strip("[]")
            self.powerbi_measure_full_reference = f"'{table}'[{measure}]"
        super().save(*args, **kwargs)


class SQLConfigSyncQueue(models.Model):
    STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("Syncing", "Syncing"),
        ("Failed", "Failed"),
    ]

    model_name = models.CharField(max_length=160, unique=True)
    table_name = models.CharField(max_length=255)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="Pending")
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["updated_at", "model_name"]
        db_table = "system_sql_config_sync_queue"

    def __str__(self) -> str:
        return f"{self.model_name} - {self.status}"


class KnowledgeMiningTerminology(KnowledgeBaseMixin):
    term = models.CharField(max_length=255)
    definition = models.TextField()
    category = models.CharField(max_length=120, blank=True)
    related_process = models.CharField(max_length=255, blank=True)
    example = models.TextField(blank=True)

    class Meta:
        ordering = ["category", "term"]
        db_table = "kb_mining_terminology"

    def __str__(self) -> str:
        return self.term


class KnowledgeQuestion(KnowledgeBaseMixin):
    INTENT_TYPES = [
        ("Single KPI", "Single KPI"),
        ("Trend", "Trend"),
        ("Comparison", "Comparison"),
        ("Ranking", "Ranking"),
        ("Root Cause", "Root Cause"),
        ("Recommendation", "Recommendation"),
        ("Executive Summary", "Executive Summary"),
    ]

    question_text = models.TextField()
    intent_type = models.CharField(max_length=80, choices=INTENT_TYPES, default="Single KPI")
    expected_json_intent = models.JSONField(default=dict, blank=True)
    expected_dax = models.TextField(blank=True)
    expected_answer_style = models.TextField(blank=True)
    language = models.CharField(max_length=16, default="en")
    difficulty_level = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        db_table = "kb_question_library"

    def __str__(self) -> str:
        return self.question_text[:80]


class KnowledgeSynonym(KnowledgeBaseMixin):
    ENTITY_TYPES = [
        ("KPI", "KPI"),
        ("Filter", "Filter"),
        ("Mine Site", "Mine Site"),
        ("Model", "Model"),
        ("Equipment Family", "Equipment Family"),
        ("Serial Number", "Serial Number"),
        ("Component", "Component"),
        ("Customer", "Customer"),
        ("Period", "Period"),
        ("Business Term", "Business Term"),
    ]
    SOURCES = [
        ("Manual", "Manual"),
        ("Business", "Business"),
        ("Imported", "Imported"),
        ("System Generated", "System Generated"),
        ("AI Generated", "AI Generated"),
    ]
    MATCH_TYPES = [
        ("Exact", "Exact"),
        ("Phrase", "Phrase"),
        ("Contains", "Contains"),
        ("Abbreviation", "Abbreviation"),
        ("Fuzzy", "Fuzzy"),
        ("Semantic", "Semantic"),
    ]

    canonical_term = models.CharField(max_length=255)
    synonym = models.CharField(max_length=255)
    normalized_value = models.CharField(max_length=255, default="", blank=True)
    normalized_synonym_key = models.CharField(max_length=255, default="", blank=True, db_index=True, editable=False)
    entity_type = models.CharField(max_length=80, choices=ENTITY_TYPES)
    language = models.CharField(max_length=16, default="en")
    confidence = models.DecimalField(max_digits=5, decimal_places=2, default=100)
    synonym_source = models.CharField(max_length=40, choices=SOURCES, default="Manual")
    match_type = models.CharField(max_length=30, choices=MATCH_TYPES, default="Exact")
    resolution_priority = models.PositiveSmallIntegerField(default=50)
    is_ambiguous = models.BooleanField(default=False)
    ambiguity_notes = models.TextField(blank=True)
    usage_count = models.PositiveIntegerField(default=0, editable=False)
    last_used_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_used_question = models.TextField(blank=True, editable=False)
    created_by = models.ForeignKey(
        User, null=True, blank=True, related_name="created_knowledge_synonyms",
        on_delete=models.SET_NULL, editable=False,
    )
    updated_by = models.ForeignKey(
        User, null=True, blank=True, related_name="updated_knowledge_synonyms",
        on_delete=models.SET_NULL, editable=False,
    )
    validated_at = models.DateTimeField(null=True, blank=True, editable=False)
    validated_by = models.ForeignKey(
        User, null=True, blank=True, related_name="validated_knowledge_synonyms",
        on_delete=models.SET_NULL, editable=False,
    )

    class Meta:
        ordering = ["entity_type", "canonical_term", "synonym"]
        db_table = "kb_synonym_library"
        indexes = [
            models.Index(fields=["section", "entity_type", "language", "normalized_synonym_key"], name="kb_syn_resolve_idx"),
            models.Index(fields=["section", "validation_status", "is_active"], name="kb_syn_status_idx"),
            models.Index(fields=["canonical_term"], name="kb_syn_canonical_idx"),
            models.Index(fields=["normalized_value"], name="kb_syn_value_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(usage_count__gte=0), name="kb_syn_usage_nonnegative"),
            models.CheckConstraint(condition=models.Q(confidence__gte=0, confidence__lte=100), name="kb_syn_confidence_range"),
            models.CheckConstraint(condition=models.Q(resolution_priority__gte=1, resolution_priority__lte=100), name="kb_syn_priority_range"),
        ]

    CRITICAL_FIELDS = {
        "section_id", "canonical_term", "synonym", "normalized_value", "entity_type",
        "language", "confidence", "match_type", "is_ambiguous", "is_active",
    }

    def clean(self):
        from django.core.exceptions import ValidationError
        from .synonym_utils import normalize_synonym_key

        self.canonical_term = str(self.canonical_term or "").strip()
        self.synonym = str(self.synonym or "").strip()
        self.language = str(self.language or "en").strip().lower()
        self.normalized_value = str(self.normalized_value or self.canonical_term).strip()
        self.normalized_synonym_key = normalize_synonym_key(self.synonym)
        errors = {}
        if not self.normalized_value:
            errors["normalized_value"] = "Normalized Value is required."
        if not self.normalized_synonym_key:
            errors["synonym"] = "Synonym must contain searchable characters."
        if not 0 <= float(self.confidence) <= 100:
            errors["confidence"] = "Confidence must be between 0 and 100."
        if not 1 <= int(self.resolution_priority) <= 100:
            errors["resolution_priority"] = "Resolution Priority must be between 1 and 100."
        duplicate = type(self).objects.filter(
            section_id=self.section_id,
            entity_type=self.entity_type,
            language=self.language,
            normalized_synonym_key=self.normalized_synonym_key,
        ).exclude(pk=self.pk)
        if duplicate.exists():
            same_canonical = duplicate.filter(canonical_term__iexact=self.canonical_term).first()
            if same_canonical:
                errors["synonym"] = (
                    "This synonym already exists for the selected section, entity type and language."
                )
            elif not self.is_ambiguous:
                conflict = duplicate.first()
                errors["synonym"] = (
                    f'Synonym "{self.synonym}" is already mapped to another canonical term '
                    f'"{conflict.canonical_term}" (record ID {conflict.id}). '
                    "Mark the new synonym as ambiguous only when this mapping is legitimate."
                )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        from .synonym_utils import default_match_type, normalize_synonym_key

        self.normalized_value = str(self.normalized_value or self.canonical_term).strip()
        self.normalized_synonym_key = normalize_synonym_key(self.synonym)
        if not self.pk and (not self.match_type or self.match_type == "Exact"):
            self.match_type = default_match_type(self.synonym)
        if self.synonym_source == "AI Generated" and not self.pk:
            self.validation_status = "Draft"
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.canonical_term} = {self.synonym}"


class KnowledgeBusinessRule(KnowledgeBaseMixin):
    rule_name = models.CharField(max_length=255)
    kpi = models.CharField(max_length=120, blank=True)
    condition = models.TextField()
    rule_description = models.TextField(blank=True)
    default_behavior = models.TextField(blank=True)
    required_filters = models.CharField(max_length=500, blank=True)
    missing_filter_behavior = models.TextField(blank=True)

    class Meta:
        ordering = ["kpi", "rule_name"]
        db_table = "kb_business_rules"

    def __str__(self) -> str:
        return self.rule_name


class KnowledgePrompt(KnowledgeBaseMixin):
    PROMPT_TYPES = [
        ("Intent Extraction", "Intent Extraction"),
        ("DAX Generation Control", "DAX Generation Control"),
        ("Business Response", "Business Response"),
        ("Recommendation", "Recommendation"),
        ("Executive Summary", "Executive Summary"),
        ("Trend Analysis", "Trend Analysis"),
        ("Comparison", "Comparison"),
        ("Root Cause Analysis", "Root Cause Analysis"),
    ]

    prompt_name = models.CharField(max_length=255)
    prompt_type = models.CharField(max_length=120, choices=PROMPT_TYPES)
    prompt_content = models.TextField()
    version = models.CharField(max_length=50, default="1.0")
    created_by = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["prompt_type", "prompt_name"]
        db_table = "kb_prompt_library"

    def __str__(self) -> str:
        return self.prompt_name


class KnowledgeRecommendedAction(KnowledgeBaseMixin):
    kpi = models.CharField(max_length=120)
    condition = models.CharField(max_length=255)
    business_context = models.TextField(blank=True)
    recommended_action = models.TextField()
    priority = models.PositiveIntegerField(default=100)

    class Meta:
        ordering = ["kpi", "priority"]
        db_table = "kb_recommended_actions"

    def __str__(self) -> str:
        return f"{self.kpi} - {self.condition}"


class KnowledgeAILog(models.Model):
    user_question = models.TextField()
    detected_section = models.CharField(max_length=120, blank=True)
    extracted_intent = models.JSONField(default=dict, blank=True)
    generated_dax = models.TextField(blank=True)
    powerbi_result = models.JSONField(default=dict, blank=True)
    final_answer = models.TextField(blank=True)
    status = models.CharField(max_length=50, default="Completed")
    error_message = models.TextField(blank=True)
    execution_time_ms = models.PositiveIntegerField(default=0)
    token_usage = models.JSONField(default=dict, blank=True)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "kb_ai_logs"

    def __str__(self) -> str:
        return self.user_question[:80]


class KnowledgeUserFeedback(models.Model):
    ai_log = models.ForeignKey(KnowledgeAILog, related_name="feedback", null=True, blank=True, on_delete=models.SET_NULL)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    rating = models.PositiveIntegerField(default=0)
    feedback_comment = models.TextField(blank=True)
    was_answer_useful = models.BooleanField(default=False)
    corrected_intent = models.JSONField(default=dict, blank=True)
    corrected_answer = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "kb_user_feedback"

    def __str__(self) -> str:
        return f"Feedback {self.rating}"


class OpenAIModelPricing(models.Model):
    model_name = models.CharField(max_length=160, db_index=True)
    effective_from = models.DateTimeField()
    effective_to = models.DateTimeField(null=True, blank=True)
    input_cost_per_million_tokens = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    cached_input_cost_per_million_tokens = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    output_cost_per_million_tokens = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    currency = models.CharField(max_length=12, default="USD")
    source = models.CharField(max_length=255, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["model_name", "-effective_from"]
        db_table = "OpenAIModelPricing"
        constraints = [
            models.UniqueConstraint(
                fields=["model_name", "effective_from"],
                name="unique_openai_model_price_period",
            ),
        ]


class OpenAIUsageLog(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    section = models.CharField(max_length=120, blank=True, db_index=True)
    feature = models.CharField(max_length=160, blank=True, db_index=True)
    model = models.CharField(max_length=160, blank=True, db_index=True)
    endpoint = models.CharField(max_length=255, blank=True)
    request_id = models.CharField(max_length=255, blank=True, db_index=True)
    conversation_id = models.CharField(max_length=255, blank=True, db_index=True)
    project_id = models.CharField(max_length=255, blank=True, db_index=True)
    api_key_id = models.CharField(max_length=255, blank=True)
    input_tokens = models.PositiveBigIntegerField(default=0)
    cached_input_tokens = models.PositiveBigIntegerField(default=0)
    output_tokens = models.PositiveBigIntegerField(default=0)
    reasoning_tokens = models.PositiveBigIntegerField(default=0)
    total_tokens = models.PositiveBigIntegerField(default=0)
    estimated_cost = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    official_cost = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    latency_ms = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=40, default="Successful", db_index=True)
    error_code = models.CharField(max_length=160, blank=True)
    environment = models.CharField(max_length=80, default="development", db_index=True)
    usage_timestamp = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-usage_timestamp"]
        db_table = "OpenAIUsageLog"
        indexes = [
            models.Index(fields=["usage_timestamp", "model"], name="openai_usage_time_model"),
            models.Index(fields=["usage_timestamp", "section"], name="openai_usage_time_section"),
        ]


class VoiceInputConfiguration(models.Model):
    FEATURE_MODES = [
        ("Disabled", "Disabled"),
        ("Admin Only", "Admin Only"),
        ("Pilot Users", "Pilot Users"),
        ("Production", "Production"),
    ]
    LANGUAGE_CHOICES = [
        ("auto", "Auto Detect"),
        ("fr", "French"),
        ("en", "English"),
    ]

    name = models.CharField(max_length=120, unique=True, default="Default")
    enabled = models.BooleanField(default=True)
    provider = models.CharField(max_length=80, default="OpenAI")
    model = models.CharField(max_length=160, default="gpt-4o-mini-transcribe")
    default_language = models.CharField(max_length=12, choices=LANGUAGE_CHOICES, default="auto")
    auto_detect_language = models.BooleanField(default=True)
    maximum_duration_seconds = models.PositiveIntegerField(default=120)
    maximum_file_size_mb = models.PositiveIntegerField(default=20)
    allowed_audio_formats = models.JSONField(
        default=list,
        blank=True,
    )
    auto_send = models.BooleanField(default=False)
    store_audio = models.BooleanField(default=False)
    retention_duration_days = models.PositiveIntegerField(default=0)
    daily_user_limit_minutes = models.PositiveIntegerField(default=30)
    request_rate_limit_per_minute = models.PositiveIntegerField(default=10)
    maximum_concurrent_transcriptions = models.PositiveSmallIntegerField(default=1)
    timeout_seconds = models.PositiveIntegerField(default=120)
    retry_count = models.PositiveSmallIntegerField(default=1)
    privacy_message_fr = models.TextField(
        default=(
            "Votre audio sera utilisé uniquement pour transcrire votre question. "
            "Il ne sera pas conservé par Mining 360 AI après traitement."
        )
    )
    privacy_message_en = models.TextField(
        default=(
            "Your audio will only be used to transcribe your question. "
            "Mining 360 AI will not retain it after processing."
        )
    )
    feature_mode = models.CharField(max_length=20, choices=FEATURE_MODES, default="Production")
    stop_recording_after_silence = models.BooleanField(default=False)
    pilot_users = models.ManyToManyField(User, related_name="voice_input_pilot_configs", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        db_table = "VoiceInputConfiguration"


class VoiceTranscriptionLog(models.Model):
    STATUS_CHOICES = [
        ("Processing", "Processing"),
        ("Completed", "Completed"),
        ("Failed", "Failed"),
        ("Cancelled", "Cancelled"),
    ]

    request_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    conversation_id = models.CharField(max_length=255, blank=True, db_index=True)
    provider = models.CharField(max_length=80, blank=True)
    model = models.CharField(max_length=160, blank=True, db_index=True)
    detected_language = models.CharField(max_length=16, blank=True)
    duration_seconds = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    file_size = models.PositiveBigIntegerField(default=0)
    mime_type = models.CharField(max_length=120, blank=True)
    processing_time_ms = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Processing", db_index=True)
    error_code = models.CharField(max_length=160, blank=True)
    input_tokens = models.PositiveBigIntegerField(default=0)
    output_tokens = models.PositiveBigIntegerField(default=0)
    total_tokens = models.PositiveBigIntegerField(default=0)
    estimated_cost = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    openai_usage_log = models.OneToOneField(
        OpenAIUsageLog,
        null=True,
        blank=True,
        related_name="voice_transcription",
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "VoiceTranscriptionLog"
        indexes = [
            models.Index(fields=["user", "created_at"], name="voice_usage_user_time"),
            models.Index(fields=["status", "created_at"], name="voice_usage_status_time"),
        ]


class OpenAICostSnapshot(models.Model):
    organization_id = models.CharField(max_length=255, blank=True, db_index=True)
    project_id = models.CharField(max_length=255, blank=True, db_index=True)
    start_time = models.DateTimeField(db_index=True)
    end_time = models.DateTimeField()
    amount = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    currency = models.CharField(max_length=12, default="USD")
    line_item = models.CharField(max_length=255, blank=True)
    source_payload = models.JSONField(default=dict, blank=True)
    synchronized_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_time"]
        db_table = "OpenAICostSnapshot"
        constraints = [
            models.UniqueConstraint(
                fields=["organization_id", "project_id", "start_time", "end_time", "line_item", "currency"],
                name="unique_openai_cost_snapshot",
            ),
        ]


class OpenAIUsageSnapshot(models.Model):
    organization_id = models.CharField(max_length=255, blank=True, db_index=True)
    project_id = models.CharField(max_length=255, blank=True, db_index=True)
    model = models.CharField(max_length=160, blank=True, db_index=True)
    start_time = models.DateTimeField(db_index=True)
    end_time = models.DateTimeField()
    input_tokens = models.PositiveBigIntegerField(default=0)
    cached_input_tokens = models.PositiveBigIntegerField(default=0)
    output_tokens = models.PositiveBigIntegerField(default=0)
    requests = models.PositiveBigIntegerField(default=0)
    source_payload = models.JSONField(default=dict, blank=True)
    synchronized_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_time"]
        db_table = "OpenAIUsageSnapshot"
        constraints = [
            models.UniqueConstraint(
                fields=["organization_id", "project_id", "model", "start_time", "end_time"],
                name="unique_openai_usage_snapshot",
            ),
        ]


class OpenAIBudget(models.Model):
    name = models.CharField(max_length=160, default="Mining360 Monthly Budget")
    organization_id = models.CharField(max_length=255, blank=True)
    project_id = models.CharField(max_length=255, blank=True)
    monthly_budget = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    currency = models.CharField(max_length=12, default="USD")
    warning_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=70)
    critical_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=90)
    active = models.BooleanField(default=True)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    billing_url = models.URLField(blank=True, default="https://platform.openai.com/settings/organization/billing/credit-grants")
    timezone_name = models.CharField(max_length=80, default="UTC")
    enable_cost_synchronization = models.BooleanField(default=True)
    enable_internal_usage_logging = models.BooleanField(default=True)
    enable_credit_synchronization = models.BooleanField(default=False)
    usage_sync_frequency_minutes = models.PositiveIntegerField(default=60)
    cost_sync_frequency_minutes = models.PositiveIntegerField(default=360)
    data_retention_days = models.PositiveIntegerField(default=730)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-effective_from", "name"]
        db_table = "OpenAIBudget"


class OpenAICreditSnapshot(models.Model):
    credit_type = models.CharField(max_length=120, blank=True)
    original_amount = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    remaining_amount = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    currency = models.CharField(max_length=12, default="USD")
    expires_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=255, blank=True)
    synchronized_at = models.DateTimeField(auto_now=True)
    availability_status = models.CharField(max_length=120, default="Unavailable from API")
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-synchronized_at"]
        db_table = "OpenAICreditSnapshot"


class ResourceKnowledgeDocument(models.Model):
    STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("Processing", "Processing"),
        ("Indexed", "Indexed"),
        ("Partial", "Partial"),
        ("Failed", "Failed"),
        ("Stale", "Stale"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    resource_id = models.CharField(max_length=1000, unique=True)
    relative_path = models.CharField(max_length=1500, unique=True)
    title = models.CharField(max_length=1000)
    filename = models.CharField(max_length=1000)
    section = models.CharField(max_length=255, blank=True, db_index=True)
    category = models.CharField(max_length=255, blank=True, db_index=True)
    level = models.CharField(max_length=120, blank=True)
    file_hash = models.CharField(max_length=64, db_index=True)
    file_size = models.PositiveBigIntegerField(default=0)
    document_version = models.CharField(max_length=80, blank=True)
    language = models.CharField(max_length=12, default="en", db_index=True)
    mime_type = models.CharField(max_length=255, blank=True)
    page_count = models.PositiveIntegerField(default=0)
    section_count = models.PositiveIntegerField(default=0)
    chunk_count = models.PositiveIntegerField(default=0)
    knowledge_count = models.PositiveIntegerField(default=0)
    table_count = models.PositiveIntegerField(default=0)
    image_count = models.PositiveIntegerField(default=0)
    parser_name = models.CharField(max_length=120, blank=True)
    parser_version = models.CharField(max_length=40, blank=True)
    processing_config_version = models.CharField(max_length=40, default="1")
    validation_status = models.CharField(
        max_length=20,
        choices=[
            ("Draft", "Draft"),
            ("To Review", "To Review"),
            ("Validated", "Validated"),
            ("Rejected", "Rejected"),
            ("Superseded", "Superseded"),
        ],
        default="To Review",
        db_index=True,
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Pending", db_index=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    indexed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    metadata_json = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["section", "category", "title"]
        db_table = "ResourceKnowledgeDocument"
        indexes = [
            models.Index(fields=["status", "is_active"], name="resource_kb_doc_status_idx"),
        ]

    def __str__(self):
        return self.title


class ResourceKnowledgeSection(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(
        ResourceKnowledgeDocument,
        related_name="sections",
        on_delete=models.CASCADE,
    )
    parent = models.ForeignKey(
        "self",
        related_name="children",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    title = models.CharField(max_length=1000, blank=True)
    section_number = models.CharField(max_length=80, blank=True)
    level = models.PositiveSmallIntegerField(default=1)
    page_start = models.PositiveIntegerField(null=True, blank=True)
    page_end = models.PositiveIntegerField(null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    content = models.TextField(blank=True)
    normalized_content = models.TextField(blank=True)
    validation_status = models.CharField(max_length=20, default="To Review", db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["document", "sort_order"]
        db_table = "ResourceKnowledgeSection"
        constraints = [
            models.UniqueConstraint(
                fields=["document", "sort_order"],
                name="unique_resource_kb_section_order",
            ),
        ]


class ResourceKnowledgeChunk(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(
        ResourceKnowledgeDocument,
        related_name="chunks",
        on_delete=models.CASCADE,
    )
    section = models.ForeignKey(
        ResourceKnowledgeSection,
        related_name="chunks",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    chunk_index = models.PositiveIntegerField()
    page_start = models.PositiveIntegerField(null=True, blank=True)
    page_end = models.PositiveIntegerField(null=True, blank=True)
    heading = models.CharField(max_length=1000, blank=True)
    heading_path = models.JSONField(default=list, blank=True)
    chunk_type = models.CharField(max_length=30, default="Text", db_index=True)
    content = models.TextField()
    normalized_content = models.TextField(blank=True)
    source_reference = models.CharField(max_length=1500, blank=True)
    language = models.CharField(max_length=12, default="en", db_index=True)
    content_hash = models.CharField(max_length=64, db_index=True)
    character_count = models.PositiveIntegerField(default=0)
    token_count = models.PositiveIntegerField(default=0)
    embedding = models.JSONField(default=list, blank=True)
    embedding_model = models.CharField(max_length=120, blank=True)
    embedding_status = models.CharField(max_length=30, default="Disabled", db_index=True)
    validation_status = models.CharField(max_length=20, default="To Review", db_index=True)
    extraction_metadata = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["document", "chunk_index"]
        db_table = "ResourceKnowledgeChunk"
        constraints = [
            models.UniqueConstraint(
                fields=["document", "chunk_index"],
                name="unique_resource_kb_chunk_index",
            ),
        ]
        indexes = [
            models.Index(fields=["document", "is_active"], name="resource_kb_chunk_doc_idx"),
        ]

    def __str__(self):
        return f"{self.document.title} #{self.chunk_index}"


class ResourceKnowledgeItem(models.Model):
    VALIDATION_STATUSES = [
        ("Draft", "Draft"),
        ("To Review", "To Review"),
        ("Validated", "Validated"),
        ("Rejected", "Rejected"),
    ]
    CRITICALITY_CHOICES = [
        ("", "Not specified"),
        ("Low", "Low"),
        ("Medium", "Medium"),
        ("High", "High"),
        ("Critical", "Critical"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(
        ResourceKnowledgeDocument,
        related_name="knowledge_items",
        on_delete=models.CASCADE,
    )
    chunk = models.ForeignKey(
        ResourceKnowledgeChunk,
        related_name="knowledge_items",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    knowledge_key = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=1000)
    business_domain = models.CharField(max_length=255, blank=True, db_index=True)
    equipment = models.CharField(max_length=500, blank=True, db_index=True)
    equipment_model = models.CharField(max_length=255, blank=True, db_index=True)
    system = models.CharField(max_length=500, blank=True, db_index=True)
    component = models.CharField(max_length=500, blank=True, db_index=True)
    subcomponent = models.CharField(max_length=500, blank=True)
    symptom = models.TextField(blank=True)
    failure_mode = models.TextField(blank=True)
    fault_codes = models.JSONField(default=list, blank=True)
    probable_causes = models.JSONField(default=list, blank=True)
    occurrence_conditions = models.TextField(blank=True)
    possible_impacts = models.TextField(blank=True)
    inspection_procedure = models.TextField(blank=True)
    troubleshooting_procedure = models.TextField(blank=True)
    best_practices = models.JSONField(default=list, blank=True)
    recommendations = models.JSONField(default=list, blank=True)
    safety_instructions = models.JSONField(default=list, blank=True)
    criticality = models.CharField(max_length=20, choices=CRITICALITY_CHOICES, blank=True)
    source_excerpt = models.TextField(blank=True)
    source_page = models.PositiveIntegerField(null=True, blank=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    extraction_source = models.CharField(max_length=40, default="AI Generated")
    validation_status = models.CharField(
        max_length=20,
        choices=VALIDATION_STATUSES,
        default="To Review",
        db_index=True,
    )
    validation_notes = models.TextField(blank=True)
    validated_by = models.ForeignKey(
        User,
        related_name="validated_resource_knowledge",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["document", "source_page", "title"]
        db_table = "ResourceKnowledgeItem"
        indexes = [
            models.Index(
                fields=["validation_status", "is_active"],
                name="resource_kb_item_status_idx",
            ),
            models.Index(fields=["component", "equipment_model"], name="resource_kb_component_idx"),
        ]

    def __str__(self):
        return self.title


class ResourceKnowledgeIndexRun(models.Model):
    STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("Processing", "Processing"),
        ("Completed", "Completed"),
        ("Partially Completed", "Partially Completed"),
        ("Failed", "Failed"),
        ("Cancelled", "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    mode = models.CharField(max_length=20, default="Apply")
    scope = models.CharField(max_length=40, default="Library")
    resource_id = models.CharField(max_length=1000, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="Pending", db_index=True)
    total_documents = models.PositiveIntegerField(default=0)
    processed_documents = models.PositiveIntegerField(default=0)
    indexed_documents = models.PositiveIntegerField(default=0)
    skipped_documents = models.PositiveIntegerField(default=0)
    failed_documents = models.PositiveIntegerField(default=0)
    chunks_created = models.PositiveIntegerField(default=0)
    knowledge_created = models.PositiveIntegerField(default=0)
    embeddings_created = models.PositiveIntegerField(default=0)
    estimated_openai_calls = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    result_json = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "ResourceKnowledgeIndexRun"


class ResourceKnowledgeRetrievalLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    conversation_id = models.CharField(max_length=255, blank=True)
    query_text = models.TextField()
    filters_json = models.JSONField(default=dict, blank=True)
    result_item_ids = models.JSONField(default=list, blank=True)
    result_scores = models.JSONField(default=list, blank=True)
    result_count = models.PositiveIntegerField(default=0)
    execution_time_ms = models.PositiveIntegerField(default=0)
    mode = models.CharField(max_length=20, default="Production")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "ResourceKnowledgeRetrievalLog"


class ResourceKnowledgeConflict(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    topic = models.CharField(max_length=1000, db_index=True)
    source_a = models.ForeignKey(
        ResourceKnowledgeItem,
        related_name="conflicts_as_source_a",
        on_delete=models.CASCADE,
    )
    source_b = models.ForeignKey(
        ResourceKnowledgeItem,
        related_name="conflicts_as_source_b",
        on_delete=models.CASCADE,
    )
    conflict_description = models.TextField()
    status = models.CharField(max_length=30, default="Open", db_index=True)
    resolution = models.TextField(blank=True)
    resolved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "ResourceKnowledgeConflict"


class KnowledgeEnrichmentQueue(models.Model):
    ENRICHMENT_TYPES = [
        ("Document Summary", "Document Summary"),
        ("Glossary Extraction", "Glossary Extraction"),
        ("Business Rule Extraction", "Business Rule Extraction"),
        ("Recommended Action Extraction", "Recommended Action Extraction"),
        ("Question Generation", "Question Generation"),
        ("Few Shot Generation", "Few Shot Generation"),
        ("Embedding Generation", "Embedding Generation"),
        ("Image Analysis", "Image Analysis"),
        ("OCR", "OCR"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(
        ResourceKnowledgeDocument,
        related_name="enrichment_requests",
        on_delete=models.CASCADE,
    )
    target_section = models.CharField(max_length=255, blank=True)
    enrichment_type = models.CharField(max_length=80, choices=ENRICHMENT_TYPES)
    status = models.CharField(max_length=30, default="Pending Approval", db_index=True)
    priority = models.PositiveSmallIntegerField(default=50)
    estimated_tokens = models.PositiveIntegerField(default=0)
    estimated_cost = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    actual_tokens = models.PositiveIntegerField(default=0)
    actual_cost = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    requested_by = models.ForeignKey(
        User,
        related_name="requested_knowledge_enrichments",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    reviewed_by = models.ForeignKey(
        User,
        related_name="reviewed_knowledge_enrichments",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-priority", "created_at"]
        db_table = "KnowledgeEnrichmentQueue"


class ResourceKnowledgeConfiguration(models.Model):
    EMBEDDING_MODES = [
        ("Disabled", "Disabled"),
        ("Local", "Local"),
        ("On Demand", "On Demand"),
        ("Batch Controlled", "Batch Controlled"),
    ]
    name = models.CharField(max_length=120, unique=True, default="Best Practices Bootstrap")
    maximum_chunk_tokens = models.PositiveIntegerField(default=1500)
    minimum_chunk_tokens = models.PositiveIntegerField(default=150)
    chunk_overlap_tokens = models.PositiveIntegerField(default=150)
    preserve_tables = models.BooleanField(default=True)
    preserve_lists = models.BooleanField(default=True)
    preserve_heading_context = models.BooleanField(default=True)
    enable_resource_ocr = models.BooleanField(default=False)
    embedding_mode = models.CharField(max_length=30, choices=EMBEDDING_MODES, default="Disabled")
    parser_config_version = models.CharField(max_length=40, default="1")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ResourceKnowledgeConfiguration"


class SystemDatabaseConfig(models.Model):
    ENGINE_CHOICES = [
        ("SQL Server", "SQL Server"),
        ("Snowflake", "Snowflake"),
        ("SQLite", "SQLite"),
        ("Other", "Other"),
    ]

    name = models.CharField(max_length=255, unique=True)
    engine = models.CharField(max_length=80, choices=ENGINE_CHOICES, default="SQL Server")
    purpose = models.CharField(max_length=255, blank=True)
    host = models.CharField(max_length=255)
    port = models.PositiveIntegerField(null=True, blank=True)
    database_name = models.CharField(max_length=255, blank=True)
    schema_name = models.CharField(max_length=128, blank=True)
    username = models.CharField(max_length=255, blank=True)
    password = models.CharField(max_length=500, blank=True)
    driver = models.CharField(max_length=255, blank=True)
    connection_options = models.JSONField(default=dict, blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=80, blank=True)
    last_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["engine", "name"]
        db_table = "SystemDatabaseConfig"

    def __str__(self) -> str:
        return f"{self.name} ({self.engine})"


class SystemManagedTable(models.Model):
    CATEGORY_CHOICES = [
        ("Django Config", "Django Config"),
        ("IA Config", "IA Config"),
        ("Knowledge Base", "Knowledge Base"),
        ("Data Browser", "Data Browser"),
        ("Sources", "Sources"),
        ("Resources", "Resources"),
        ("Power BI", "Power BI"),
        ("Business Performance", "Business Performance"),
        ("OpenAI Usage", "OpenAI Usage"),
        ("Logs", "Logs"),
        ("Other", "Other"),
    ]

    database_config = models.ForeignKey(SystemDatabaseConfig, related_name="managed_tables", null=True, blank=True, on_delete=models.SET_NULL)
    schema_name = models.CharField(max_length=128, default="dbo")
    table_name = models.CharField(max_length=255)
    category = models.CharField(max_length=80, choices=CATEGORY_CHOICES, default="Django Config")
    model_name = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    row_count = models.PositiveIntegerField(default=0)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "schema_name", "table_name"]
        db_table = "SystemManagedTable"
        constraints = [
            models.UniqueConstraint(fields=["schema_name", "table_name"], name="unique_system_managed_table"),
        ]

    def __str__(self) -> str:
        return f"{self.schema_name}.{self.table_name}"


class SystemIntegrationConfig(models.Model):
    TYPE_CHOICES = [
        ("Power BI", "Power BI"),
        ("Power Automate", "Power Automate"),
        ("OpenAI", "OpenAI"),
        ("Database", "Database"),
        ("Data Source", "Data Source"),
        ("Storage", "Storage"),
        ("Authentication", "Authentication"),
        ("Active Directory", "Active Directory"),
        ("Notification", "Notification"),
        ("Other", "Other"),
    ]
    STATUS_CHOICES = [
        ("Not Configured", "Not Configured"),
        ("Configured", "Configured"),
        ("Connected", "Connected"),
        ("Failed", "Failed"),
        ("Disabled", "Disabled"),
    ]

    code = models.SlugField(max_length=120, unique=True)
    name = models.CharField(max_length=255)
    integration_type = models.CharField(max_length=40, choices=TYPE_CHOICES)
    provider = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    settings_json = models.JSONField(default=dict, blank=True)
    encrypted_secrets = models.TextField(blank=True)
    configured_secret_keys = models.JSONField(default=list, blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="Not Configured")
    last_verified_at = models.DateTimeField(null=True, blank=True)
    last_message = models.TextField(blank=True)
    created_by = models.ForeignKey(
        User, null=True, blank=True, related_name="created_system_integrations", on_delete=models.SET_NULL
    )
    updated_by = models.ForeignKey(
        User, null=True, blank=True, related_name="updated_system_integrations", on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["integration_type", "name"]
        db_table = "SystemIntegrationConfig"
        indexes = [
            models.Index(fields=["integration_type", "is_active"], name="system_integration_type_idx"),
        ]

    def __str__(self):
        return f"{self.name} ({self.integration_type})"


class SystemParameter(models.Model):
    VALUE_TYPES = [
        ("Text", "Text"),
        ("Integer", "Integer"),
        ("Decimal", "Decimal"),
        ("Boolean", "Boolean"),
        ("JSON", "JSON"),
        ("URL", "URL"),
        ("Duration", "Duration"),
    ]

    key = models.SlugField(max_length=160, unique=True)
    category = models.CharField(max_length=80, db_index=True)
    label = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    value_type = models.CharField(max_length=20, choices=VALUE_TYPES, default="Text")
    value_json = models.JSONField(null=True, blank=True)
    default_value_json = models.JSONField(null=True, blank=True)
    options_json = models.JSONField(default=list, blank=True)
    is_required = models.BooleanField(default=False)
    is_runtime_editable = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    validation_pattern = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(
        User, null=True, blank=True, related_name="created_system_parameters", on_delete=models.SET_NULL
    )
    updated_by = models.ForeignKey(
        User, null=True, blank=True, related_name="updated_system_parameters", on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "label"]
        db_table = "SystemParameter"
        indexes = [models.Index(fields=["category", "is_active"], name="system_parameter_cat_idx")]

    def __str__(self):
        return f"{self.category} / {self.label}"


class BusinessPerformanceConfig(models.Model):
    AUTH_CHOICES = [
        ("Existing Power BI connection", "Existing Power BI connection"),
        ("Service Principal", "Service Principal"),
        ("Power Automate", "Power Automate"),
    ]

    name = models.CharField(max_length=120, unique=True, default="Business Performance")
    workspace_id = models.CharField(max_length=128, blank=True)
    semantic_model_name = models.CharField(max_length=255, default="Customer Fleet & Revenue Planning Model")
    semantic_model_id = models.CharField(max_length=128, blank=True)
    report_id = models.CharField(max_length=128, blank=True)
    tenant_id = models.CharField(max_length=128, blank=True)
    authentication_mode = models.CharField(max_length=80, choices=AUTH_CHOICES, default="Power Automate")
    api_endpoint = models.CharField(max_length=500, blank=True)
    xmla_endpoint = models.CharField(max_length=500, blank=True)
    default_currency = models.CharField(max_length=16, default="EUR")
    default_date_range = models.CharField(max_length=80, default="Current Year")
    default_lob = models.CharField(max_length=120, blank=True)
    default_division = models.CharField(max_length=120, blank=True)
    cache_duration_seconds = models.PositiveIntegerField(default=300)
    query_timeout_seconds = models.PositiveIntegerField(default=300)
    top_n_default = models.PositiveIntegerField(default=20)
    active_fleet_status_value = models.CharField(max_length=20, default="-1")
    opportunity_threshold_mode = models.CharField(max_length=20, default="median")
    opportunity_fleet_threshold = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    opportunity_revenue_threshold = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    last_successful_refresh = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "bp_config"

    def __str__(self) -> str:
        return self.name


class BusinessPerformanceMapping(models.Model):
    OBJECT_TYPES = [
        ("measure", "Measure"),
        ("column", "Column"),
    ]
    CATEGORIES = [
        ("metric", "Metric"),
        ("filter", "Filter"),
        ("customer", "Customer"),
        ("parts", "Parts Sales"),
        ("prime", "Machine Sales"),
        ("fleet", "Fleet"),
    ]

    logical_name = models.SlugField(max_length=120, unique=True)
    display_name = models.CharField(max_length=255)
    category = models.CharField(max_length=40, choices=CATEGORIES)
    object_type = models.CharField(max_length=20, choices=OBJECT_TYPES)
    table_name = models.CharField(max_length=255, blank=True)
    object_name = models.CharField(max_length=255, blank=True)
    data_type = models.CharField(max_length=40, default="text")
    format_string = models.CharField(max_length=80, blank=True)
    description = models.TextField(blank=True)
    is_required = models.BooleanField(default=False)
    is_visible = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "display_order", "display_name"]
        db_table = "bp_mappings"

    def __str__(self) -> str:
        return f"{self.logical_name} -> {self.object_name or 'Not configured'}"


class BusinessPerformanceQueryLog(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    page = models.CharField(max_length=80)
    action = models.CharField(max_length=120)
    filters = models.JSONField(default=dict, blank=True)
    dax_query = models.TextField(blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=30, default="Completed")
    error_message = models.TextField(blank=True)
    row_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "bp_query_logs"

    def __str__(self) -> str:
        return f"{self.page} - {self.status}"


class DescriptionCATReference(models.Model):
    VALIDATION_STATUSES = [(value, value) for value in ("Draft", "To Review", "Validated", "Rejected", "Deprecated")]

    code = models.SlugField(max_length=140, unique=True)
    name = models.CharField(max_length=255, unique=True)
    display_name = models.CharField(max_length=255)
    definition = models.TextField(blank=True)
    category = models.CharField(max_length=120, blank=True)
    parent_category = models.ForeignKey("self", null=True, blank=True, related_name="children", on_delete=models.SET_NULL)
    classification_type = models.CharField(max_length=80, default="technical")
    examples_json = models.JSONField(default=list, blank=True)
    keywords_json = models.JSONField(default=list, blank=True)
    synonyms_json = models.JSONField(default=list, blank=True)
    exclusion_terms_json = models.JSONField(default=list, blank=True)
    applicable_work_types_json = models.JSONField(default=list, blank=True)
    applicable_families_json = models.JSONField(default=list, blank=True)
    applicable_models_json = models.JSONField(default=list, blank=True)
    active = models.BooleanField(default=True, db_index=True)
    validation_status = models.CharField(max_length=20, choices=VALIDATION_STATUSES, default="To Review", db_index=True)
    version = models.CharField(max_length=40, default="1.0")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_name"]
        db_table = "DescriptionCATReference"
        permissions = [("manage_description_cat_reference", "Can manage Description CAT reference")]

    def __str__(self):
        return self.display_name


class DescriptionCATClassificationRule(models.Model):
    VALIDATION_STATUSES = DescriptionCATReference.VALIDATION_STATUSES

    rule_code = models.SlugField(max_length=140, unique=True)
    name = models.CharField(max_length=255)
    condition_json = models.JSONField(default=dict, blank=True)
    priority = models.PositiveIntegerField(default=100)
    expected_description_cat = models.ForeignKey(DescriptionCATReference, related_name="classification_rules", on_delete=models.PROTECT)
    explanation = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    validation_status = models.CharField(max_length=20, choices=VALIDATION_STATUSES, default="To Review")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority", "name"]
        db_table = "DescriptionCATClassificationRule"


class GenericDowntimeCommentRule(models.Model):
    MATCH_TYPES = [(value, value) for value in ("Exact", "Contains", "Regex")]

    expression = models.CharField(max_length=500)
    language = models.CharField(max_length=10, default="all")
    match_type = models.CharField(max_length=20, choices=MATCH_TYPES, default="Exact")
    active = models.BooleanField(default=True)
    validation_status = models.CharField(max_length=20, choices=DescriptionCATReference.VALIDATION_STATUSES, default="Validated")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["expression"]
        db_table = "GenericDowntimeCommentRule"


class DowntimeMappingCheckRun(models.Model):
    STATUSES = [(value, value) for value in (
        "Draft", "Previewed", "Queued", "Running", "Partially Completed", "Completed", "Failed", "Cancelled",
    )]
    MODES = [("full", "Full AI Audit"), ("smart", "Smart Audit")]
    PROCESSING_METHODS = [("standard", "Real-time / standard"), ("batch", "Provider batch")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_by = models.ForeignKey(User, null=True, related_name="downtime_mapping_runs", on_delete=models.SET_NULL)
    start_date = models.DateField()
    end_date = models.DateField()
    filters_json = models.JSONField(default=dict, blank=True)
    execution_mode = models.CharField(max_length=20, choices=MODES, default="full")
    provider = models.CharField(max_length=100, blank=True)
    model_name = models.CharField(max_length=180, blank=True)
    processing_method = models.CharField(max_length=20, choices=PROCESSING_METHODS, default="standard")
    taxonomy_version = models.CharField(max_length=40, default="1.0")
    mapping_rule_version = models.CharField(max_length=40, default="1.0")
    prompt_version = models.CharField(max_length=80, default="DOWNTIME_DESCRIPTION_CAT_CLASSIFICATION_V1")
    total_rows = models.PositiveIntegerField(default=0)
    cached_rows = models.PositiveIntegerField(default=0)
    ai_rows = models.PositiveIntegerField(default=0)
    processed_rows = models.PositiveIntegerField(default=0)
    verified_rows = models.PositiveIntegerField(default=0)
    likely_correct_rows = models.PositiveIntegerField(default=0)
    mismatch_rows = models.PositiveIntegerField(default=0)
    ambiguous_rows = models.PositiveIntegerField(default=0)
    insufficient_evidence_rows = models.PositiveIntegerField(default=0)
    unmapped_rows = models.PositiveIntegerField(default=0)
    taxonomy_gap_rows = models.PositiveIntegerField(default=0)
    failed_rows = models.PositiveIntegerField(default=0)
    estimated_tokens = models.PositiveBigIntegerField(default=0)
    actual_input_tokens = models.PositiveBigIntegerField(default=0)
    actual_output_tokens = models.PositiveBigIntegerField(default=0)
    estimated_cost = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    actual_cost = models.DecimalField(max_digits=18, decimal_places=8, default=0)
    comment_coverage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    status = models.CharField(max_length=30, choices=STATUSES, default="Draft", db_index=True)
    error_message = models.TextField(blank=True)
    cancellation_requested = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "DowntimeMappingCheckRun"
        permissions = [
            ("view_downtime_mapping_checks", "Can view downtime mapping checks"),
            ("create_downtime_mapping_check", "Can create downtime mapping checks"),
            ("cancel_downtime_mapping_check", "Can cancel downtime mapping checks"),
            ("view_downtime_mapping_costs", "Can view downtime mapping costs"),
            ("export_downtime_mapping_results", "Can export downtime mapping results"),
        ]


class DowntimeMappingCheckItem(models.Model):
    MAPPING_STATUSES = [(value, value) for value in (
        "VERIFIED", "LIKELY_CORRECT", "MISMATCH", "AMBIGUOUS", "INSUFFICIENT_EVIDENCE", "UNMAPPED", "TAXONOMY_GAP", "AI_ERROR",
    )]
    REVIEW_STATUSES = [(value, value) for value in ("Unreviewed", "Approved Current", "Approved Recommendation", "Alternative Selected", "Rejected", "Ambiguous", "Insufficient Evidence")]

    run = models.ForeignKey(DowntimeMappingCheckRun, related_name="items", on_delete=models.CASCADE)
    downtime_event_id = models.CharField(max_length=120)
    source_system = models.CharField(max_length=120, default="MiningProd")
    minesite = models.CharField(max_length=255, blank=True)
    customer = models.CharField(max_length=255, blank=True)
    model = models.CharField(max_length=120, blank=True)
    family = models.CharField(max_length=255, blank=True)
    serial_number = models.CharField(max_length=120, blank=True)
    event_start = models.DateTimeField(null=True, blank=True)
    event_end = models.DateTimeField(null=True, blank=True)
    downtime_hours = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    labour_type = models.CharField(max_length=500, blank=True)
    current_description_cat = models.CharField(max_length=500, blank=True)
    comment_snapshot = models.TextField(blank=True)
    sanitized_comment = models.TextField(blank=True)
    sanitization_status = models.CharField(max_length=30, default="unchanged")
    component_snapshot = models.CharField(max_length=500, blank=True)
    cause_snapshot = models.CharField(max_length=500, blank=True)
    work_type_snapshot = models.CharField(max_length=255, blank=True)
    down_type_snapshot = models.CharField(max_length=255, blank=True)
    comment_quality = models.CharField(max_length=30, default="Empty", db_index=True)
    recommended_description_cat = models.ForeignKey(DescriptionCATReference, null=True, blank=True, related_name="check_items", on_delete=models.SET_NULL)
    mapping_status = models.CharField(max_length=30, choices=MAPPING_STATUSES, db_index=True)
    confidence = models.PositiveSmallIntegerField(default=0)
    reason = models.TextField(blank=True)
    evidence_phrases_json = models.JSONField(default=list, blank=True)
    detected_information_json = models.JSONField(default=dict, blank=True)
    alternative_candidates_json = models.JSONField(default=list, blank=True)
    candidate_list_json = models.JSONField(default=list, blank=True)
    requires_review = models.BooleanField(default=False, db_index=True)
    review_status = models.CharField(max_length=30, choices=REVIEW_STATUSES, default="Unreviewed", db_index=True)
    reviewed_by = models.ForeignKey(User, null=True, blank=True, related_name="reviewed_downtime_mappings", on_delete=models.SET_NULL)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    approved_description_cat = models.ForeignKey(DescriptionCATReference, null=True, blank=True, related_name="approved_check_items", on_delete=models.SET_NULL)
    applied = models.BooleanField(default=False)
    classification_signature = models.CharField(max_length=64, db_index=True)
    comparison_signature = models.CharField(max_length=64, db_index=True)
    request_id = models.CharField(max_length=255, blank=True)
    classification_payload_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-confidence", "downtime_event_id"]
        db_table = "DowntimeMappingCheckItem"
        constraints = [models.UniqueConstraint(fields=["run", "downtime_event_id"], name="unique_mapping_check_event")]
        indexes = [models.Index(fields=["run", "mapping_status"], name="mapping_run_status_idx")]
        permissions = [
            ("review_downtime_mapping", "Can review downtime mapping results"),
            ("apply_downtime_mapping_corrections", "Can apply approved downtime mapping corrections"),
        ]


class DowntimeMappingReviewDecision(models.Model):
    DECISIONS = [(value, value) for value in (
        "Approve Current", "Approve AI Recommendation", "Select Another Description CAT", "Mark Ambiguous", "Mark Insufficient Evidence", "Reject AI Result",
    )]

    check_item = models.ForeignKey(DowntimeMappingCheckItem, related_name="review_decisions", on_delete=models.CASCADE)
    original_current_description_cat = models.CharField(max_length=500, blank=True)
    ai_recommended_description_cat = models.CharField(max_length=500, blank=True)
    reviewer_selected_description_cat = models.ForeignKey(DescriptionCATReference, null=True, blank=True, on_delete=models.SET_NULL)
    decision = models.CharField(max_length=60, choices=DECISIONS)
    notes = models.TextField(blank=True)
    reviewer = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "DowntimeMappingReviewDecision"
