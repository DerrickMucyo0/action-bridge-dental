"""Core-only requests fit the reviewed IAM baseline without the mapping repair.

Build the pinned, post-role-repair baseline from public test models, never from
ignored owner exports. A separate local audit applies these same cases to the
saved current documents. No AWS access or live permission changes occur here.
"""
import hashlib
import json
from pathlib import Path
import unittest

import test_staging_execution_repair as ROLE_REPAIR
from test_staging_role_lifecycle import decision


HERE = Path(__file__).resolve().parents[1] / "staging"
ACCOUNT, REGION, API = "631367363628", "us-east-2", "l52iwors8c"
STACK = "actionbridge-dental-staging"
CORE = ("health", "cases", "calculations")
OHIO = {"aws:RequestedRegion": REGION}
BASIC = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
PINS = {
    "identity-01.json": "65e4ac6a87ea0b1a1bf8b44f93c9836a894c988608119268b6bc7709d15e8d5b",
    "identity-02.json": "9b8c407018993fe2b02cff4304faa112214d34b6246afda7027c5e8818895c5f",
    "identity-03.json": "f7e85dadbf01bbf7553985822d343b0f96e959f20e785558f64386fc2df3ce9b",
    "guardrails-01.json": "8815922e7b6376f1b063eaa0d613a6923f95e6e40ccdf5f376961dceb996efbd",
    "guardrails-02.json": "0135b38399772f472d2b8d8d267ebdef5b83dc17a10ef05cf92418b6ad615a07",
}


