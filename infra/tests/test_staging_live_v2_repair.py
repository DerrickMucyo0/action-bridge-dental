"""Regress the owner-exported v2 mismatch without reading private .staging files.

The reported guardrails-01 v2 is the complete intended repair, while identity-03
v2 contains only its original three statements. A version label alone therefore
does not establish that the five required allow/deny supplements were applied.
"""
import copy
import unittest

import test_staging_execution_repair as REPAIR_TESTS


LIFECYCLE = REPAIR_TESTS.LIFECYCLE
REPAIR = REPAIR_TESTS.REPAIR
API = "l52iwors8c"
ALIASES = LIFECYCLE.ALIASES
ROLES = LIFECYCLE.ROLES
BOUNDARIES = LIFECYCLE.BOUNDARIES
BASIC, SQS = LIFECYCLE.BASIC, LIFECYCLE.SQS
IDENTITY = "identity-03.json"
GUARDRAILS = "guardrails-01.json"


def reported_v2_fixture():
    """Synthesize the exported mismatch from public, pinned baseline structures."""
    original = REPAIR_TESTS.legacy_bundle()
    intended = REPAIR.repair_documents(original)
    reported = copy.deepcopy(intended)
    reported[IDENTITY]["Statement"] = copy.deepcopy(intended[IDENTITY]["Statement"][:3])
    return original, reported, intended


def evaluate(bundle, action, resource, context=None, extra_allow=False):
    documents = [bundle[name] for name in sorted(bundle)]
    if extra_allow:
        documents.append({"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": "*", "Resource": "*"},
        ]})
    return LIFECYCLE.decision(documents, action, resource, context)


