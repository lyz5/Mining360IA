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
    PowerAppsLaunchContext,
    PrimeMoversIntegrationConfiguration,
    PrimeMoversIntegrationExecutionLog,
    UserExternalIdentity,
)


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


@admin.register(PrimeMoversIntegrationConfiguration)
class PrimeMoversIntegrationConfigurationAdmin(admin.ModelAdmin):
    list_display = ("code", "report", "powerapps_app_id", "iframe_enabled", "new_tab_fallback", "validation_status", "active")
    list_filter = ("validation_status", "iframe_enabled", "new_tab_fallback", "active")
    search_fields = ("code", "report__display_name", "powerapps_app_id")
    fieldsets = (
        (None, {"fields": ("code", "report", "active", "validation_status")}),
        ("Power BI", {"fields": (
            "powerbi_page_internal_name", "powerbi_safe_initial_page_internal_name",
            "powerapps_visual_internal_name", "powerapps_visual_type",
        )}),
        ("Power Apps", {"fields": (
            "powerapps_app_id", "powerapps_tenant_id", "powerapps_environment_id",
            "powerapps_launch_url", "iframe_enabled", "new_tab_fallback",
        )}),
        ("Dataverse context transfer", {"fields": (
            "context_transfer_mode", "context_expiration_minutes",
            "dataverse_environment_url", "dataverse_context_entity_set",
        )}),
    )


@admin.register(UserExternalIdentity)
class UserExternalIdentityAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "upn", "tenant_id", "mapping_status", "active", "last_verified_at")
    list_filter = ("provider", "mapping_status", "active")
    search_fields = ("user__username", "upn", "external_object_id", "windows_identity")


@admin.register(PowerAppsLaunchContext)
class PowerAppsLaunchContextAdmin(admin.ModelAdmin):
    list_display = ("opaque_id", "user", "serial_number", "mine_site", "status", "expires_at", "created_at")
    list_filter = ("status", "created_at")
    readonly_fields = tuple(field.name for field in PowerAppsLaunchContext._meta.fields)


@admin.register(PrimeMoversIntegrationExecutionLog)
class PrimeMoversIntegrationExecutionLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "report", "selected_strategy", "powerbi_status", "powerapps_status", "error_code")
    list_filter = ("selected_strategy", "powerbi_status", "powerapps_status", "error_code")
    readonly_fields = tuple(field.name for field in PrimeMoversIntegrationExecutionLog._meta.fields)
