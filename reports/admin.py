from django.contrib import admin

from .models import (
    ActiveDirectoryAuthenticationAuditLog,
    UserAccessAuditLog,
    ActiveDirectorySyncRun,
    DescriptionCATClassificationRule,
    DescriptionCATReference,
    DowntimeMappingCheckItem,
    DowntimeMappingCheckRun,
    DowntimeMappingReviewDecision,
    GenericDowntimeCommentRule,
    HomepageConfiguration,
    HomepageInteractionEvent,
    ReportCategory,
    ReportVisualAsset,
    UserExternalIdentity,
    AIActionContract,
    AICapabilityOperation,
    AIChatInteractionEvent,
    AIChatSuggestion,
    AIConversationExecution,
    AIDependencyHealthSnapshot,
    AISuggestionCertification,
    FeaturePilotMembership,
    BusinessAccount,
    BusinessCompanyCodeReference,
    KeyAccount,
    KeyAccountMembership,
    SourceAccountRecord,
    SourceAccountFieldOverride,
    BusinessAccountAlias,
    MineSite,
    AccountMineSiteCandidate,
    AccountMineSiteMapping,
    AccountMineSiteMappingVersion,
    RevenueSiteAllocationRule,
    MappingPublication,
    MappingAuditLog,
    MappingSynchronizationRun,
    BusinessReviewSnapshot,
    BusinessPortfolioThresholdRule,
    BusinessOpportunity,
    BusinessRisk,
    BusinessReviewAction,
    BusinessDecision,
    BusinessReviewSavedView,
)


@admin.register(BusinessAccount)
class BusinessAccountAdmin(admin.ModelAdmin):
    list_display = ("canonical_account_name", "canonical_account_code", "country", "assigned_operating_country", "validation_status", "active")
    list_filter = ("validation_status", "active", "country", "assigned_operating_country")
    search_fields = ("canonical_account_name", "canonical_account_code", "account_group")


@admin.register(BusinessCompanyCodeReference)
class BusinessCompanyCodeReferenceAdmin(admin.ModelAdmin):
    list_display = (
        "company_code", "legal_entity_name", "operating_country_code",
        "classification_type", "validation_status", "active",
    )
    list_filter = ("operating_country_code", "classification_type", "validation_status", "active")
    search_fields = ("company_code", "legal_entity_name", "address")


@admin.register(KeyAccount)
class KeyAccountAdmin(admin.ModelAdmin):
    list_display = ("key_account_name", "key_account_code", "version", "active", "updated_at")
    list_filter = ("active",)
    search_fields = ("key_account_name", "key_account_code")


@admin.register(KeyAccountMembership)
class KeyAccountMembershipAdmin(admin.ModelAdmin):
    list_display = ("key_account", "business_account", "active", "created_by", "created_at")
    list_filter = ("active", "key_account")
    search_fields = ("key_account__key_account_name", "business_account__canonical_account_name")
    raw_id_fields = ("key_account", "business_account")


@admin.register(SourceAccountRecord)
class SourceAccountRecordAdmin(admin.ModelAdmin):
    list_display = ("source_account_name", "source_record_id", "source_system", "canonical_account", "active", "source_last_seen_at")
    list_filter = ("source_system", "active")
    search_fields = ("source_account_name", "source_record_id", "code_cic")
    raw_id_fields = ("canonical_account", "synchronization_run")


@admin.register(SourceAccountFieldOverride)
class SourceAccountFieldOverrideAdmin(admin.ModelAdmin):
    list_display = ("source_record_id", "field_name", "source_value", "corrected_value", "active", "validated_at")
    list_filter = ("source_system", "field_name", "active")
    search_fields = ("source_record_id", "reason")


@admin.register(BusinessAccountAlias)
class BusinessAccountAliasAdmin(admin.ModelAdmin):
    list_display = ("alias", "canonical_account", "source_system", "validation_status", "active")
    list_filter = ("validation_status", "active", "source_system")
    search_fields = ("alias", "normalized_alias", "canonical_account__canonical_account_name")


