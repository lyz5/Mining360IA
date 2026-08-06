from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class DeploymentTarget(models.Model):
    ENVIRONMENTS = [
        ("Development", "Development"),
        ("Test", "Test"),
        ("Staging", "Staging"),
        ("Preproduction", "Preproduction"),
        ("Production", "Production"),
        ("Disaster Recovery", "Disaster Recovery"),
    ]
    CONNECTION_MODES = [("ssh", "Agentless SSH"), ("agent", "Deployment Agent")]
    OS_FAMILIES = [
        ("debian", "Debian / Ubuntu"),
        ("redhat", "Red Hat / Rocky / AlmaLinux"),
        ("windows", "Windows Server (inventory only)"),
        ("unknown", "Unknown"),
    ]
    STATUSES = [
        ("Not Configured", "Not Configured"),
        ("Pending Approval", "Pending Approval"),
        ("Online", "Online"),
        ("Offline", "Offline"),
        ("Blocked", "Blocked"),
    ]

    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    environment = models.CharField(max_length=30, choices=ENVIRONMENTS, default="Test")
    hostname = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True, protocol="both")
    dns_name = models.CharField(max_length=255, blank=True)
    port = models.PositiveIntegerField(default=22)
    operating_system = models.CharField(max_length=150, blank=True)
    operating_system_version = models.CharField(max_length=100, blank=True)
    os_family = models.CharField(max_length=20, choices=OS_FAMILIES, default="unknown")
    architecture = models.CharField(max_length=50, blank=True)
    connection_mode = models.CharField(max_length=20, choices=CONNECTION_MODES, default="ssh")
    ssh_username = models.CharField(max_length=150, blank=True)
    credential = models.ForeignKey(
        "DeploymentCredential", null=True, blank=True, related_name="targets", on_delete=models.PROTECT
    )
    host_key_fingerprint = models.CharField(max_length=255, blank=True)
    host_key_verified = models.BooleanField(default=False)
    deployment_base_path = models.CharField(max_length=500, default="/opt/mining360")
    application_path = models.CharField(max_length=500, blank=True)
    backup_path = models.CharField(max_length=500, blank=True)
    logs_path = models.CharField(max_length=500, blank=True)
    temporary_path = models.CharField(max_length=500, blank=True)
    domain_name = models.CharField(max_length=255, blank=True)
    application_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    is_approved = models.BooleanField(default=False)
    is_production = models.BooleanField(default=False)
    status = models.CharField(max_length=30, choices=STATUSES, default="Pending Approval")
    last_connection_test_at = models.DateTimeField(null=True, blank=True)
    last_successful_connection_at = models.DateTimeField(null=True, blank=True)
    last_health_check_at = models.DateTimeField(null=True, blank=True)
    last_connection_result = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, related_name="created_deployment_targets", on_delete=models.SET_NULL
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, related_name="updated_deployment_targets", on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["environment", "name"]
        permissions = [
            ("test_deployment_connection", "Can test deployment connections"),
            ("approve_deployment_target", "Can approve deployment targets"),
            ("manage_deployment_credentials", "Can manage deployment credentials"),
        ]

    @property
    def connection_host(self):
        return self.dns_name or self.hostname or self.ip_address or ""

    def __str__(self):
        return f"{self.name} ({self.environment})"


class DeploymentCredential(models.Model):
    TYPES = [
        ("ssh_private_key", "SSH Private Key"),
        ("ssh_password", "SSH Password"),
        ("agent_token", "Deployment Agent Token"),
        ("vault_reference", "Vault Secret Reference"),
    ]

    name = models.CharField(max_length=200, unique=True)
    credential_type = models.CharField(max_length=30, choices=TYPES)
    secret_reference = models.CharField(max_length=500, blank=True)
    encrypted_secret = models.TextField(blank=True)
    public_key = models.TextField(blank=True)
    key_identifier = models.CharField(max_length=255, blank=True)
    last_four_characters = models.CharField(max_length=4, blank=True)
    fingerprint = models.CharField(max_length=255, blank=True)
    username = models.CharField(max_length=150, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_rotated_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ApplicationRelease(models.Model):
    STATUSES = [("Draft", "Draft"), ("Validated", "Validated"), ("Deprecated", "Deprecated")]
    version = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    git_commit = models.CharField(max_length=64, blank=True)
    git_branch = models.CharField(max_length=150, blank=True)
    git_tag = models.CharField(max_length=150, blank=True)
    package_path = models.CharField(max_length=1000, blank=True)
    checksum = models.CharField(max_length=128, blank=True)
    release_notes = models.TextField(blank=True)
    database_migration_required = models.BooleanField(default=True)
    minimum_supported_version = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUSES, default="Draft")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.version


