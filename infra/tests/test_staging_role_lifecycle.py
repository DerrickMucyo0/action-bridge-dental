"""Evaluate the bounded IAM request contexts seen during staging role lifecycle.

This deliberately small evaluator covers only operators emitted by the policy
generator. It is not an AWS IAM simulator: unknown operators fail the test rather
than silently making a statement match. Contexts omit permissions-boundary keys
for missing-role lookups/cleanup, reproducing the provider's failed requests.
"""
from fnmatch import fnmatchcase
import importlib.util
from pathlib import Path
import unittest


HERE = Path(__file__).resolve().parents[1] / "staging"
SPEC = importlib.util.spec_from_file_location("staging_role_lifecycle_execution", HERE / "build-execution-policy.py")
EXECUTION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXECUTION)

API = "a1b2c3d4e5"
ACCOUNT = "631367363628"
ROLE_PREFIX = f"arn:aws:iam::{ACCOUNT}:role/"
PATH_PREFIX = ROLE_PREFIX + "actionbridge/staging/actionbridge-dental-staging/"
SLUGS = ("health", "cases", "calculations", "jobs", "job-worker")
NAMES = tuple("actionbridge-dental-staging-" + slug + "-role" for slug in SLUGS)
ROLES = tuple(PATH_PREFIX + name for name in NAMES)
ALIASES = tuple(ROLE_PREFIX + name for name in NAMES)
BOUNDARIES = tuple(f"arn:aws:iam::{ACCOUNT}:policy/actionbridge-dental-staging-{slug}-boundary" for slug in SLUGS)
BASIC = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
SQS = "arn:aws:iam::aws:policy/service-role/AWSLambdaSQSQueueExecutionRole"
OPERATORS = {"ArnEquals", "ArnNotEquals", "StringEquals", "StringNotEquals", "Null"}


def values(value):
    return value if isinstance(value, list) else [value]


def arn_matches(actual, pattern):
    actual_parts, pattern_parts = actual.split(":", 5), pattern.split(":", 5)
    return (len(actual_parts) == len(pattern_parts) == 6
            and all(fnmatchcase(part, wanted) for part, wanted in zip(actual_parts, pattern_parts)))


def conditions_match(conditions, context):
    context = {key.lower(): value for key, value in context.items()}
    for operator, clauses in conditions.items():
        if operator not in OPERATORS:
            raise ValueError("Unsupported IAM test operator: " + operator)
        for key, expected in clauses.items():
            actual = context.get(key.lower())
            present = actual is not None and actual != "" and actual != []
            if operator == "Null":
                if str(expected).lower() not in ("true", "false"):
                    raise ValueError("Null requires true or false.")
                matches = (not present) == (str(expected).lower() == "true")
            else:
                compare = arn_matches if operator.startswith("Arn") else lambda left, right: left == right
                matches = present and any(compare(left, right)
                                          for left in values(actual) for right in values(expected))
                if operator in ("ArnNotEquals", "StringNotEquals"):
                    matches = not matches
            if not matches:
                return False
    return True


def decision(documents, action, resource, context=None):
    """Return effective Allow/implicit Deny/explicit Deny for the tested subset."""
    statements = [statement for document in documents for statement in document["Statement"]]
    # Validate every operator, including statements not reached by this request.
    for statement in statements:
        unknown = set(statement.get("Condition", {})) - OPERATORS
        if unknown:
            raise ValueError("Unsupported IAM test operator: " + sorted(unknown)[0])
        if ("Action" in statement) == ("NotAction" in statement):
            raise ValueError("Exactly one of Action and NotAction is required.")
        if ("Resource" in statement) == ("NotResource" in statement):
            raise ValueError("Exactly one of Resource and NotResource is required.")
    allowed = False
    for statement in statements:
        action_key = "Action" if "Action" in statement else "NotAction"
        action_matches = any(fnmatchcase(action.lower(), pattern.lower()) for pattern in values(statement[action_key]))
        if action_matches == (action_key == "NotAction"):
            continue
        resource_key = "Resource" if "Resource" in statement else "NotResource"
        resource_matches = any(fnmatchcase(resource, pattern) for pattern in values(statement[resource_key]))
        if resource_matches == (resource_key == "NotResource"):
            continue
        if not conditions_match(statement.get("Condition", {}), context or {}):
            continue
        if statement["Effect"] == "Deny":
            return "explicitDeny"
        if statement["Effect"] != "Allow":
            raise ValueError("Unsupported policy effect.")
        allowed = True
    return "allowed" if allowed else "implicitDeny"


class StagingRoleLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.identity = EXECUTION.backend_policy(API)
        cls.guardrails = EXECUTION.guardrail_policy(API)
        cls.documents = [cls.identity, cls.guardrails]
        cls.broad_allow = {"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": "*", "Resource": "*"},
        ]}

    def assert_decision(self, expected, action, resource, context=None, extra_allow=False):
        documents = self.documents + ([self.broad_allow] if extra_allow else [])
        self.assertEqual(decision(documents, action, resource, context), expected,
                         (action, resource, context))

    def test_original_not_resource_deny_reproduces_both_observed_failures(self):
        original_guard = {"Version": "2012-10-17", "Statement": [
            {"Effect": "Deny", "Action": "iam:*", "NotResource": list(ROLES)},
        ]}
        for action in ("iam:GetRole", "iam:DetachRolePolicy"):
            with self.subTest(action=action):
                # Even a supplemental unconditional Allow cannot fix this Deny.
                self.assertEqual(decision([original_guard, self.broad_allow], action, ALIASES[0],
                                          {"iam:PolicyARN": BASIC}), "explicitDeny")

    def test_exact_root_alias_lookups_work_before_creation_and_during_rollback(self):
        for alias in ALIASES:
            for context in ({}, {"iam:PermissionsBoundary": BOUNDARIES[0]}):
                with self.subTest(alias=alias, context=context):
                    self.assert_decision("allowed", "iam:GetRole", alias, context)

    def test_missing_role_detach_is_limited_to_exact_per_role_managed_policies(self):
        for index, alias in enumerate(ALIASES):
            approved = (BASIC, SQS) if index == 4 else (BASIC,)
            for policy in approved:
                with self.subTest(alias=alias, policy=policy):
                    self.assert_decision("allowed", "iam:DetachRolePolicy", alias, {"iam:PolicyARN": policy})
            wrong = ("arn:aws:iam::aws:policy/AdministratorAccess", BOUNDARIES[index])
            if index != 4:
                wrong += (SQS,)
            for policy in wrong:
                with self.subTest(alias=alias, wrong_policy=policy):
                    self.assert_decision("explicitDeny", "iam:DetachRolePolicy", alias,
                                         {"iam:PolicyARN": policy}, extra_allow=True)
            self.assert_decision("explicitDeny", "iam:DetachRolePolicy", alias, {}, extra_allow=True)

    def test_existing_bounded_root_alias_cannot_be_detached(self):
        for index, alias in enumerate(ALIASES):
            for boundary in (BOUNDARIES[index], "arn:aws:iam::631367363628:policy/unrelated-boundary"):
                with self.subTest(alias=alias, boundary=boundary):
                    self.assert_decision("explicitDeny", "iam:DetachRolePolicy", alias,
                                         {"iam:PolicyARN": BASIC, "iam:PermissionsBoundary": boundary},
                                         extra_allow=True)

    def test_existing_unbounded_reserved_alias_is_the_documented_cleanup_tradeoff(self):
        # IAM does not expose resource existence through Null. An existing role
        # without a boundary shares the absent-boundary context of NoSuchEntity.
        # The exception is therefore not a proof that the target does not exist.
        for alias in ALIASES:
            self.assert_decision("allowed", "iam:DetachRolePolicy", alias, {"iam:PolicyARN": BASIC})

    def test_root_aliases_are_explicitly_denied_every_other_iam_mutation(self):
        mutations = ("CreateRole", "DeleteRole", "PutRolePolicy", "DeleteRolePolicy", "AttachRolePolicy",
                     "UpdateAssumeRolePolicy", "UpdateRole", "UpdateRoleDescription", "TagRole", "UntagRole",
                     "PassRole", "PutRolePermissionsBoundary", "DeleteRolePermissionsBoundary")
        for alias in ALIASES:
            for operation in mutations:
                with self.subTest(alias=alias, operation=operation):
                    self.assert_decision("explicitDeny", "iam:" + operation, alias,
                                         {"iam:PermissionsBoundary": BOUNDARIES[0], "iam:PolicyARN": BASIC,
                                          "iam:PassedToService": "lambda.amazonaws.com"}, extra_allow=True)

    def test_path_role_creation_and_policy_mutation_still_require_the_paired_boundary(self):
        for index, role in enumerate(ROLES):
            for action in ("iam:CreateRole", "iam:PutRolePolicy", "iam:UpdateAssumeRolePolicy"):
                with self.subTest(role=role, action=action):
                    self.assert_decision("allowed", action, role, {"iam:PermissionsBoundary": BOUNDARIES[index]})
                    self.assert_decision("explicitDeny", action, role, {}, extra_allow=True)
                    self.assert_decision("explicitDeny", action, role,
                                         {"iam:PermissionsBoundary": BOUNDARIES[(index + 1) % 5]}, extra_allow=True)

    def test_path_role_attach_and_detach_keep_both_existing_conditions(self):
        for index, role in enumerate(ROLES):
            approved = (BASIC, SQS) if index == 4 else (BASIC,)
            for action in ("iam:AttachRolePolicy", "iam:DetachRolePolicy"):
                for policy in approved:
                    with self.subTest(role=role, action=action, policy=policy):
                        context = {"iam:PermissionsBoundary": BOUNDARIES[index], "iam:PolicyARN": policy}
                        self.assert_decision("allowed", action, role, context)
                        self.assert_decision("explicitDeny", action, role, {"iam:PolicyARN": policy}, extra_allow=True)
                self.assert_decision("explicitDeny", action, role,
                                     {"iam:PermissionsBoundary": BOUNDARIES[index], "iam:PolicyARN": "arn:aws:iam::aws:policy/AdministratorAccess"},
                                     extra_allow=True)

    def test_path_role_reads_tags_and_existing_cleanup_permissions_remain_available(self):
        operations = ("GetRole", "GetRolePolicy", "ListRolePolicies", "ListAttachedRolePolicies", "ListRoleTags",
                      "DeleteRole", "DeleteRolePolicy", "TagRole", "UntagRole")
        for role in ROLES:
            for operation in operations:
                with self.subTest(role=role, operation=operation):
                    self.assert_decision("allowed", "iam:" + operation, role)

    def test_pass_role_stays_lambda_only_on_path_roles(self):
        for role in ROLES:
            self.assert_decision("allowed", "iam:PassRole", role, {"iam:PassedToService": "lambda.amazonaws.com"})
            for context in ({}, {"iam:PassedToService": "ec2.amazonaws.com"}):
                self.assert_decision("explicitDeny", "iam:PassRole", role, context, extra_allow=True)

    def test_unrelated_names_paths_accounts_and_execution_role_remain_protected(self):
        unrelated = (ROLE_PREFIX + "production-role", PATH_PREFIX + "actionbridge-dental-staging-health-role-other",
                     ROLE_PREFIX + "production/" + NAMES[0], "arn:aws:iam::111122223333:role/" + NAMES[0],
                     ROLE_PREFIX + "actionbridge-dental-staging-cfn")
        for role in unrelated:
            for operation in ("GetRole", "CreateRole", "DetachRolePolicy", "PutRolePolicy", "DeleteRole", "TagRole", "PassRole"):
                with self.subTest(role=role, operation=operation):
                    self.assert_decision("explicitDeny", "iam:" + operation, role,
                                         {"iam:PolicyARN": BASIC, "iam:PermissionsBoundary": BOUNDARIES[0],
                                          "iam:PassedToService": "lambda.amazonaws.com"}, extra_allow=True)

    def test_boundaries_and_policy_versions_cannot_be_changed_even_with_another_allow(self):
        for role in (*ROLES, *ALIASES):
            for operation in ("iam:PutRolePermissionsBoundary", "iam:DeleteRolePermissionsBoundary"):
                self.assert_decision("explicitDeny", operation, role, extra_allow=True)
        for policy in BOUNDARIES:
            for operation in ("iam:CreatePolicy", "iam:CreatePolicyVersion", "iam:SetDefaultPolicyVersion",
                              "iam:DeletePolicyVersion", "iam:DeletePolicy"):
                self.assert_decision("explicitDeny", operation, policy, extra_allow=True)

    def test_api_scope_and_collection_creation_denials_are_unchanged(self):
        api = "arn:aws:apigateway:us-east-2::/apis/" + API
        context = {"aws:RequestedRegion": "us-east-2"}
        self.assert_decision("allowed", "apigateway:PATCH", api, context)
        self.assert_decision("allowed", "apigateway:POST", api + "/integrations", context)
        self.assert_decision("explicitDeny", "apigateway:POST", "arn:aws:apigateway:us-east-2::/apis", context, extra_allow=True)
        self.assert_decision("explicitDeny", "apigateway:DELETE", "arn:aws:apigateway:us-east-2::/apis/z9y8x7w6v5", context,
                             extra_allow=True)

    def test_evaluator_matches_case_sensitive_resources_and_case_insensitive_actions(self):
        self.assert_decision("allowed", "IAM:gEtRoLe", ALIASES[0])
        self.assert_decision("explicitDeny", "IaM:cReAtErOlE", ALIASES[0], extra_allow=True)
        self.assert_decision("explicitDeny", "iam:GetRole", ALIASES[0].replace("health", "HEALTH"), extra_allow=True)
        self.assertTrue(conditions_match({"Null": {"iam:PermissionsBoundary": "true"}}, {}))
        self.assertFalse(conditions_match({"Null": {"iam:PermissionsBoundary": "true"}}, {"iam:PermissionsBoundary": BOUNDARIES[0]}))
        self.assertTrue(conditions_match({"ArnNotEquals": {"iam:PermissionsBoundary": BOUNDARIES[0]}}, {}))
        self.assertFalse(conditions_match({"ArnEquals": {"iam:PermissionsBoundary": BOUNDARIES[0]}}, {}))
        self.assertTrue(conditions_match({"ArnEquals": {"iam:PermissionsBoundary": BOUNDARIES[0]}},
                                         {"IAM:PERMISSIONSBOUNDARY": BOUNDARIES[0]}))

    def test_evaluator_rejects_unknown_operators(self):
        document = {"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": "iam:GetRole", "Resource": "*",
             "Condition": {"NumericEquals": {"unmodeled:key": "1"}}},
        ]}
        with self.assertRaisesRegex(ValueError, "Unsupported IAM test operator"):
            decision([document], "iam:GetRole", ALIASES[0])

    def test_all_repaired_parts_fit_quotas_without_losing_statements(self):
        parts = []
        for document in self.documents:
            split = EXECUTION.parts(document)
            self.assertEqual([statement for part in split for statement in part["Statement"]], document["Statement"])
            for part in split:
                self.assertLessEqual(EXECUTION.compact_size(part), 6144)
            parts.extend(split)
        self.assertLessEqual(len(parts), 10)


if __name__ == "__main__":
    unittest.main()
