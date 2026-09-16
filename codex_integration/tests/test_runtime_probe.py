from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from codex_integration.contracts import AnswerStatus, RunStatus
from codex_integration.runtime_probe import CodexRuntimeProbe


class RuntimeProbeTests(TestCase):
    missing_config_root = Path("codex_integration/tests/fixtures/no_codex_config")

    def test_contract_values_are_stable(self):
        self.assertEqual(AnswerStatus.ANSWERABLE, "ANSWERABLE")
        self.assertEqual(RunStatus.WAITING_FOR_APPROVAL, "WAITING_FOR_APPROVAL")
        self.assertEqual(RunStatus.RECOVERY_REQUIRED, "RECOVERY_REQUIRED")

    def test_probe_reports_missing_sdk_and_runtime_configuration(self):
        with (
            patch.object(CodexRuntimeProbe, "_distribution_version", return_value=None),
            patch("codex_integration.runtime_probe.shutil.which", return_value=None),
        ):
            result = CodexRuntimeProbe(project_root=self.missing_config_root).run()

        self.assertFalse(result.ready_for_sdk_prototype)
        self.assertIn("The openai-codex Python SDK is not installed or pinned.", result.blockers)
        self.assertIn("Dedicated Chatbot/Admin CODEX_HOME configuration is not created.", result.blockers)

    def test_probe_never_starts_the_cli_when_it_is_absent(self):
        with (
            patch.object(CodexRuntimeProbe, "_distribution_version", return_value="1.2.3"),
            patch("codex_integration.runtime_probe.shutil.which", return_value=None),
            patch("codex_integration.runtime_probe.subprocess.run") as process,
        ):
            CodexRuntimeProbe(project_root=self.missing_config_root).run()

        process.assert_not_called()