@admin.register(MineSite)
class MineSiteAdmin(admin.ModelAdmin):
    list_display = ("canonical_minesite_name", "minesite_code", "country", "status", "validation_status", "active")
    list_filter = ("status", "validation_status", "active", "country")
    search_fields = ("canonical_minesite_name", "minesite_code")


@admin.register(AccountMineSiteCandidate)
class AccountMineSiteCandidateAdmin(admin.ModelAdmin):
    list_display = ("source_account", "candidate_minesite", "confidence_score", "suggestion_method", "status", "generated_at")
    list_filter = ("status", "suggestion_method")
    search_fields = ("source_account__source_account_name", "candidate_minesite__canonical_minesite_name")


@admin.register(AccountMineSiteMapping)
class AccountMineSiteMappingAdmin(admin.ModelAdmin):
    list_display = ("business_account", "minesite", "account_role", "relationship_status", "revenue_allocation_status", "current_version", "active")
    list_filter = ("relationship_status", "revenue_allocation_status", "account_role", "active")
    search_fields = ("business_account__canonical_account_name", "minesite__canonical_minesite_name")
    readonly_fields = ("current_version", "created_at", "updated_at")


@admin.register(AccountMineSiteMappingVersion)
class AccountMineSiteMappingVersionAdmin(admin.ModelAdmin):
    list_display = ("mapping", "version_number", "status", "created_by", "created_at")
    list_filter = ("status", "created_at")
    readonly_fields = tuple(field.name for field in AccountMineSiteMappingVersion._meta.fields)


@admin.register(RevenueSiteAllocationRule)
class RevenueSiteAllocationRuleAdmin(admin.ModelAdmin):
    list_display = ("business_account", "minesite", "lob", "allocation_method", "allocation_percentage", "status", "valid_from")
    list_filter = ("status", "allocation_method", "lob")


@admin.register(MappingPublication)
class MappingPublicationAdmin(admin.ModelAdmin):
    list_display = ("version", "status", "mapping_count", "account_count", "minesite_count", "published_at")
    list_filter = ("status",)
    readonly_fields = tuple(field.name for field in MappingPublication._meta.fields)


@admin.register(MappingAuditLog)
class MappingAuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "actor", "action", "entity_type", "entity_id")
    list_filter = ("action", "entity_type", "timestamp")
    search_fields = ("entity_id", "reason", "actor__username")
    readonly_fields = tuple(field.name for field in MappingAuditLog._meta.fields)


@admin.register(MappingSynchronizationRun)
class MappingSynchronizationRunAdmin(admin.ModelAdmin):
    list_display = ("created_at", "source", "status", "records_read", "records_created", "records_updated")
    list_filter = ("status", "source")
    readonly_fields = tuple(field.name for field in MappingSynchronizationRun._meta.fields)


@admin.register(BusinessReviewSnapshot)
class BusinessReviewSnapshotAdmin(admin.ModelAdmin):
    list_display = ("generated_at", "mapping_publication", "source_synchronization", "status", "confidence_status", "business_rule_version")
    list_filter = ("status", "confidence_status", "business_rule_version")
    readonly_fields = tuple(field.name for field in BusinessReviewSnapshot._meta.fields)


@admin.register(BusinessPortfolioThresholdRule)
class BusinessPortfolioThresholdRuleAdmin(admin.ModelAdmin):
    list_display = ("code", "revenue_lens", "scope_country", "method", "validation_status", "rule_version", "active")
    list_filter = ("revenue_lens", "method", "validation_status", "active")


@admin.register(BusinessOpportunity)
class BusinessOpportunityAdmin(admin.ModelAdmin):
    list_display = ("opportunity_code", "minesite", "business_account", "revenue_lens", "severity", "status", "detected_at")
    list_filter = ("revenue_lens", "severity", "status")


@admin.register(BusinessRisk)
class BusinessRiskAdmin(admin.ModelAdmin):
    list_display = ("risk_code", "minesite", "business_account", "severity", "status", "detected_at")
    list_filter = ("severity", "status")


