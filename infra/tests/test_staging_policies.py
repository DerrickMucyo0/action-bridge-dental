"""Offline checks of the unapplied IAM review drafts, not live authorization tests."""
import json
import unittest
from pathlib import Path


STAGING = Path(__file__).resolve().parents[1] / "staging"
STACK = "arn:aws:cloudformation:us-east-2:631367363628:stack/actionbridge-dental-staging/*"
CFN_ROLE = "arn:aws:iam::631367363628:role/actionbridge-dental-staging-cfn"
BOUNDARIES = ["arn:aws:iam::631367363628:policy/actionbridge-dental-staging-" + slug + "-boundary" for slug in ("health", "cases", "calculations", "jobs", "job-worker")]
BUCKET = "arn:aws:s3:::ab-dental-staging-artifacts-631367363628-us-east-2"
CHANGE_SETS = ["actionbridge-staging-initial-review", "actionbridge-staging-backend-review"]


def policy(name):
    return json.loads((STAGING / name).read_text())


def values(value):
    return value if isinstance(value, list) else [value]


def grants(document, action):
    return [statement for statement in document["Statement"]
            if statement["Effect"] == "Allow" and action in values(statement["Action"])]


class StagingPolicyDraftTests(unittest.TestCase):
    def setUp(self):
        self.preparer = policy("change-set-preparer-policy.json")
        self.preflight = policy("preflight-read-policy.json")

    def test_trust_is_only_cloudformation_service(self):
        trust = policy("cloudformation-trust.json")
        self.assertEqual(trust["Version"], "2012-10-17")
        self.assertEqual(len(trust["Statement"]), 1)
        statement = trust["Statement"][0]
        self.assertEqual(statement["Effect"], "Allow")
        self.assertEqual(statement["Principal"], {"Service": "cloudformation.amazonaws.com"})
        self.assertEqual(values(statement["Action"]), ["sts:AssumeRole"])
        self.assertNotIn("NotPrincipal", statement)

    def test_change_set_preparation_requires_exact_stack_role_region_and_name(self):
        statements = grants(self.preparer, "cloudformation:CreateChangeSet")
        self.assertEqual(len(statements), 1)
        stack = [statement for statement in statements if statement["Resource"] == STACK]
        self.assertEqual(len(stack), 1)
        self.assertEqual(stack[0]["Condition"]["StringEquals"], {
            "cloudformation:RoleArn": CFN_ROLE,
            "cloudformation:ChangeSetName": CHANGE_SETS,
            "aws:RequestedRegion": "us-east-2",
        })
        # The generated staging templates are plain CloudFormation; no macro grant is needed.
        self.assertFalse(any("transform/" in statement["Resource"] for statement in statements))
        # AWS provides no IAM ChangeSetType condition. CREATE-only still needs command review.
        self.assertNotIn("cloudformation:ChangeSetType", json.dumps(self.preparer))

    def test_review_uses_stack_arn_and_only_named_change_set(self):
        statements = grants(self.preparer, "cloudformation:DescribeChangeSet")
        self.assertEqual(len(statements), 1)
        self.assertEqual(statements[0]["Resource"], STACK)
        self.assertEqual(statements[0]["Condition"]["StringEquals"],
                         {"cloudformation:ChangeSetName": CHANGE_SETS})
        for action in ("cloudformation:GetTemplate", "cloudformation:ListChangeSets",
                       "cloudformation:DescribeStacks", "cloudformation:DescribeStackEvents",
                       "cloudformation:ListStackResources"):
            with self.subTest(action=action):
                self.assertTrue(grants(self.preparer, action))
                self.assertTrue(all(statement["Resource"] == STACK
                                    for statement in grants(self.preparer, action)))

    def test_pass_role_covers_one_role_and_cloudformation_only(self):
        statements = grants(self.preparer, "iam:PassRole")
        self.assertEqual(len(statements), 1)
        self.assertEqual(statements[0]["Resource"], CFN_ROLE)
        self.assertEqual(statements[0]["Condition"]["StringEquals"],
                         {"iam:PassedToService": "cloudformation.amazonaws.com"})

    def test_execution_direct_stack_changes_and_explicit_imports_are_denied(self):
        denied = set()
        for statement in self.preparer["Statement"]:
            if (statement["Effect"] == "Deny" and statement["Resource"] == "*"
                    and "Condition" not in statement):
                denied.update(values(statement["Action"]))
        self.assertTrue({
            "cloudformation:ExecuteChangeSet", "cloudformation:CreateStack",
            "cloudformation:UpdateStack", "cloudformation:DeleteStack",
            "cloudformation:ContinueUpdateRollback", "cloudformation:RollbackStack",
            "cloudformation:SetStackPolicy", "cloudformation:UpdateTerminationProtection",
        }.issubset(denied))
        imports = [statement for statement in self.preparer["Statement"]
                   if statement["Effect"] == "Deny"
                   and "cloudformation:CreateChangeSet" in values(statement["Action"])]
        self.assertEqual(len(imports), 1)
        self.assertEqual(imports[0]["Resource"], STACK)
        self.assertEqual(imports[0]["Condition"],
                         {"Null": {"cloudformation:ImportResourceTypes": "false"}})

    def test_artifact_access_is_account_and_prefix_scoped(self):
        location = grants(self.preparer, "s3:GetBucketLocation")
        self.assertEqual(len(location), 1)
        self.assertEqual(location[0]["Resource"], BUCKET)
        for action in ("s3:GetObject", "s3:PutObject"):
            statements = grants(self.preparer, action)
            self.assertEqual(len(statements), 1)
            self.assertEqual(statements[0]["Resource"], BUCKET + "/actionbridge-dental-staging/*")
        for statement in location + grants(self.preparer, "s3:GetObject") + grants(self.preparer, "s3:PutObject"):
            self.assertEqual(statement["Condition"]["StringEquals"],
                             {"s3:ResourceAccount": "631367363628"})

    def test_preflight_boundary_inspection_is_read_only_and_exact(self):
        for action in ("iam:GetPolicy", "iam:GetPolicyVersion"):
            statements = grants(self.preflight, action)
            self.assertEqual(len(statements), 1)
            self.assertEqual(statements[0]["Resource"], BOUNDARIES)
        for statement in self.preflight["Statement"]:
            self.assertEqual(statement["Effect"], "Allow")
            self.assertNotIn("*", values(statement["Resource"]))
            self.assertNotIn("NotAction", statement)
            self.assertNotIn("NotResource", statement)
            for action in values(statement["Action"]):
                self.assertRegex(action, r"^[a-z0-9-]+:(Get|Describe|List)[A-Za-z]+$")

    def test_preparer_has_no_direct_service_mutation_or_broad_iam_api_allow(self):
        allowed_actions = {
            "cloudformation:CreateChangeSet", "cloudformation:DescribeStacks",
            "cloudformation:DescribeStackEvents", "cloudformation:ListStackResources",
            "cloudformation:GetTemplate", "cloudformation:DescribeChangeSet",
            "cloudformation:ListChangeSets", "iam:PassRole", "s3:GetBucketLocation",
            "s3:GetObject", "s3:PutObject",
        }
        for statement in self.preparer["Statement"]:
            if statement["Effect"] != "Allow":
                continue
            self.assertNotIn("NotAction", statement)
            self.assertNotIn("NotResource", statement)
            self.assertNotIn("*", values(statement["Resource"]))
            self.assertTrue(set(values(statement["Action"])).issubset(allowed_actions))


if __name__ == "__main__":
    unittest.main()
