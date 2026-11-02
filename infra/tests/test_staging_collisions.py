"""Offline name-plan safety tests. No private parameters, credentials or AWS calls."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/staging/collision-checks.py"
SPEC = importlib.util.spec_from_file_location("staging_collision_checks", SCRIPT)
CHECKS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKS)


class StagingCollisionPlanTests(unittest.TestCase):
    def test_manifest_is_exactly_targeted_and_names_meet_service_limits(self):
        resources = CHECKS.load_manifest()
        self.assertEqual(resources["account"], "631367363628")
        self.assertEqual(resources["region"], "us-east-2")
        self.assertEqual(resources["stack_name"], "actionbridge-dental-staging")
        self.assertEqual(len(resources["functions"]), 5)
        for item in resources["functions"].values():
            self.assertLessEqual(len(item["name"]), 64)
            self.assertLessEqual(len(item["role_name"]), 64)
            self.assertLessEqual(len(item["boundary_policy_name"]), 128)
        for bucket in resources["buckets"].values():
            self.assertLessEqual(len(bucket), 63)
            self.assertRegex(bucket, r"^[a-z0-9][a-z0-9-]+[a-z0-9]$")
        for queue in resources["queues"].values():
            self.assertLessEqual(len(queue), 80)
        self.assertNotEqual(resources["buckets"]["uploads"], resources["buckets"]["artifacts"])
        self.assertNotEqual(resources["queues"]["work"], resources["queues"]["dead_letter"])

    def test_manifest_rejects_other_accounts_regions_and_role_paths(self):
        resources = CHECKS.load_manifest()
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "resources.json"
            for key, value in (("account", "195469705669"), ("region", "us-east-1"),
                               ("stack_name", "actionbridge-dental-dev"), ("role_path", "/")):
                changed = copy.deepcopy(resources)
                changed[key] = value
                manifest.write_text(json.dumps(changed))
                with self.subTest(key=key), self.assertRaises(ValueError):
                    CHECKS.load_manifest(manifest)

    def test_plan_is_scoped_read_only_and_excludes_sensitive_response_fields(self):
        resources = CHECKS.load_manifest()
        permitted = {
            ("sts", "get-caller-identity"), ("ec2", "describe-regions"),
            ("cloudformation", "describe-stacks"), ("lambda", "get-function-configuration"),
            ("logs", "describe-log-groups"), ("dynamodb", "describe-table"),
            ("sqs", "get-queue-url"), ("s3api", "head-bucket"), ("iam", "list-roles"),
            ("iam", "get-role"), ("iam", "get-policy"), ("apigatewayv2", "get-apis"),
            ("apigateway", "get-rest-apis"),
        }
        commands = CHECKS.command_plan(resources, "authorized-admin")
        for check in commands:
            command = check["command"]
            with self.subTest(label=check["label"]):
                self.assertEqual(command[:8], ["aws", "--profile", "authorized-admin", "--region",
                                               "us-east-2", "--no-cli-pager", "--output", "json"])
                self.assertIn(tuple(command[8:10]), permitted)
                self.assertIn("--query", command)
                query = command[command.index("--query") + 1]
                for sensitive in ("Environment", "Secret", "Token", "Users", "Attributes"):
                    self.assertNotIn(sensitive, query)
        self.assertEqual(sum(check["command"][8:10] == ["lambda", "get-function-configuration"] for check in commands), 5)
        self.assertEqual(sum(check["command"][8:10] == ["logs", "describe-log-groups"] for check in commands), 5)
        self.assertEqual(sum(check["command"][8:10] == ["iam", "get-role"] for check in commands), 6)
        for check in commands:
            command = check["command"]
            if command[8:10] == ["s3api", "head-bucket"]:
                self.assertEqual(command[command.index("--expected-bucket-owner") + 1], resources["account"])

    def test_cli_prints_only_and_rejects_an_execute_option(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sentinel = root / "aws-was-executed"
            fake_aws = root / "aws"
            fake_aws.write_text("#!/bin/sh\nprintf invoked > '" + str(sentinel) + "'\nexit 1\n")
            fake_aws.chmod(0o700)
            for extra, expected_code in (([], 0), (["--execute"], 2)):
                result = subprocess.run([sys.executable, str(SCRIPT), "--profile", "authorized-admin", *extra],
                                        env={"PATH": str(root)}, capture_output=True, text=True)
                self.assertEqual(result.returncode, expected_code, result.stderr)
                self.assertFalse(sentinel.exists())
                if not extra:
                    self.assertIn("OFFLINE PLAN ONLY", result.stdout)
                    self.assertIn("UNKNOWN, never FREE", result.stdout)
                    self.assertIn("153-resource inventory is incomplete", result.stdout)
                    self.assertIn("No collision finding is established", result.stdout)

    def test_script_has_no_execution_network_or_credential_modules(self):
        source = ast.parse(SCRIPT.read_text())
        imported = set()
        called = set()
        for node in ast.walk(source):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                called.add(node.func.id)
        self.assertFalse(imported & {"boto3", "botocore", "subprocess", "socket", "os", "urllib", "http"})
        self.assertFalse(called & {"exec", "eval", "__import__"})

    def test_queries_do_not_read_private_parameters_or_test_users(self):
        rendered = json.dumps(CHECKS.command_plan(CHECKS.load_manifest(), "authorized-admin"))
        self.assertNotIn("parameters.json", rendered)
        self.assertNotIn("cognito-idp", rendered)
        self.assertNotIn("list-users", rendered)


if __name__ == "__main__":
    unittest.main()
