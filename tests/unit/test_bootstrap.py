"""Exercise bootstrap failure boundaries without Docker or real credentials."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "bootstrap.py"
spec = importlib.util.spec_from_file_location("bootstrap", SCRIPT)
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.config = {
            "services": {
                "auth": {"environment": {
                    "APP_ENV": "development", "EDGE_PUBLIC_URL": "https://localhost:8443",
                }},
                "seed": {"command": ["python", "scripts/create_admin.py", "--email", "owner@example.com"]},
            },
            "secrets": {},
        }
        for name in ("postgres_password", "edge_cert", "admin_password"):
            path = self.directory / name
            path.write_text("test-only")
            self.config["secrets"][name] = {"file": str(path)}

    def execute(self, *, reset_data=False, side_effect=None):
        with (
            patch.object(bootstrap.subprocess, "check_output", return_value=json.dumps(self.config)),
            patch.object(bootstrap, "run", side_effect=side_effect) as run,
        ):
            bootstrap.bootstrap(reset_data=reset_data)
            return [call.args for call in run.call_args_list]

    def test_reset_precedes_start_and_smoke_uses_configured_credentials(self):
        calls = self.execute(reset_data=True)
        self.assertEqual(calls[1], ("docker", "compose", "down", "--volumes"))
        self.assertEqual(calls[2][0:4], ("docker", "compose", "up", "--build"))
        self.assertIn("owner@example.com", calls[3])
        self.assertIn(str(self.directory / "admin_password"), calls[3])
        self.assertNotIn("--chatbot", calls[3])

    def test_normal_start_never_removes_volumes_or_regenerates_secrets(self):
        calls = self.execute()
        self.assertEqual(len(calls), 3)
        self.assertFalse(any("down" in call or "scripts/generate_secrets.py" in call for call in calls))

    def test_missing_secrets_abort_before_reset(self):
        (self.directory / "admin_password").unlink()
        with (
            patch.object(bootstrap.subprocess, "check_output", return_value=json.dumps(self.config)),
            patch.object(bootstrap, "run") as run,
        ):
            with self.assertRaises(ValueError):
                bootstrap.bootstrap(reset_data=True)
            run.assert_not_called()

    def test_production_is_rejected_before_reset(self):
        self.config["services"]["auth"]["environment"]["APP_ENV"] = "production"
        with self.assertRaises(ValueError):
            self.execute(reset_data=True)

    def test_failed_reset_never_starts_stack(self):
        calls = []

        def run(*command):
            calls.append(command)
            if "down" in command:
                raise subprocess.CalledProcessError(1, command)

        with self.assertRaises(subprocess.CalledProcessError):
            self.execute(reset_data=True, side_effect=run)
        self.assertEqual(len(calls), 2)

    def test_enabled_chatbot_is_smoke_tested(self):
        self.config["services"]["chatbot"] = {}
        self.assertIn("--chatbot", self.execute()[-1])

    def test_fresh_secrets_are_generated_before_reset(self):
        directory = self.directory / "new-secrets"
        for name in self.config["secrets"]:
            self.config["secrets"][name]["file"] = str(directory / name)
        calls = []

        def run(*command):
            calls.append(command)
            if "scripts/generate_secrets.py" in command:
                directory.mkdir()
                for name in self.config["secrets"]:
                    (directory / name).write_text("test-only")

        self.execute(reset_data=True, side_effect=run)
        self.assertIn("scripts/generate_secrets.py", calls[0])
        self.assertEqual(calls[2], ("docker", "compose", "down", "--volumes"))

    def test_failed_start_never_runs_smoke(self):
        calls = []

        def run(*command):
            calls.append(command)
            if "up" in command:
                raise subprocess.CalledProcessError(1, command)

        with self.assertRaises(subprocess.CalledProcessError):
            self.execute(side_effect=run)
        self.assertFalse(any("scripts/smoke_s2.py" in call for call in calls))


if __name__ == "__main__":
    unittest.main()
