import json

from django.core.management.base import BaseCommand, CommandError

from deployment.models import DeploymentTarget
from deployment.services.system_doctor import DeploymentSystemDoctorService


class Command(BaseCommand):
    help = "Diagnose Mining360 readiness and optionally apply allowlisted safe repairs."

    def add_arguments(self, parser):
        parser.add_argument("--target", help="Deployment target ID or exact name.")
        parser.add_argument("--repair", action="store_true", help="Apply allowlisted reversible repairs.")
        parser.add_argument("--json", action="store_true", help="Return machine-readable JSON.")

    def handle(self, *args, **options):
        target = None
        if options["target"]:
            query = str(options["target"])
            target = DeploymentTarget.objects.filter(pk=query).first() if query.isdigit() else None
            target = target or DeploymentTarget.objects.filter(name=query).first()
            if target is None:
                raise CommandError(f"Deployment target not found: {query}")
        result = DeploymentSystemDoctorService().run(target, repair=options["repair"])
        if options["json"]:
            self.stdout.write(json.dumps(result, indent=2, default=str))
            return
        self.stdout.write(self.style.SUCCESS(f"Mining360 System Doctor: {result['status']}"))
        for item in result["checks"]:
            self.stdout.write(f"[{item['status']}] {item['name']}: {item['value']}")
            if item.get("recommendation"):
                self.stdout.write(f"  Action: {item['recommendation']}")
