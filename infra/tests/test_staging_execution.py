"""Offline regression checks of local execution-policy preparation."""
import ast
import importlib.util
import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest


HERE = Path(__file__).resolve().parents[1] / "staging"
SPEC = importlib.util.spec_from_file_location("staging_execution", HERE / "build-execution-policy.py")
EXECUTION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXECUTION)
API = "a1b2c3d4e5"


def actions(statement):
    value = statement.get("Action", [])
    return [value] if isinstance(value, str) else value


def resources(statement):
    value = statement.get("Resource", [])
    return [value] if isinstance(value, str) else value


def grants(document, action):
    return [statement for statement in document["Statement"] if statement["Effect"] == "Allow" and action in actions(statement)]


class StagingExecutionPolicyTests(unittest.TestCase):
    def test_bootstrap_is_current_and_creation_is_constrained(self):
        policy = EXECUTION.bootstrap_policy()
        self.assertEqual(json.loads(EXECUTION.BOOTSTRAP.read_text()), policy)
        create = grants(policy, "apigateway:POST")
        self.assertEqual(len(create), 1)
        self.assertEqual(create[0]["Resource"], "arn:aws:apigateway:us-east-2::/apis")
        self.assertEqual(create[0]["Condition"], {
            "StringEquals": {"aws:RequestedRegion": "us-east-2", "apigateway:Request/ApiName": "actionbridge-dental-staging"},
            "Bool": {"apigateway:Request/DisableExecuteApiEndpoint": "true"},
        })
        self.assertEqual({action for statement in policy["Statement"] if statement["Effect"] == "Allow" for action in actions(statement)},
                         {"apigateway:POST", "apigateway:GET"})
        denied = [statement for statement in policy["Statement"] if statement["Effect"] == "Deny"]
        self.assertTrue(any(statement.get("NotAction") == ["apigateway:GET", "apigateway:POST"]
                            and statement.get("Resource") == "*" for statement in denied))
        self.assertTrue(any(statement.get("NotResource") == create[0]["Resource"] for statement in denied))
        self.assertTrue(any(statement.get("Condition", {}).get("BoolIfExists", {}).get("apigateway:Request/DisableExecuteApiEndpoint") == "false" for statement in denied))
        self.assertEqual(EXECUTION.main(["--check"]), 0)

    def test_invalid_api_and_mapping_ids_fail_before_output(self):
        for bad in ("", "123", "A1b2c3d4e5", "a1b2c3d4e5/../apis", "*", "a1b2c3d4e5\n", "a1b2c3d4e55"):
            with self.subTest(api_id=bad), self.assertRaises(ValueError):
                EXECUTION.backend_policy(bad)
        with self.assertRaises(ValueError):
            EXECUTION.backend_policy(API, "*")

    def test_backend_api_mutation_covers_one_api_and_only_reviewed_children(self):
        policy = EXECUTION.backend_policy(API)
        expected = "arn:aws:apigateway:us-east-2::/apis/" + API
        for method in ("GET", "PATCH", "PUT", "POST", "DELETE"):
            allowed = grants(policy, "apigateway:" + method)
            self.assertEqual(len(allowed), 1)
            for arn in resources(allowed[0]):
                self.assertTrue(arn == expected or arn.startswith(expected + "/"))
                self.assertNotIn("/apis/*", arn)
                if "/stages/" in arn:
                    self.assertEqual(arn, expected + "/stages/staging")
        self.assertFalse(any(statement["Effect"] == "Allow" and statement.get("Resource") == "arn:aws:apigateway:us-east-2::/apis" for statement in policy["Statement"]))

    def test_all_five_role_creation_and_inline_policy_grants_require_paired_boundaries(self):
        policy = EXECUTION.backend_policy(API)
        cfg = EXECUTION.manifest()
        for action in ("iam:CreateRole", "iam:PutRolePolicy", "iam:UpdateAssumeRolePolicy"):
            allowed = grants(policy, action)
            self.assertEqual(len(allowed), 5)
            for statement, key in zip(allowed, EXECUTION.FUNCTIONS):
                spec = cfg["functions"][key]
                self.assertEqual(statement["Resource"], "arn:aws:iam::631367363628:role" + cfg["role_path"] + spec["role_name"])
                self.assertEqual(statement["Condition"]["ArnEquals"]["iam:PermissionsBoundary"],
                                 "arn:aws:iam::631367363628:policy/" + spec["boundary_policy_name"])

    def test_managed_policy_attachment_and_pass_role_are_limited(self):
        policy = EXECUTION.backend_policy(API)
        for action in ("iam:AttachRolePolicy", "iam:DetachRolePolicy"):
            # Existing roles retain their paired-boundary requirements. The
            # separate exact-name, missing-boundary cleanup grants are covered
            # by the lifecycle decision tests, not mistaken for path-role grants.
            allowed = [statement for statement in grants(policy, action)
                       if "iam:PermissionsBoundary" in statement.get("Condition", {}).get("ArnEquals", {})]
            self.assertEqual(len(allowed), 5)
            for index, statement in enumerate(allowed):
                self.assertEqual(statement["Condition"]["ArnEquals"]["iam:PolicyARN"],
                                 [EXECUTION.BASIC, EXECUTION.SQS] if index == 4 else EXECUTION.BASIC)
        passed = grants(policy, "iam:PassRole")
        self.assertEqual(len(passed), 1)
        self.assertEqual(len(resources(passed[0])), 5)
        self.assertEqual(passed[0]["Condition"], {"StringEquals": {"iam:PassedToService": "lambda.amazonaws.com"}})
        guardrails = EXECUTION.guardrail_policy(API)
        denied = [statement for statement in guardrails["Statement"]
                  if statement["Effect"] == "Deny" and "iam:PassRole" in actions(statement)]
        self.assertEqual(len(denied), 1)
        self.assertEqual(resources(denied[0]), resources(passed[0]))
        self.assertEqual(denied[0]["Condition"], {"StringNotEquals": {"iam:PassedToService": "lambda.amazonaws.com"}})

    def test_boundary_removal_policy_versions_and_self_mutation_are_denied(self):
        policy = EXECUTION.backend_policy(API)
        denied = {action for statement in policy["Statement"] if statement["Effect"] == "Deny" for action in actions(statement)}
        self.assertTrue({"iam:PutRolePermissionsBoundary", "iam:DeleteRolePermissionsBoundary", "iam:CreatePolicyVersion",
                         "iam:SetDefaultPolicyVersion", "iam:DeletePolicyVersion", "iam:DeletePolicy"}.issubset(denied))
        self.assertTrue(any(statement["Effect"] == "Deny" and statement.get("Action") == "iam:*"
                            and statement.get("Resource") == "arn:aws:iam::631367363628:role/actionbridge-dental-staging-cfn"
                            for statement in policy["Statement"]))

    def test_mapping_creation_and_mutation_are_bound_to_the_staging_worker(self):
        policy = EXECUTION.backend_policy(API)
        for action in ("lambda:CreateEventSourceMapping", "lambda:GetEventSourceMapping", "lambda:UpdateEventSourceMapping", "lambda:DeleteEventSourceMapping"):
            statement = grants(policy, action)[0]
            self.assertEqual(statement["Condition"]["ArnEquals"]["lambda:FunctionArn"],
                             "arn:aws:lambda:us-east-2:631367363628:function:actionbridge-dental-staging-job-worker")
            self.assertEqual(statement["Condition"]["StringEquals"]["aws:RequestedRegion"], "us-east-2")
        mapping = "00000000-0000-4000-8000-000000000001"
        # Cleanup may be authorized against Resource '*'; its supported exact
        # FunctionArn condition is mandatory. Update retains an ARN guardrail.
        for action in ("lambda:GetEventSourceMapping", "lambda:DeleteEventSourceMapping"):
            self.assertEqual(grants(policy, action)[0]["Resource"], "*")
        narrowed = [s for s in EXECUTION.guardrail_policy(API, mapping)["Statement"]
                    if s.get("Action") == ["lambda:UpdateEventSourceMapping"] and "NotResource" in s]
        self.assertEqual(narrowed[0]["NotResource"], "arn:aws:lambda:us-east-2:631367363628:event-source-mapping:" + mapping)

    def test_execution_role_has_no_business_data_model_or_cognito_actions(self):
        policy = EXECUTION.backend_policy(API)
        forbidden = {"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "dynamodb:UpdateItem",
                     "s3:PutObject", "s3:DeleteObject", "sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage",
                     "bedrock:InvokeModel", "polly:SynthesizeSpeech"}
        allowed = {action for statement in policy["Statement"] if statement["Effect"] == "Allow" for action in actions(statement)}
        self.assertFalse(allowed & forbidden)
        self.assertFalse(any(action.startswith(("cognito-idp:", "transcribe:", "textract:")) or "*" in action for action in allowed))
        artifact = grants(policy, "s3:GetObject")
        self.assertEqual(len(artifact), 1)
        self.assertEqual(artifact[0]["Resource"], "arn:aws:s3:::ab-dental-staging-artifacts-631367363628-us-east-2/actionbridge-dental-staging/*")

    def test_backend_output_is_exclusive_and_cli_cannot_apply_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "review"
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(EXECUTION.main(["--api-id", API, "--output-dir", str(path)]), 0)
                original = {item.name: item.read_bytes() for item in path.iterdir()}
                self.assertEqual(EXECUTION.main(["--api-id", API, "--output-dir", str(path)]), 1)
                self.assertEqual({item.name: item.read_bytes() for item in path.iterdir()}, original)
        tree = ast.parse((HERE / "build-execution-policy.py").read_text())
        modules = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        modules |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertEqual(modules, {"argparse", "json", "pathlib", "re", "sys"})

    def test_backend_bundle_parts_fit_managed_policy_quota_and_preserve_all_statements(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "new-bundle"
            review = EXECUTION.write_backend_bundle(API, path)
            self.assertFalse(review["ownership_verified"])
            self.assertFalse(review["execution_permissions_boundary"])
            self.assertLessEqual(len(review["compact_sizes"]), 10)
            for label, expected in (("identity", EXECUTION.backend_policy(API)), ("guardrail", EXECUTION.guardrail_policy(API))):
                actual = []
                for name in review[label + "_policies"]:
                    part = json.loads((path / name).read_text())
                    self.assertLessEqual(EXECUTION.compact_size(part), 6144)
                    actual += part["Statement"]
                self.assertEqual(actual, expected["Statement"])

    def test_guardrails_explicitly_deny_changes_outside_reviewed_resource_sets(self):
        guardrails = EXECUTION.guardrail_policy(API)
        self.assertTrue(all(statement["Effect"] == "Deny" for statement in guardrails["Statement"]))
        for action in ("lambda:CreateFunction", "dynamodb:CreateTable", "sqs:CreateQueue", "logs:CreateLogGroup", "apigateway:POST"):
            statements = [statement for statement in guardrails["Statement"] if action in actions(statement) and "NotResource" in statement]
            self.assertTrue(statements, action)
        wrong_boundaries = [statement for statement in guardrails["Statement"] if "iam:CreateRole" in actions(statement)]
        self.assertEqual(len(wrong_boundaries), 5)
        for statement in wrong_boundaries:
            self.assertIn("iam:PermissionsBoundary", statement["Condition"]["ArnNotEquals"])

    def test_output_rejects_symlink_in_final_directory_or_any_ancestor(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            actual = base / "actual"
            actual.mkdir()
            linked = base / "linked"
            linked.symlink_to(actual, target_is_directory=True)
            for output in (linked, linked / "new-bundle", linked / ".." / "hidden-redirect"):
                with self.subTest(output=str(output)), self.assertRaisesRegex(ValueError, "symlink"):
                    EXECUTION.write_backend_bundle(API, output)
            self.assertEqual(list(actual.iterdir()), [])
            self.assertFalse((base / "hidden-redirect").exists())

    def test_lambda_permission_mutation_has_supported_principal_condition(self):
        # The Lambda authorization reference lists lambda:Principal for both
        # AddPermission and RemovePermission. Restrict both on exact handlers.
        policy = EXECUTION.backend_policy(API)
        for action in ("lambda:AddPermission", "lambda:RemovePermission"):
            statement = grants(policy, action)[0]
            self.assertEqual(len(resources(statement)), 4)
            self.assertEqual(statement["Condition"]["StringEquals"]["lambda:Principal"], "apigateway.amazonaws.com")


if __name__ == "__main__":
    unittest.main()