class DeploymentEnvironmentTemplate(models.Model):
    name = models.CharField(max_length=200, unique=True)
    environment = models.CharField(max_length=30, choices=DeploymentTarget.ENVIRONMENTS)
    deployment_strategy = models.CharField(max_length=40, default="native_django")
    configuration_json = models.JSONField(default=dict, blank=True)
    required_secret_keys = models.JSONField(default=list, blank=True)
    service_configuration = models.JSONField(default=dict, blank=True)
    health_check_configuration = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True)
    version = models.CharField(max_length=30, default="1.0")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class DeploymentPlan(models.Model):
    STATUSES = [
        ("Draft", "Draft"),
        ("Ready", "Ready"),
        ("Pending Approval", "Pending Approval"),
        ("Approved", "Approved"),
        ("Queued", "Queued"),
        ("Running", "Running"),
        ("Succeeded", "Succeeded"),
        ("Failed", "Failed"),
        ("Cancelled", "Cancelled"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    target = models.ForeignKey(DeploymentTarget, related_name="plans", on_delete=models.PROTECT)
    release = models.ForeignKey(ApplicationRelease, null=True, blank=True, related_name="plans", on_delete=models.PROTECT)
    environment_template = models.ForeignKey(
        DeploymentEnvironmentTemplate, null=True, blank=True, related_name="plans", on_delete=models.PROTECT
    )
    deployment_strategy = models.CharField(max_length=40, default="native_django")
    configuration_json = models.JSONField(default=dict, blank=True)
    manifest_json = models.JSONField(default=dict, blank=True)
    dry_run_result = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=30, choices=STATUSES, default="Draft", db_index=True)
    rollback_capability = models.CharField(max_length=50, default="Application Only")
    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, related_name="prepared_deployments", on_delete=models.SET_NULL
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, related_name="approved_deployments", on_delete=models.SET_NULL
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [
            ("approve_deployment", "Can approve deployments"),
            ("execute_deployment", "Can execute deployments"),
            ("cancel_deployment", "Can cancel deployments"),
            ("rollback_deployment", "Can roll back deployments"),
            ("view_deployment_configuration", "Can view deployment configuration"),
        ]

    def __str__(self):
        return self.name


class DeploymentStepDefinition(models.Model):
    code = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    required = models.BooleanField(default=True)
    can_retry = models.BooleanField(default=True)
    can_skip = models.BooleanField(default=False)
    requires_approval = models.BooleanField(default=False)
    timeout_seconds = models.PositiveIntegerField(default=300)
    rollback_step = models.CharField(max_length=80, blank=True)
    handler_code = models.CharField(max_length=100)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "code"]


class DeploymentJob(models.Model):
    STATUSES = [
        ("Queued", "Queued"), ("Running", "Running"), ("Waiting for Manual Action", "Waiting for Manual Action"),
        ("Succeeded", "Succeeded"), ("Failed", "Failed"), ("Rolling Back", "Rolling Back"),
        ("Rolled Back", "Rolled Back"), ("Cancelled", "Cancelled"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    deployment_plan = models.ForeignKey(DeploymentPlan, related_name="jobs", on_delete=models.CASCADE)
    status = models.CharField(max_length=40, choices=STATUSES, default="Queued", db_index=True)
    current_step = models.CharField(max_length=80, blank=True)
    progress_percentage = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancel_requested = models.BooleanField(default=False)
    failure_step = models.CharField(max_length=80, blank=True)
    failure_code = models.CharField(max_length=100, blank=True)
    failure_message = models.TextField(blank=True)
    worker_reference = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class DeploymentStepExecution(models.Model):
    job = models.ForeignKey(DeploymentJob, related_name="step_executions", on_delete=models.CASCADE)
    step = models.ForeignKey(DeploymentStepDefinition, on_delete=models.PROTECT)
    status = models.CharField(max_length=40, default="Pending")
    result_json = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    attempt = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["step__order", "attempt"]


class DeploymentLog(models.Model):
    LEVELS = [(value, value) for value in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")]
    job = models.ForeignKey(DeploymentJob, null=True, blank=True, related_name="logs", on_delete=models.CASCADE)
    plan = models.ForeignKey(DeploymentPlan, related_name="logs", on_delete=models.CASCADE)
    step_code = models.CharField(max_length=80, blank=True)
    level = models.CharField(max_length=10, choices=LEVELS, default="INFO")
    message = models.TextField()
    command_reference = models.CharField(max_length=100, blank=True)
    exit_code = models.IntegerField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]


class DeploymentHealthCheck(models.Model):
    target = models.ForeignKey(DeploymentTarget, related_name="health_checks", on_delete=models.CASCADE)
    job = models.ForeignKey(DeploymentJob, null=True, blank=True, related_name="health_checks", on_delete=models.CASCADE)
    check_code = models.CharField(max_length=100)
    display_name = models.CharField(max_length=200)
    category = models.CharField(max_length=80, default="Infrastructure")
    status = models.CharField(max_length=20, default="Pending")
    result_json = models.JSONField(default=dict, blank=True)
    checked_at = models.DateTimeField(auto_now_add=True)


class DeploymentLock(models.Model):
    target = models.OneToOneField(DeploymentTarget, related_name="deployment_lock", on_delete=models.CASCADE)
    job = models.ForeignKey(DeploymentJob, null=True, blank=True, on_delete=models.CASCADE)
    locked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    acquired_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)


class DeploymentAuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    target = models.ForeignKey(DeploymentTarget, null=True, blank=True, on_delete=models.SET_NULL)
    plan = models.ForeignKey(DeploymentPlan, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=100, db_index=True)
    details_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