@admin.register(BusinessReviewAction)
class BusinessReviewActionAdmin(admin.ModelAdmin):
    list_display = ("title", "priority", "owner", "due_date", "status", "updated_at")
    list_filter = ("priority", "status")
    search_fields = ("title", "description", "notes")


@admin.register(BusinessDecision)
class BusinessDecisionAdmin(admin.ModelAdmin):
    list_display = ("title", "decided_by", "decision_date", "review_date", "status")
    list_filter = ("status", "decision_date")


@admin.register(BusinessReviewSavedView)
class BusinessReviewSavedViewAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "visualization", "updated_at")


@admin.register(ReportCategory)
class ReportCategoryAdmin(admin.ModelAdmin):
    list_display = ("display_name", "code", "accent_code", "illustration_code", "validation_status", "active")
    list_filter = ("accent_code", "validation_status", "active")
    search_fields = ("display_name", "code", "description")


@admin.register(ReportVisualAsset)
class ReportVisualAssetAdmin(admin.ModelAdmin):
    list_display = ("name", "asset_type", "category", "file_size", "validation_status", "active")
    list_filter = ("asset_type", "validation_status", "active")
    search_fields = ("name", "illustration_code")


@admin.register(HomepageConfiguration)
class HomepageConfigurationAdmin(admin.ModelAdmin):
    list_display = (
        "code", "default_kpi", "default_period", "default_breakdown",
        "animation_enabled", "cache_duration_seconds", "active",
    )
    list_filter = ("default_period", "default_breakdown", "animation_enabled", "active")
    fieldsets = (
        (None, {"fields": ("code", "active", "default_kpi", "default_period", "default_breakdown")}),
        ("Content", {"fields": (
            "show_target", "show_comparison", "show_top_performers",
            "show_bottom_performers", "show_ai_insight", "maximum_cards",
            "equipment_page_size",
        )}),
        ("Experience", {"fields": ("animation_enabled", "animation_intensity")}),
        ("Performance", {"fields": ("cache_duration_seconds", "freshness_threshold_hours")}),
    )


@admin.register(HomepageInteractionEvent)
class HomepageInteractionEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "event_type")
    list_filter = ("event_type", "created_at")
    search_fields = ("user__username", "user__email")
    readonly_fields = tuple(field.name for field in HomepageInteractionEvent._meta.fields)


@admin.register(DescriptionCATReference)
class DescriptionCATReferenceAdmin(admin.ModelAdmin):
    list_display = ("display_name", "code", "classification_type", "validation_status", "version", "active")
    list_filter = ("validation_status", "classification_type", "active", "version")
    search_fields = ("name", "display_name", "code", "definition")


@admin.register(DescriptionCATClassificationRule)
class DescriptionCATClassificationRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "priority", "expected_description_cat", "validation_status", "active")
    list_filter = ("validation_status", "active")
    ordering = ("priority", "name")


@admin.register(GenericDowntimeCommentRule)
class GenericDowntimeCommentRuleAdmin(admin.ModelAdmin):
    list_display = ("expression", "language", "match_type", "validation_status", "active")
    list_filter = ("language", "match_type", "validation_status", "active")


@admin.register(DowntimeMappingCheckRun)
class DowntimeMappingCheckRunAdmin(admin.ModelAdmin):
    list_display = ("id", "start_date", "end_date", "execution_mode", "status", "total_rows", "mismatch_rows", "created_by", "created_at")
    list_filter = ("status", "execution_mode", "processing_method")
    readonly_fields = ("created_at", "updated_at", "started_at", "completed_at")


@admin.register(DowntimeMappingCheckItem)
class DowntimeMappingCheckItemAdmin(admin.ModelAdmin):
    list_display = ("downtime_event_id", "mapping_status", "labour_type", "current_description_cat", "recommended_description_cat", "confidence", "review_status")
    list_filter = ("mapping_status", "comment_quality", "review_status", "requires_review")
    search_fields = ("downtime_event_id", "serial_number", "labour_type", "current_description_cat", "comment_snapshot")
    readonly_fields = ("classification_payload_json", "classification_signature", "comparison_signature")