class StagingLiveV2RepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original, cls.reported, cls.intended = reported_v2_fixture()

    def test_reported_v2_has_complete_guardrails_but_original_identity_content(self):
        self.assertEqual(self.reported[GUARDRAILS], self.intended[GUARDRAILS])
        self.assertEqual(len(self.reported[GUARDRAILS]["Statement"]), 14)
        self.assertEqual(self.reported[IDENTITY], self.original[IDENTITY])
        self.assertEqual(len(self.reported[IDENTITY]["Statement"]), 3)
        self.assertEqual(REPAIR.canonical_sha256(self.reported[IDENTITY]),
                         REPAIR.BASELINE_CANONICAL_SHA256[IDENTITY])

    def test_reported_mixed_snapshot_implicitly_denies_both_required_alias_operations(self):
        for index, alias in enumerate(ALIASES):
            with self.subTest(alias=alias, action="iam:GetRole"):
                self.assertEqual(evaluate(self.reported, "iam:GetRole", alias), "implicitDeny")
            approved = (BASIC, SQS) if index == 4 else (BASIC,)
            for policy in approved:
                with self.subTest(alias=alias, action="iam:DetachRolePolicy", policy=policy):
                    self.assertEqual(evaluate(self.reported, "iam:DetachRolePolicy", alias,
                                              {"iam:PolicyARN": policy}), "implicitDeny")

    def test_only_identity03_needs_replacement_and_original_prefix_is_preserved(self):
        before = copy.deepcopy(self.reported)
        changed = {name for name in self.reported if self.reported[name] != self.intended[name]}
        self.assertEqual(changed, {IDENTITY})
        self.assertEqual(self.reported[GUARDRAILS], self.intended[GUARDRAILS])
        self.assertEqual(self.intended[IDENTITY]["Statement"][:3], self.reported[IDENTITY]["Statement"])
        self.assertEqual(self.reported, before)

    def test_identity_replacement_contains_all_five_allow_and_deny_additions_and_fits_quota(self):
        replacement = self.intended[IDENTITY]
        self.assertEqual(len(replacement["Statement"]), 8)
        additions = replacement["Statement"][3:]
        self.assertEqual(len(additions), 5)
        self.assertEqual(sum(statement["Effect"] == "Allow" for statement in additions), 3)
        self.assertEqual(sum(statement["Effect"] == "Deny" for statement in additions), 2)
        self.assertEqual(REPAIR.compact_size(replacement), 3262)
        self.assertLessEqual(REPAIR.compact_size(replacement), 6144)

    def test_complete_identity_replacement_allows_exact_alias_lookup_and_approved_cleanup(self):
        for index, alias in enumerate(ALIASES):
            self.assertEqual(evaluate(self.intended, "iam:GetRole", alias), "allowed")
            for policy in ((BASIC, SQS) if index == 4 else (BASIC,)):
                with self.subTest(alias=alias, policy=policy):
                    self.assertEqual(evaluate(self.intended, "iam:DetachRolePolicy", alias,
                                              {"iam:PolicyARN": policy}), "allowed")

    def test_both_deny_supplements_are_required_in_addition_to_the_three_allows(self):
        for index, alias in enumerate(ALIASES):
            # The incomplete snapshot is implicitly safe only while no other
            # broad Allow exists. The full replacement must restore explicit
            # protections even against a future supplemental Allow.
            create_context = {"iam:PermissionsBoundary": BOUNDARIES[index]}
            self.assertEqual(evaluate(self.reported, "iam:CreateRole", alias, create_context,
                                      extra_allow=True), "allowed")
            self.assertEqual(evaluate(self.intended, "iam:CreateRole", alias, create_context,
                                      extra_allow=True), "explicitDeny")
            bounded_cleanup = {"iam:PolicyARN": BASIC, "iam:PermissionsBoundary": BOUNDARIES[index]}
            self.assertEqual(evaluate(self.reported, "iam:DetachRolePolicy", alias, bounded_cleanup,
                                      extra_allow=True), "allowed")
            self.assertEqual(evaluate(self.intended, "iam:DetachRolePolicy", alias, bounded_cleanup,
                                      extra_allow=True), "explicitDeny")

    def test_fixed_snapshot_explicitly_denies_wrong_policy_boundary_present_and_other_alias_mutations(self):
        for index, alias in enumerate(ALIASES):
            wrong_policies = ("arn:aws:iam::aws:policy/AdministratorAccess", BOUNDARIES[index])
            if index != 4:
                wrong_policies += (SQS,)
            for policy in wrong_policies:
                self.assertEqual(evaluate(self.intended, "iam:DetachRolePolicy", alias,
                                          {"iam:PolicyARN": policy}, extra_allow=True), "explicitDeny")
            self.assertEqual(evaluate(self.intended, "iam:DetachRolePolicy", alias, {}, extra_allow=True),
                             "explicitDeny")
            for boundary in (BOUNDARIES[index], "arn:aws:iam::631367363628:policy/unrelated-boundary"):
                self.assertEqual(evaluate(self.intended, "iam:DetachRolePolicy", alias,
                                          {"iam:PolicyARN": BASIC, "iam:PermissionsBoundary": boundary},
                                          extra_allow=True), "explicitDeny")
            for action in ("CreateRole", "DeleteRole", "AttachRolePolicy", "PutRolePolicy", "DeleteRolePolicy",
                           "UpdateAssumeRolePolicy", "TagRole", "UntagRole", "PassRole"):
                with self.subTest(alias=alias, action=action):
                    self.assertEqual(evaluate(self.intended, "iam:" + action, alias,
                                              {"iam:PolicyARN": BASIC, "iam:PermissionsBoundary": BOUNDARIES[index],
                                               "iam:PassedToService": "lambda.amazonaws.com"}, extra_allow=True),
                                     "explicitDeny")

    def test_original_path_role_lifecycle_and_API_scope_are_unchanged(self):
        for bundle in (self.reported, self.intended):
            for index, role in enumerate(ROLES):
                for action in ("CreateRole", "PutRolePolicy", "UpdateAssumeRolePolicy"):
                    self.assertEqual(evaluate(bundle, "iam:" + action, role,
                                              {"iam:PermissionsBoundary": BOUNDARIES[index]}), "allowed")
                    self.assertEqual(evaluate(bundle, "iam:" + action, role, {}, extra_allow=True), "explicitDeny")
                for action in ("AttachRolePolicy", "DetachRolePolicy"):
                    self.assertEqual(evaluate(bundle, "iam:" + action, role,
                                              {"iam:PolicyARN": BASIC, "iam:PermissionsBoundary": BOUNDARIES[index]}),
                                     "allowed")
                for action in ("GetRole", "DeleteRole", "DeleteRolePolicy", "TagRole", "UntagRole"):
                    self.assertEqual(evaluate(bundle, "iam:" + action, role), "allowed")
                self.assertEqual(evaluate(bundle, "iam:PassRole", role,
                                          {"iam:PassedToService": "lambda.amazonaws.com"}), "allowed")
                self.assertEqual(evaluate(bundle, "iam:PassRole", role,
                                          {"iam:PassedToService": "ec2.amazonaws.com"}, extra_allow=True), "explicitDeny")
            region = {"aws:RequestedRegion": "us-east-2"}
            self.assertEqual(evaluate(bundle, "apigateway:PATCH", "arn:aws:apigateway:us-east-2::/apis/" + API,
                                      region), "allowed")
            self.assertEqual(evaluate(bundle, "apigateway:DELETE", "arn:aws:apigateway:us-east-2::/apis/z9y8x7w6v5",
                                      region, extra_allow=True), "explicitDeny")
            self.assertEqual(evaluate(bundle, "apigateway:POST", "arn:aws:apigateway:us-east-2::/apis",
                                      region, extra_allow=True), "explicitDeny")

    def test_unrelated_roles_and_boundary_policy_changes_remain_explicitly_denied(self):
        for bundle in (self.reported, self.intended):
            unrelated = ("arn:aws:iam::631367363628:role/production-role",
                         "arn:aws:iam::111122223333:role/actionbridge-dental-staging-health-role",
                         "arn:aws:iam::631367363628:role/production/actionbridge-dental-staging-health-role",
                         "arn:aws:iam::631367363628:role/actionbridge-dental-staging-cfn")
            for role in unrelated:
                for action in ("GetRole", "CreateRole", "DetachRolePolicy", "DeleteRole", "PassRole"):
                    self.assertEqual(evaluate(bundle, "iam:" + action, role,
                                              {"iam:PolicyARN": BASIC, "iam:PermissionsBoundary": BOUNDARIES[0],
                                               "iam:PassedToService": "lambda.amazonaws.com"}, extra_allow=True),
                                     "explicitDeny")
            for role in (*ROLES, *ALIASES):
                for action in ("iam:PutRolePermissionsBoundary", "iam:DeleteRolePermissionsBoundary"):
                    self.assertEqual(evaluate(bundle, action, role, extra_allow=True), "explicitDeny")
            for boundary in BOUNDARIES:
                for action in ("CreatePolicy", "CreatePolicyVersion", "SetDefaultPolicyVersion",
                               "DeletePolicyVersion", "DeletePolicy"):
                    self.assertEqual(evaluate(bundle, "iam:" + action, boundary, extra_allow=True), "explicitDeny")


if __name__ == "__main__":
    unittest.main()
