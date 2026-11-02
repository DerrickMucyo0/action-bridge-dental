"""Offline scope checks for the 32-check grant; not an AWS policy simulation."""
from fnmatch import fnmatchcase
import importlib.util
import json
from pathlib import Path
import unittest


STAGING = Path(__file__).resolve().parents[1] / "staging"
SPEC = importlib.util.spec_from_file_location("collision_plan_for_policy", STAGING / "collision-checks.py")
CHECKS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKS)
ACCOUNT = "631367363628"
REGION = "us-east-2"
PRINCIPAL = f"arn:aws:iam::{ACCOUNT}:user/actionbridge-developer"


def values(value):
    return value if isinstance(value, list) else [value]


def resource_grants(policy, action, resource):
    """Inspect action/resource patterns only; AWS conditions are asserted separately."""
    return [item for item in policy["Statement"] if action in values(item["Action"])
            and any(fnmatchcase(resource, pattern) for pattern in values(item["Resource"]))]


class CollisionReadPolicyTests(unittest.TestCase):
    def setUp(self):
        self.manifest = CHECKS.load_manifest()
        self.policy = json.loads((STAGING / "collision-read-policy.json").read_text())

    def test_only_eleven_required_read_actions_and_no_existing_rights_are_denied(self):
        expected = {
            "ec2:DescribeRegions", "cloudformation:DescribeStacks", "lambda:GetFunctionConfiguration",
            "logs:DescribeLogGroups", "dynamodb:DescribeTable", "sqs:GetQueueUrl", "s3:ListBucket",
            "iam:ListRoles", "iam:GetRole", "iam:GetPolicy", "apigateway:GET",
        }
        self.assertEqual(self.policy["Version"], "2012-10-17")
        self.assertEqual({action for item in self.policy["Statement"] for action in values(item["Action"])}, expected)
        for item in self.policy["Statement"]:
            self.assertEqual(item["Effect"], "Allow")
            self.assertNotIn("NotAction", item)
            self.assertNotIn("NotResource", item)
        # STS GetCallerIdentity needs no IAM grant; the two API versions share GET.
        self.assertFalse(resource_grants(self.policy, "sts:GetCallerIdentity", "*"))
        self.assertLessEqual(len(json.dumps(self.policy, separators=(",", ":"))), 6144)

    def test_every_allow_is_bound_to_the_existing_developer_identity(self):
        for item in self.policy["Statement"]:
            self.assertEqual(item["Condition"]["ArnEquals"], {"aws:PrincipalArn": PRINCIPAL})

    def test_regional_requests_are_ohio_and_only_global_or_s3_exceptions_omit_region(self):
        regional = {"ec2:", "cloudformation:", "lambda:", "logs:", "dynamodb:", "sqs:", "apigateway:"}
        for item in self.policy["Statement"]:
            prefixes = {action.split(":", 1)[0] + ":" for action in values(item["Action"])}
            if prefixes & regional:
                self.assertEqual(item["Condition"]["StringEquals"], {"aws:RequestedRegion": REGION})
            else:
                self.assertTrue(prefixes <= {"iam:", "s3:"})
                self.assertNotIn("StringEquals", item["Condition"])

    def test_only_unscopable_metadata_actions_have_whole_resource_wildcards(self):
        actual = {action for item in self.policy["Statement"] if item["Resource"] == "*"
                  for action in values(item["Action"])}
        self.assertEqual(actual, {"ec2:DescribeRegions", "logs:DescribeLogGroups", "iam:ListRoles"})

    def test_all_32_planned_operations_are_covered_without_extra_actions(self):
        commands = CHECKS.command_plan(self.manifest, "actionbridge-developer")
        self.assertEqual(len(commands), 32)
        for entry in commands:
            command = entry["command"]
            operation = tuple(command[8:10])
            def argument(name):
                return command[command.index(name) + 1]
            if operation == ("sts", "get-caller-identity"):
                continue  # Public AWS API reference explicitly says no permission is required.
            if operation == ("ec2", "describe-regions"):
                action, resource = "ec2:DescribeRegions", "*"
            elif operation == ("cloudformation", "describe-stacks"):
                action, resource = "cloudformation:DescribeStacks", f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{argument('--stack-name')}/example"
            elif operation == ("lambda", "get-function-configuration"):
                action, resource = "lambda:GetFunctionConfiguration", f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{argument('--function-name')}"
            elif operation == ("logs", "describe-log-groups"):
                action, resource = "logs:DescribeLogGroups", "*"
            elif operation == ("dynamodb", "describe-table"):
                action, resource = "dynamodb:DescribeTable", f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{argument('--table-name')}"
            elif operation == ("sqs", "get-queue-url"):
                action, resource = "sqs:GetQueueUrl", f"arn:aws:sqs:{REGION}:{ACCOUNT}:{argument('--queue-name')}"
            elif operation == ("s3api", "head-bucket"):
                action, resource = "s3:ListBucket", f"arn:aws:s3:::{argument('--bucket')}"
            elif operation == ("iam", "list-roles"):
                action, resource = "iam:ListRoles", "*"
            elif operation == ("iam", "get-role"):
                action, resource = "iam:GetRole", f"arn:aws:iam::{ACCOUNT}:role/arbitrary/nested/path/{argument('--role-name')}"
            elif operation == ("iam", "get-policy"):
                action, resource = "iam:GetPolicy", argument("--policy-arn")
            elif operation in (("apigatewayv2", "get-apis"), ("apigateway", "get-rest-apis")):
                action = "apigateway:GET"
                resource = f"arn:aws:apigateway:{REGION}::/" + ("apis" if operation[0] == "apigatewayv2" else "restapis")
            else:
                self.fail("An unreviewed operation was added to the plan: " + repr(operation))
            with self.subTest(label=entry["label"]):
                self.assertTrue(resource_grants(self.policy, action, resource))

    def test_six_exact_role_names_work_at_root_and_nested_paths_but_no_other_roles(self):
        names = [item["role_name"] for item in self.manifest["functions"].values()] + [self.manifest["execution_role_name"]]
        for name in names:
            for path in ("", "other/", "deep/nested/"):
                self.assertTrue(resource_grants(self.policy, "iam:GetRole", f"arn:aws:iam::{ACCOUNT}:role/{path}{name}"))
        for name in ("production-admin", "actionbridge-dental-staging-unreviewed-role", names[0] + "-extra"):
            self.assertFalse(resource_grants(self.policy, "iam:GetRole", f"arn:aws:iam::{ACCOUNT}:role/{name}"))
        self.assertFalse(resource_grants(self.policy, "iam:GetRole", f"arn:aws:iam::195469705669:role/{names[0]}"))

    def test_exact_resources_exclude_other_functions_tables_queues_and_stacks(self):
        attempts = [
            ("lambda:GetFunctionConfiguration", f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:production"),
            ("lambda:GetFunctionConfiguration", f"arn:aws:lambda:us-east-1:{ACCOUNT}:function:actionbridge-dental-staging-health"),
            ("dynamodb:DescribeTable", f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/production"),
            ("sqs:GetQueueUrl", f"arn:aws:sqs:{REGION}:{ACCOUNT}:production"),
            ("cloudformation:DescribeStacks", f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/production/example"),
        ]
        for action, resource in attempts:
            self.assertFalse(resource_grants(self.policy, action, resource))

    def test_bucket_reads_are_exact_and_do_not_require_owner_context_or_grant_objects(self):
        items = [item for item in self.policy["Statement"] if "s3:ListBucket" in values(item["Action"])]
        self.assertEqual(len(items), 1)
        self.assertEqual(set(values(items[0]["Resource"])), {"arn:aws:s3:::" + name for name in self.manifest["buckets"].values()})
        self.assertNotIn("s3:ResourceAccount", json.dumps(items[0]))
        self.assertFalse(resource_grants(self.policy, "s3:GetObject", "arn:aws:s3:::example/private"))
        self.assertFalse(resource_grants(self.policy, "s3:ListBucket", "arn:aws:s3:::production"))

    def test_api_grant_is_collection_metadata_only_and_boundary_policy_reads_are_exact(self):
        expected_api = {f"arn:aws:apigateway:{REGION}::/apis", f"arn:aws:apigateway:{REGION}::/restapis"}
        items = [item for item in self.policy["Statement"] if "apigateway:GET" in values(item["Action"])]
        self.assertEqual(set(values(items[0]["Resource"])), expected_api)
        self.assertFalse(resource_grants(self.policy, "apigateway:GET", f"arn:aws:apigateway:{REGION}::/apis/exampleapi"))
        expected_policies = {f"arn:aws:iam::{ACCOUNT}:policy/{item['boundary_policy_name']}" for item in self.manifest["functions"].values()}
        items = [item for item in self.policy["Statement"] if "iam:GetPolicy" in values(item["Action"])]
        self.assertEqual(set(values(items[0]["Resource"])), expected_policies)
        self.assertFalse(resource_grants(self.policy, "iam:GetPolicyVersion", next(iter(expected_policies))))


if __name__ == "__main__":
    unittest.main()
