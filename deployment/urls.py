from django.urls import path

from deployment import views


urlpatterns = [
    path("health/", views.app_health, name="app-health"),
    path("api/health/", views.app_health, name="api-health"),
    path("config/deployment/", views.deployment_home, name="deployment-home"),
    path("api/deployment/dashboard/", views.dashboard_api, name="deployment-dashboard-api"),
    path("api/deployment/targets/", views.targets_api, name="deployment-targets-api"),
    path("api/deployment/targets/<int:target_id>/approve/", views.approve_target_api, name="deployment-target-approve-api"),
    path("api/deployment/targets/<int:target_id>/test-connection/", views.test_connection_api, name="deployment-target-test-api"),
    path("api/deployment/targets/<int:target_id>/precheck/", views.precheck_api, name="deployment-target-precheck-api"),
    path("api/deployment/targets/<int:target_id>/credential/", views.credential_api, name="deployment-target-credential-api"),
    path("api/deployment/targets/<int:target_id>/trust-host-key/", views.trust_host_key_api, name="deployment-target-host-key-api"),
    path("api/deployment/plans/", views.plans_api, name="deployment-plans-api"),
    path("api/deployment/plans/<uuid:plan_id>/dry-run/", views.dry_run_api, name="deployment-plan-dry-run-api"),
    path("api/deployment/releases/<int:release_id>/validate/", views.validate_release_api, name="deployment-release-validate-api"),
    path("api/deployment/quick-deploy/", views.quick_deploy_api, name="deployment-quick-deploy-api"),
    path("api/deployment/jobs/<uuid:job_id>/", views.deployment_job_api, name="deployment-job-api"),
]
