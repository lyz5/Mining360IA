from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceDefinition:
    code: str
    name: str
    category: str
    criticality: str
    required: bool
    cadence: str
    stale_after_seconds: int
    dependencies: tuple[str, ...] = ()
    port: int | None = None


class ServiceRegistry:
    """Environment-aware inventory used by health and UI layers."""

    def __init__(self, environment: str | None = None) -> None:
        self.environment = (environment or os.getenv("MINING360_CONTROL_ENVIRONMENT") or "Development").strip()

    def services(self) -> tuple[ServiceDefinition, ...]:
        development = self.environment.casefold() in {"local", "development", "dev"}
        upstream_port = 8001 if development else 8000
        return (
            ServiceDefinition("process", "Mining 360 Runtime", "Runtime", "critical", True, "fast", 12, port=upstream_port),
            ServiceDefinition("django", "Django / Waitress", "Runtime", "critical", True, "medium", 35, ("process",), upstream_port),
            ServiceDefinition("https", "HTTPS Gateway", "Runtime", "critical", True, "medium", 35, ("django",), 443),
            ServiceDefinition("database", "Application Database", "Runtime", "critical", True, "medium", 35, ("django",)),
            ServiceDefinition("codex_worker", "Codex Worker", "AI & Workers", "important", True, "medium", 35, ("database",)),
            ServiceDefinition("active_directory", "Active Directory", "Identity & Security", "external", False, "slow", 180),
            ServiceDefinition("powerbi", "Power BI API", "Data & Integrations", "external", False, "slow", 180),
            ServiceDefinition("database_migrations", "Database Migrations", "Runtime", "important", False, "slow", 180, ("database",)),
            ServiceDefinition("static_assets", "Static Assets", "Runtime", "important", False, "slow", 180),
            ServiceDefinition("mapping_sync", "Business Mapping Sync", "Data & Integrations", "data", False, "slow", 180, ("database",)),
            ServiceDefinition("mapping_publication", "Published Mapping", "Data & Integrations", "data", False, "slow", 180, ("mapping_sync",)),
            ServiceDefinition("revenue_snapshot", "Revenue Snapshot", "Data & Integrations", "data", False, "slow", 180, ("mapping_sync",)),
            ServiceDefinition("fleet_snapshot", "Fleet Snapshot", "Data & Integrations", "data", False, "slow", 180, ("mapping_sync",)),
            ServiceDefinition("invoice_sync", "Invoice Tracking Sync", "Data & Integrations", "data", False, "slow", 180, ("database",)),
            ServiceDefinition("machine_sales", "Machine Sales Detail", "Data & Integrations", "data", False, "slow", 180, ("database",)),
            ServiceDefinition("parts_sales", "Parts Sales Detail", "Data & Integrations", "data", False, "slow", 180, ("database",)),
        )

    def by_code(self) -> dict[str, ServiceDefinition]:
        return {item.code: item for item in self.services()}

    @property
    def lifecycle_supported(self) -> bool:
        return self.environment.casefold() in {"local", "development", "dev"}