admin.site.register(DowntimeMappingReviewDecision)


@admin.register(ActiveDirectorySyncRun)
class ActiveDirectorySyncRunAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "discovered_users", "created_users", "updated_users", "disabled_users", "failed_users", "created_by", "started_at")
    list_filter = ("status", "started_at")
    readonly_fields = tuple(field.name for field in ActiveDirectorySyncRun._meta.fields)


@admin.register(ActiveDirectoryAuthenticationAuditLog)
class ActiveDirectoryAuthenticationAuditLogAdmin(admin.ModelAdmin):
    list_display = ("username", "status", "reason_code", "source_ip", "created_at")
    list_filter = ("status", "reason_code", "created_at")
    search_fields = ("username", "source_ip")
    readonly_fields = tuple(field.name for field in ActiveDirectoryAuthenticationAuditLog._meta.fields)


@admin.register(UserAccessAuditLog)
class UserAccessAuditLogAdmin(admin.ModelAdmin):
    list_display = ("platform_user", "action", "actor", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("platform_user__display_name", "platform_user__user_principal_name", "actor__username")
    readonly_fields = tuple(field.name for field in UserAccessAuditLog._meta.fields)


@admin.register(UserExternalIdentity)
class UserExternalIdentityAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "upn", "tenant_id", "mapping_status", "active", "last_verified_at")
    list_filter = ("provider", "mapping_status", "active")
    search_fields = ("user__username", "upn", "external_object_id", "windows_identity")


@admin.register(AICapabilityOperation)
class AICapabilityOperationAdmin(admin.ModelAdmin):
    list_display = ("operation_code", "capability", "readiness_status", "readiness_score", "validation_status", "active", "last_validated_at")
    list_filter = ("readiness_status", "validation_status", "active", "domain_code")
    search_fields = ("operation_code", "display_name_en", "display_name_fr")


@admin.register(AIChatSuggestion)
class AIChatSuggestionAdmin(admin.ModelAdmin):
    list_display = ("suggestion_code", "action_type", "operation", "reliability_tier", "certification_status", "certification_environment", "active")
    list_filter = ("action_type", "reliability_tier", "certification_status", "certification_environment", "active")
    search_fields = ("suggestion_code", "label_en", "label_fr")


@admin.register(AISuggestionCertification)
class AISuggestionCertificationAdmin(admin.ModelAdmin):
    list_display = ("suggestion", "environment", "test_case_code", "certification_status", "passed", "duration_ms", "tested_at")
    list_filter = ("environment", "certification_status", "passed", "automated")
    readonly_fields = ("created_at",)


@admin.register(AIActionContract)
class AIActionContractAdmin(admin.ModelAdmin):
    list_display = ("action_code", "operation", "readiness_status", "certification_status", "validation_status", "active")
    list_filter = ("readiness_status", "certification_status", "validation_status", "active")


@admin.register(FeaturePilotMembership)
class FeaturePilotMembershipAdmin(admin.ModelAdmin):
    list_display = ("feature_flag", "user", "group", "start_at", "end_at", "active")
    list_filter = ("feature_flag", "active")


@admin.register(AIDependencyHealthSnapshot)
class AIDependencyHealthSnapshotAdmin(admin.ModelAdmin):
    list_display = ("dependency_code", "status", "response_time_ms", "checked_at", "expires_at")
    list_filter = ("status",)


@admin.register(AIChatInteractionEvent)
class AIChatInteractionEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event_type", "user", "suggestion", "action_code", "operation_code", "outcome", "duration_ms")
    list_filter = ("event_type", "outcome", "created_at")
    readonly_fields = tuple(field.name for field in AIChatInteractionEvent._meta.fields)


@admin.register(AIConversationExecution)
class AIConversationExecutionAdmin(admin.ModelAdmin):
    list_display = ("started_at", "client_execution_id", "conversation", "status", "suggestion_code", "action_code", "retry_count", "completed_at")
    list_filter = ("status", "suggestion_code", "action_code", "started_at")
    readonly_fields = tuple(field.name for field in AIConversationExecution._meta.fields)
