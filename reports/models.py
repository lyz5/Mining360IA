from django.db import models
from django.contrib.auth.models import User


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


class DataBrowser(models.Model):
    name = models.CharField(max_length=255)
    display_order = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True)
    table_name = models.CharField(max_length=255, unique=True)
    source_view_name = models.CharField(max_length=255)
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
    data_type = models.CharField(max_length=20, choices=DATA_TYPES)
    length = models.PositiveIntegerField(null=True, blank=True)
    is_required = models.BooleanField(default=False)
    is_unique = models.BooleanField(default=False)
    default_value = models.CharField(max_length=255, blank=True)
    display_order = models.PositiveIntegerField(default=0)
    is_visible = models.BooleanField(default=True)
    is_lookup = models.BooleanField(default=False)
    lookup_source_name = models.CharField(max_length=255, blank=True)
    lookup_value_column = models.CharField(max_length=128, blank=True)
    lookup_label_column = models.CharField(max_length=128, blank=True)
    lookup_filter = models.CharField(max_length=255, blank=True)
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
    section = models.ForeignKey(AIConfigSection, related_name="interaction_reports", on_delete=models.CASCADE)
    workspace_id = models.CharField(max_length=128)
    report_id = models.CharField(max_length=128, unique=True)
    report_name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255)
    semantic_model_id = models.CharField(max_length=128, blank=True)
    embed_url = models.TextField(blank=True)
    description = models.TextField(blank=True)
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
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        db_table = "ai_conversation_contexts"
        constraints = [
            models.UniqueConstraint(fields=["conversation_id", "user"], name="unique_ai_context_per_user"),
        ]


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