def canonical_sha256(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def current_reviewed_baseline():
    # This reconstructs the original ARN-based mapping restrictions, then only
    # the already-applied role repair. It excludes the conditional mapping fix.
    documents = ROLE_REPAIR.REPAIR.repair_documents(ROLE_REPAIR.legacy_bundle())
    if {name: canonical_sha256(doc) for name, doc in documents.items()} != PINS:
        raise ValueError("Current reviewed core IAM baseline drifted.")
    return documents


def core_request_cases(slugs=CORE):
    cases = []

    def add(label, expected, action, resource, context=None):
        cases.append({"group": label, "expected": expected, "action": action,
                      "resource": resource, "context": context or {}})

    for slug in slugs:
        name = STACK + "-" + slug
        function = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{name}"
        role = f"arn:aws:iam::{ACCOUNT}:role/actionbridge/staging/{STACK}/{name}-role"
        alias = f"arn:aws:iam::{ACCOUNT}:role/{name}-role"
        boundary = f"arn:aws:iam::{ACCOUNT}:policy/{name}-boundary"
        bounded = {"iam:PermissionsBoundary": boundary}
        for action in ("iam:CreateRole", "iam:PutRolePolicy", "iam:UpdateAssumeRolePolicy"):
            add(slug, "allowed", action, role, bounded)
        for action in ("iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:ListRoleTags",
                       "iam:DeleteRole", "iam:DeleteRolePolicy", "iam:TagRole", "iam:UntagRole"):
            add(slug, "allowed", action, role)
        add(slug, "allowed", "iam:GetRole", alias)
        for action in ("iam:AttachRolePolicy", "iam:DetachRolePolicy"):
            add(slug, "allowed", action, role, {**bounded, "iam:PolicyARN": BASIC})
        add(slug, "allowed", "iam:DetachRolePolicy", alias, {"iam:PolicyARN": BASIC})
        add(slug, "allowed", "iam:PassRole", role, {"iam:PassedToService": "lambda.amazonaws.com"})
        for action in ("lambda:CreateFunction", "lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:UpdateFunctionCode",
                       "lambda:UpdateFunctionConfiguration", "lambda:DeleteFunction", "lambda:ListTags", "lambda:TagResource", "lambda:UntagResource"):
            add(slug, "allowed", action, function, OHIO)
        for action in ("lambda:AddPermission", "lambda:RemovePermission"):
            add(slug, "allowed", action, function, {**OHIO, "lambda:Principal": "apigateway.amazonaws.com"})
        add(slug, "allowed", "lambda:GetPolicy", function, OHIO)
        group = f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/lambda/{name}"
        for action in ("logs:CreateLogGroup", "logs:PutRetentionPolicy", "logs:DeleteRetentionPolicy", "logs:DeleteLogGroup",
                       "logs:ListTagsLogGroup", "logs:TagLogGroup", "logs:UntagLogGroup"):
            add(slug, "allowed", action, group + ":*", OHIO)
        for action in ("logs:ListTagsForResource", "logs:TagResource", "logs:UntagResource"):
            add(slug, "allowed", action, group, OHIO)
        add(slug, "explicitDeny", "iam:CreateRole", role, {"iam:PermissionsBoundary": boundary + "-unrelated"})
        add(slug, "explicitDeny", "iam:AttachRolePolicy", role,
            {**bounded, "iam:PolicyARN": "arn:aws:iam::aws:policy/AdministratorAccess"})
        add(slug, "explicitDeny", "iam:DeleteRolePermissionsBoundary", role)
        add(slug, "explicitDeny", "iam:PassRole", role, {"iam:PassedToService": "ec2.amazonaws.com"})
        add(slug, "explicitDeny", "lambda:DeleteFunction", function.replace("staging", "production"), OHIO)
        add(slug, "explicitDeny", "lambda:CreateFunction", function, {"aws:RequestedRegion": "us-east-1"})
        add(slug, "explicitDeny", "iam:DeleteRole", alias)

    api = f"arn:aws:apigateway:{REGION}::/apis/{API}"
    for suffix in ("", "/authorizers", "/authorizers/example", "/integrations", "/integrations/example", "/routes", "/routes/example", "/stages", "/stages/staging"):
        for method in ("GET", "PATCH", "PUT", "POST", "DELETE"):
            add("api", "allowed", "apigateway:" + method, api + suffix, OHIO)
    table = f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{STACK}-cases"
    for action in ("dynamodb:CreateTable", "dynamodb:DescribeTable", "dynamodb:UpdateTable", "dynamodb:DeleteTable", "dynamodb:DescribeTimeToLive",
                   "dynamodb:UpdateTimeToLive", "dynamodb:ListTagsOfResource", "dynamodb:TagResource", "dynamodb:UntagResource"):
        add("table", "allowed", action, table, OHIO)
    add("logs", "allowed", "logs:DescribeLogGroups", "*", OHIO)
    artifacts = f"arn:aws:s3:::ab-dental-staging-artifacts-{ACCOUNT}-{REGION}/"
    add("artifacts", "allowed", "s3:GetObject", artifacts + STACK + "/health/example.zip", {"s3:ResourceAccount": ACCOUNT})
    add("artifacts", "explicitDeny", "s3:GetObject", artifacts + "unrelated/health/example.zip", {"s3:ResourceAccount": ACCOUNT})
    # These remain denied in the current live baseline; core avoids them by
    # excluding worker/mappings rather than applying the conditional proposal.
    for action in ("lambda:GetEventSourceMapping", "lambda:DeleteEventSourceMapping"):
        add("mapping_unchanged", "explicitDeny", action, "*",
            {**OHIO, "lambda:FunctionArn": f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{STACK}-job-worker"})
    return cases


def core_runtime_cases():
    cases = []
    for slug in CORE:
        stream = f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/lambda/{STACK}-{slug}:log-stream:synthetic"
        for action in ("logs:CreateLogStream", "logs:PutLogEvents"):
            cases.append((slug, "allowed", action, stream))
        for action in ("sqs:SendMessage", "bedrock:InvokeModel", "lambda:CreateEventSourceMapping"):
            cases.append((slug, "explicitDeny", action, "*"))
        if slug != "health":
            table = f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{STACK}-cases"
            actions = ("dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:ConditionCheckItem", "dynamodb:Query") if slug == "cases" else ("dynamodb:GetItem",)
            cases.extend((slug, "allowed", action, table) for action in actions)
            cases.append((slug, "explicitDeny", "dynamodb:GetItem", table.replace("staging", "production")))
    return cases


class StagingCoreIAMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = current_reviewed_baseline()
        cls.docs = list(cls.baseline.values())

    def test_core_requests_are_allowed_and_unrelated_access_remains_denied(self):
        cases = core_request_cases()
        self.assertEqual(set(case["group"] for case in cases if case["group"] in CORE), set(CORE))
        for case in cases:
            with self.subTest(group=case["group"], action=case["action"], resource=case["resource"]):
                self.assertEqual(decision(self.docs, case["action"], case["resource"], case["context"]), case["expected"])

    def test_core_does_not_require_or_apply_the_mapping_policy_correction(self):
        self.assertEqual(self.baseline["identity-02.json"]["Statement"][4]["Resource"],
                         f"arn:aws:lambda:{REGION}:{ACCOUNT}:event-source-mapping:*")
        self.assertEqual(self.baseline["guardrails-02.json"]["Statement"][9]["Action"],
                         ["lambda:GetEventSourceMapping", "lambda:UpdateEventSourceMapping", "lambda:DeleteEventSourceMapping"])
        for case in core_request_cases():
            if case["expected"] == "allowed":
                self.assertNotIn("EventSourceMapping", case["action"])

    def test_three_runtime_boundaries_keep_core_actions_and_deny_background_services(self):
        docs = {slug: json.loads((HERE / "generated" / f"{STACK}-{slug}-boundary.json").read_text()) for slug in CORE}
        for slug, expected, action, resource in core_runtime_cases():
            with self.subTest(function=slug, action=action):
                self.assertEqual(decision([docs[slug]], action, resource), expected)


if __name__ == "__main__":
    unittest.main()
