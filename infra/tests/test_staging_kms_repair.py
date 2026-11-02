"""Bounded, adversarial IAM checks for the owner-controlled KMS repair.

These tests model identity policies and permissions boundaries only. They never
flatten resource/key policies or grants into identity Allows, contact AWS, or
claim to replace AWS's authorization engine. Public policy builders reconstruct
the fixture; ignored owner exports and CLI credentials are not test inputs.
"""
import copy
from fnmatch import fnmatchcase
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_staging_delegated_access as DELEGATED
import test_staging_http_stage_tagging as TAGGING


HERE = Path(__file__).resolve().parents[1] / "staging"
OPERATORS = {
    "StringEquals", "StringNotEquals", "StringLike", "StringNotLike",
    "ArnEquals", "ArnNotEquals", "ArnLike", "ArnNotLike", "Null", "Bool", "BoolIfExists",
    "ForAllValues:StringEquals", "ForAnyValue:StringNotEquals",
}
NEGATED = {"StringNotEquals", "StringNotLike", "ArnNotEquals", "ArnNotLike"}
BROAD = {"Version": "2012-10-17", "Statement": [
    {"Effect": "Allow", "Action": "*", "Resource": "*"},
]}
BOUNDARY_IDS = tuple(logical + "KmsBoundary" for logical in DELEGATED.D.LOGICAL[:3])
TEST_BOUNDARY_ARNS = tuple(
    f"arn:aws:iam::{DELEGATED.D.ACCOUNT}:policy/" + "x" * (128 - len(logical)) + logical
    for logical in BOUNDARY_IDS)


def resolved(value):
    """Resolve only reviewed intrinsics, using distinct maximum-length names."""
    if isinstance(value, list):
        return [resolved(item) for item in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {"Ref"} and value["Ref"] in BOUNDARY_IDS:
        return TEST_BOUNDARY_ARNS[BOUNDARY_IDS.index(value["Ref"])]
    if any(key in value for key in ("Ref", "Fn::GetAtt", "Fn::Sub")):
        return DELEGATED.resolved(value)
    return {key: resolved(item) for key, item in value.items()}


def values(value):
    return value if isinstance(value, list) else [value]


def arn_matches(actual, expected):
    left, right = actual.split(":", 5), expected.split(":", 5)
    return len(left) == len(right) == 6 and all(
        fnmatchcase(part, wanted) for part, wanted in zip(left, right))


def boolean(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    raise ValueError("IAM Bool/Null requires true or false")


def validate_conditions(conditions):
    if not isinstance(conditions, dict):
        raise ValueError("Conditions must be an object")
    if set(conditions) - OPERATORS:
        raise ValueError("Unsupported IAM test operator")
    for operator, clauses in conditions.items():
        if not isinstance(clauses, dict) or not clauses:
            raise ValueError("Condition operator requires key/value clauses")
        for key, expected in clauses.items():
            if not isinstance(key, str) or not key or not values(expected):
                raise ValueError("Condition key/value must be nonempty")
            if operator in ("Bool", "BoolIfExists", "Null"):
                if isinstance(expected, list):
                    raise ValueError("This model requires scalar Bool/Null values")
                boolean(expected)
            elif any(not isinstance(item, str) for item in values(expected)):
                raise ValueError("Condition policy values must be strings")


def conditions_match(conditions, context):
    validate_conditions(conditions)
    normalized = {key.lower(): value for key, value in context.items()}
    for operator, clauses in conditions.items():
        for key, expected in clauses.items():
            actual = normalized.get(key.lower())
            present = actual is not None and actual != "" and actual != []
            if operator == "Null":
                matches = (not present) == boolean(expected)
            elif operator in ("Bool", "BoolIfExists"):
                matches = ((not present and operator == "BoolIfExists") or
                           (present and boolean(actual) == boolean(expected)))
            elif operator == "ForAllValues:StringEquals":
                # AWS set operators are vacuously true for an absent/empty key.
                # A separate Null:false is needed when presence is required.
                matches = not present or all(item in values(expected) for item in values(actual))
            elif operator == "ForAnyValue:StringNotEquals":
                matches = present and any(item not in values(expected) for item in values(actual))
            else:
                if isinstance(actual, (dict, bool)) or isinstance(actual, list):
                    raise ValueError("Set-valued request keys need an explicit set operator")
                compare = (arn_matches if operator.startswith("Arn") else
                           fnmatchcase if operator in ("StringLike", "StringNotLike") else
                           lambda left, right: left == right)
                matches = present and any(compare(actual, wanted) for wanted in values(expected))
                if operator in NEGATED:
                    matches = not matches
            if not matches:
                return False
    return True


def decision(documents, action, resource, context=None):
    """Evaluate only the declared IAM identity subset; fail on unknown syntax."""
    statements = []
    for document in documents:
        if set(document) - {"Version", "Statement", "Id"}:
            raise ValueError("Unknown policy field")
        if not isinstance(document.get("Statement"), list):
            raise ValueError("Statement must be an array")
        statements.extend(document["Statement"])
    for statement in statements:
        if set(statement) - {"Sid", "Effect", "Action", "NotAction", "Resource", "NotResource", "Condition"}:
            raise ValueError("Resource policies, Principals and unknown fields require a separate model")
        if statement.get("Effect") not in ("Allow", "Deny"):
            raise ValueError("Unknown effect")
        if ("Action" in statement) == ("NotAction" in statement):
            raise ValueError("Exactly one Action or NotAction is required")
        if ("Resource" in statement) == ("NotResource" in statement):
            raise ValueError("Exactly one Resource or NotResource is required")
        for key in ("Action", "NotAction", "Resource", "NotResource"):
            if key in statement and (not values(statement[key]) or
                                     any(not isinstance(item, str) for item in values(statement[key]))):
                raise ValueError("Unresolved or invalid action/resource")
        validate_conditions(statement.get("Condition", {}))
    allowed = False
    for statement in statements:
        action_key = "Action" if "Action" in statement else "NotAction"
        match = any(fnmatchcase(action.lower(), pattern.lower()) for pattern in values(statement[action_key]))
        if match == (action_key == "NotAction"):
            continue
        resource_key = "Resource" if "Resource" in statement else "NotResource"
        match = any(fnmatchcase(resource, pattern) for pattern in values(statement[resource_key]))
        if match == (resource_key == "NotResource"):
            continue
        if not conditions_match(statement.get("Condition", {}), context or {}):
            continue
        if statement["Effect"] == "Deny":
            return "explicitDeny"
        allowed = True
    return "allowed" if allowed else "implicitDeny"


def runtime_decision(identity, boundary, action, resource, context=None, extra=None):
    """Boundary is an intersection, never an independent source of Allow."""
    identity_result = decision([identity] + (extra or []), action, resource, context)
    boundary_result = decision([boundary], action, resource, context)
    if "explicitDeny" in (identity_result, boundary_result):
        return "explicitDeny"
    return "allowed" if identity_result == boundary_result == "allowed" else "implicitDeny"


def dependency_order(template):
    """Topologically order explicit and intrinsic resource dependencies."""
    resources = template["Resources"]
    graph = {logical: set() for logical in resources}

    def references(value):
        found = set()
        if isinstance(value, list):
            for item in value:
                found.update(references(item))
        elif isinstance(value, dict):
            if "Ref" in value:
                logical = value["Ref"]
                if not logical.startswith("AWS::"):
                    if logical not in resources:
                        raise ValueError("Unknown Ref dependency")
                    found.add(logical)
            if "Fn::GetAtt" in value:
                logical = value["Fn::GetAtt"][0]
                if logical not in resources:
                    raise ValueError("Unknown GetAtt dependency")
                found.add(logical)
            if "Fn::Sub" in value:
                substitution = value["Fn::Sub"]
                text, mapping = substitution if isinstance(substitution, list) else (substitution, {})
                for token in re.findall(r"\$\{([^}]+)\}", text):
                    logical = token.split(".", 1)[0]
                    if logical not in mapping and logical in resources:
                        found.add(logical)
            for nested in value.values():
                found.update(references(nested))
        return found

    for logical, resource in resources.items():
        explicit = set(values(resource.get("DependsOn", [])))
        if explicit - set(resources):
            raise ValueError("Unknown DependsOn dependency")
        graph[logical] = explicit | references(resource.get("Properties", {}))
    order, states = [], {}

    def visit(logical):
        if states.get(logical) == "visiting":
            raise ValueError("Resource dependency cycle")
        if states.get(logical) == "visited":
            return
        states[logical] = "visiting"
        for dependency in sorted(graph[logical]):
            visit(dependency)
        states[logical] = "visited"
        order.append(logical)

    for logical in sorted(resources):
        visit(logical)
    return graph, order


class StrictKmsIamModelTests(unittest.TestCase):
    def test_unknown_operators_and_resource_policies_cannot_be_silently_flattened(self):
        for change in ({"Condition": {"DateLessThan": {"aws:CurrentTime": "2099-01-01T00:00:00Z"}}},
                       {"Condition": {"ForAnyValue:StringEquals": {"kms:GrantOperations": ["Decrypt"]}}},
                       {"Principal": {"AWS": "*"}}, {"UnfamiliarNestedField": {"Allow": True}}):
            document = copy.deepcopy(BROAD)
            document["Statement"].append({"Effect": "Deny", "Action": "never:Matched", "Resource": "*", **change})
            with self.subTest(change=change), self.assertRaises(ValueError):
                decision([document], "kms:Decrypt", "*")

    def test_multiple_condition_keys_are_and_and_expected_values_are_or(self):
        clauses = {"StringEquals": {"kms:CallerAccount": "631367363628", "kms:ViaService": ["lambda.us-east-2.amazonaws.com", "dynamodb.us-east-2.amazonaws.com"]}}
        self.assertTrue(conditions_match(clauses, {"KMS:CALLERACCOUNT": "631367363628", "kms:ViaService": "lambda.us-east-2.amazonaws.com"}))
        self.assertFalse(conditions_match(clauses, {"kms:CallerAccount": "631367363628"}))
        self.assertFalse(conditions_match(clauses, {"kms:CallerAccount": "other", "kms:ViaService": "lambda.us-east-2.amazonaws.com"}))

    def test_negated_conditions_match_absent_keys_and_apply_nor(self):
        for operator in ("StringNotEquals", "StringNotLike", "ArnNotEquals", "ArnNotLike"):
            expected = ["arn:aws:iam::631367363628:role/first", "arn:aws:iam::631367363628:role/second"]
            self.assertTrue(conditions_match({operator: {"test:key": expected}}, {}))
            self.assertFalse(conditions_match({operator: {"test:key": expected}}, {"test:key": expected[0]}))
            self.assertTrue(conditions_match({operator: {"test:key": expected}}, {"test:key": expected[0] + "-other"}))

    def test_arn_like_and_string_like_keep_region_and_account_segments(self):
        clauses = {"ArnLike": {"test:principal": "arn:aws:sts::631367363628:assumed-role/named/*"},
                   "StringLike": {"test:service": "dynamodb.us-east-2.*"}}
        good = {"test:principal": "arn:aws:sts::631367363628:assumed-role/named/session", "test:service": "dynamodb.us-east-2.amazonaws.com"}
        self.assertTrue(conditions_match(clauses, good))
        self.assertFalse(conditions_match(clauses, {**good, "test:principal": good["test:principal"].replace("631367363628", "195469705669")}))
        self.assertFalse(conditions_match(clauses, {**good, "test:service": "dynamodb.us-east-1.amazonaws.com"}))

    def test_grant_set_requires_every_operation_and_separate_nonempty_guard(self):
        clauses = {"ForAllValues:StringEquals": {"kms:GrantOperations": ["Decrypt", "RetireGrant"]},
                   "Null": {"kms:GrantOperations": "false"}, "Bool": {"kms:GrantIsForAWSResource": "true"}}
        self.assertTrue(conditions_match(clauses, {"kms:GrantOperations": ["Decrypt", "RetireGrant"], "kms:GrantIsForAWSResource": True}))
        for operations in ([], ["Decrypt", "Encrypt"], ["CreateGrant"], None):
            self.assertFalse(conditions_match(clauses, {"kms:GrantOperations": operations, "kms:GrantIsForAWSResource": "true"}))
        self.assertTrue(conditions_match({"ForAllValues:StringEquals": {"kms:GrantOperations": ["Decrypt"]}}, {}))
        with self.assertRaises(ValueError):
            conditions_match({"Bool": {"test:flag": "true"}}, {"test:flag": "yes"})

    def test_boundary_is_an_intersection_and_explicit_deny_wins(self):
        key = "arn:aws:kms:us-east-2:631367363628:key/example"
        deny = {"Statement": [{"Effect": "Deny", "Action": "kms:Decrypt", "Resource": key}]}
        empty = {"Statement": []}
        self.assertEqual(decision([BROAD, deny], "kms:Decrypt", key), "explicitDeny")
        self.assertEqual(runtime_decision(empty, BROAD, "kms:Decrypt", key), "implicitDeny")
        self.assertEqual(runtime_decision(BROAD, empty, "kms:Decrypt", key), "implicitDeny")
        self.assertEqual(runtime_decision(BROAD, deny, "kms:Decrypt", key), "explicitDeny")

    def test_grant_escalation_deny_requires_any_unlisted_operation(self):
        clause = {"ForAnyValue:StringNotEquals": {"kms:GrantOperations": ["Decrypt", "RetireGrant"]}}
        self.assertFalse(conditions_match(clause, {"kms:GrantOperations": ["Decrypt", "RetireGrant"]}))
        self.assertTrue(conditions_match(clause, {"kms:GrantOperations": ["Decrypt", "CreateGrant"]}))
        self.assertFalse(conditions_match(clause, {}))
        clause = {"BoolIfExists": {"kms:GrantIsForAWSResource": "false"}}
        self.assertTrue(conditions_match(clause, {}))
        self.assertTrue(conditions_match(clause, {"kms:GrantIsForAWSResource": False}))
        self.assertFalse(conditions_match(clause, {"kms:GrantIsForAWSResource": True}))

    def test_dependency_model_fails_on_cycles_and_unknown_references(self):
        cycle = {"Resources": {"First": {"DependsOn": "Second"}, "Second": {"DependsOn": "First"}}}
        with self.assertRaises(ValueError):
            dependency_order(cycle)
        for template in ({"Resources": {"First": {"DependsOn": "Missing"}}},
                         {"Resources": {"First": {"Properties": {"Target": {"Ref": "Missing"}}}}}):
            with self.assertRaises(ValueError):
                dependency_order(template)


class KmsRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("owner_kms_repair", HERE / "prepare-kms-repair.py")
        cls.R = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.R)
        cls.D = DELEGATED.D
        # Reconstruct the reviewed access stack from committed public builders,
        # not ignored exports, account credentials, or private CloudTrail files.
        cls.source = TAGGING.PROPOSAL.proposal_documents(TAGGING.PREVIOUS.recovery_a_baseline())
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        source = Path(directory.name)
        for name, policy in cls.source.items():
            (source / name).write_text(json.dumps(policy))
        source_patch = patch.object(cls.R.D, "POLICY_SOURCE", source)
        source_patch.start()
        cls.addClassCleanup(source_patch.stop)
        with patch.object(cls.D, "POLICY_SOURCE", source):
            cls.baseline = cls.D.access_template()
        cls.candidate = cls.R.repair_template(cls.baseline)
        cls.ceilings = cls.policies(cls.candidate, "ExecutionCeiling")
        cls.deployer = cls.policies(cls.candidate, "DeployerPolicy")
        cls.original_ceilings = cls.policies(cls.baseline, "ExecutionCeiling")
        cls.original_deployer = cls.policies(cls.baseline, "DeployerPolicy")

    @staticmethod
    def policies(template, prefix):
        return [resolved(value["Properties"]["PolicyDocument"])
                for name, value in template["Resources"].items() if name.startswith(prefix)]

    def cfn(self, action, key, context):
        # The adversarial Allow represents a separate identity/resource grant
        # solely to prove the immutable explicit-Deny ceiling cannot be bypassed.
        # This is not a model of key-policy Principal/delegation evaluation.
        return decision(self.ceilings + [BROAD], action, key, context)

    def deploy(self, action, key, context, adversarial=False):
        return decision(self.deployer + ([BROAD] if adversarial else []), action, key, context)

    def common(self, service=None):
        context = {"aws:RequestedRegion": self.R.REGION, "kms:CallerAccount": self.R.ACCOUNT}
        if service:
            context["kms:ViaService"] = service + ".us-east-2.amazonaws.com"
        return context

    def lambda_context(self, index=0, service=None):
        return {**self.common(service), "kms:EncryptionContext:aws:lambda:FunctionArn": self.R.CORE_FUNCTIONS[index]}

    def ddb_context(self):
        return {**self.common("dynamodb"),
                "kms:EncryptionContext:aws:dynamodb:tableName": self.D.STACK + "-cases",
                "kms:EncryptionContext:aws:dynamodb:subscriberId": self.R.ACCOUNT}

    def grant_context(self, key, index=0):
        if key == self.R.LAMBDA_KEY:
            return {**self.lambda_context(index, "lambda"), "kms:GrantIsForAWSResource": True,
                    "kms:GranteePrincipal": self.R.LAMBDA_GRANTEES[index],
                    "kms:GrantOperations": self.R.LAMBDA_GRANT_OPERATIONS,
                    "kms:GrantConstraintType": "EncryptionContextEquals"}
        return {**self.ddb_context(), "kms:GrantIsForAWSResource": True,
                "kms:GrantOperations": self.R.DDB_GRANT_OPERATIONS,
                "kms:GrantConstraintType": "EncryptionContextSubset"}

    def runtime_documents(self, index):
        logical = self.D.LOGICAL[index] + "Role"
        properties = self.candidate["Resources"][logical]["Properties"]
        boundary_id = properties["PermissionsBoundary"]["Ref"]
        boundary = self.candidate["Resources"][boundary_id]["Properties"]["PolicyDocument"]
        return properties["Policies"][0]["PolicyDocument"], boundary

    def test_exact_resource_ownership_and_only_reviewed_additions(self):
        before, after = self.baseline["Resources"], self.candidate["Resources"]
        expected = {logical + "KmsBoundary" for logical in self.D.LOGICAL[:3]}
        self.assertEqual((len(before), len(after)), (14, 17))
        self.assertEqual(set(after) - set(before), expected)
        self.assertEqual(set(before) - set(after), set())
        self.assertEqual(self.candidate.keys(), self.baseline.keys())
        for key in self.baseline.keys() - {"Resources"}:
            self.assertEqual(self.candidate[key], self.baseline[key], key)
        permitted = {logical + "Role" for logical in self.D.LOGICAL[:3]}
        permitted |= {name for name in before if name.startswith(("ExecutionCeiling", "DeployerPolicy"))}
        self.assertLessEqual({name for name in before if before[name] != after[name]}, permitted)
        self.assertEqual(after["DeployerRole"], before["DeployerRole"])
        self.assertEqual(after["FrontendApp"], before["FrontendApp"])
        for logical in self.D.LOGICAL[3:]:
            self.assertEqual(after[logical + "Role"], before[logical + "Role"])
        for logical, arn in zip(self.D.LOGICAL[:3], TEST_BOUNDARY_ARNS):
            role = after[logical + "Role"]
            previous = before[logical + "Role"]
            self.assertEqual({k: v for k, v in role["Properties"].items() if k not in ("PermissionsBoundary", "Policies")},
                             {k: v for k, v in previous["Properties"].items() if k not in ("PermissionsBoundary", "Policies")})
            policy = after[logical + "KmsBoundary"]
            self.assertEqual(policy["Type"], "AWS::IAM::ManagedPolicy")
            self.assertEqual(policy["DeletionPolicy"], "Retain")
            self.assertEqual(policy["UpdateReplacePolicy"], "Retain")
            self.assertNotIn("ManagedPolicyName", policy["Properties"])
            self.assertEqual(role["Properties"]["PermissionsBoundary"], {"Ref": logical + "KmsBoundary"})
            self.assertNotIn(arn, self.D.EDITABLE)
        self.assertTrue(self.R.validate_candidate(self.baseline, self.candidate))

    def test_original_failures_are_explicit_denies_even_with_broad_allow(self):
        for action, key, context in (("kms:DescribeKey", self.R.DDB_KEY, self.common("dynamodb")),
                                     ("kms:Encrypt", self.R.LAMBDA_KEY, self.lambda_context(0, "lambda"))):
            self.assertEqual(decision(self.original_ceilings + [BROAD], action, key, context), "explicitDeny")
            self.assertEqual(self.cfn(action, key, context), "allowed")
        for index in range(3):
            old_boundary = json.loads((HERE / "generated" / (self.D.STACK + "-" + self.D.SLUGS[index] + "-boundary.json")).read_text())
            self.assertEqual(decision([old_boundary, BROAD], "kms:Decrypt", self.R.LAMBDA_KEY, self.lambda_context(index)), "explicitDeny")

    def test_provider_metadata_does_not_require_encryption_context(self):
        for key, service in ((self.R.DDB_KEY, "dynamodb"), (self.R.LAMBDA_KEY, "lambda")):
            self.assertEqual(self.cfn("kms:DescribeKey", key, self.common(service)), "allowed")
            # Metadata is deliberately not gated by service/encryption-context
            # keys. Actual key-policy delegation is checked outside this model.
            self.assertEqual(self.cfn("kms:DescribeKey", key, self.common()), "allowed")
            for context in ({}, {"aws:RequestedRegion": self.R.REGION}):
                self.assertEqual(self.cfn("kms:DescribeKey", key, context), "explicitDeny")

    def test_all_core_provider_create_read_and_rollback_lambda_contexts(self):
        for index in range(3):
            self.assertEqual(self.cfn("kms:Encrypt", self.R.LAMBDA_KEY, self.lambda_context(index, "lambda")), "allowed")
            self.assertEqual(self.cfn("kms:Decrypt", self.R.LAMBDA_KEY, self.lambda_context(index)), "allowed")
            self.assertEqual(self.cfn("kms:Decrypt", self.R.LAMBDA_KEY, self.lambda_context(index, "lambda")), "allowed")
            # The key's context-only Decrypt path is deliberate; Encrypt/grant
            # creation still require AWS's service-mediated request context.
            self.assertEqual(self.cfn("kms:Encrypt", self.R.LAMBDA_KEY, self.lambda_context(index)), "explicitDeny")
        self.assertEqual(self.cfn("kms:Encrypt", self.R.DDB_KEY, self.ddb_context()), "explicitDeny")
        self.assertEqual(self.cfn("kms:Decrypt", self.R.DDB_KEY, self.ddb_context()), "allowed")
        self.assertEqual(self.cfn("kms:Decrypt", self.R.DDB_KEY, self.common()), "explicitDeny")

    def test_successful_service_grants_and_each_required_context_guard(self):
        for key, indices in ((self.R.DDB_KEY, [0]), (self.R.LAMBDA_KEY, range(3))):
            for index in indices:
                context = self.grant_context(key, index)
                self.assertEqual(self.cfn("kms:CreateGrant", key, context), "allowed")
                for required in context:
                    missing = {name: value for name, value in context.items() if name != required}
                    with self.subTest(key=key, index=index, missing=required):
                        self.assertEqual(self.cfn("kms:CreateGrant", key, missing), "explicitDeny")
                for invalid in (False, "false"):
                    self.assertEqual(self.cfn("kms:CreateGrant", key, {**context, "kms:GrantIsForAWSResource": invalid}), "explicitDeny")
                self.assertEqual(self.cfn("kms:CreateGrant", key, {**context, "kms:GrantOperations": []}), "explicitDeny")
                for bad in ("CreateGrant", "Sign", "Verify", "GenerateDataKeyWithoutPlaintext"):
                    self.assertEqual(self.cfn("kms:CreateGrant", key, {**context, "kms:GrantOperations": list(context["kms:GrantOperations"]) + [bad]}), "explicitDeny")
                fields = ["kms:GrantConstraintType"]
                if key == self.R.LAMBDA_KEY:
                    fields.append("kms:GranteePrincipal")
                for field in fields:
                    self.assertEqual(self.cfn("kms:CreateGrant", key, {**context, field: "unrelated"}), "explicitDeny")
        for index in range(3):
            context = self.grant_context(self.R.LAMBDA_KEY, index)
            self.assertEqual(self.cfn("kms:CreateGrant", self.R.LAMBDA_KEY,
                                      {**context, "kms:GranteePrincipal": self.R.LAMBDA_GRANTEES[(index + 1) % 3]}), "explicitDeny")

    def test_service_principal_parameters_are_not_assumed_arn_condition_context(self):
        # CloudTrail service-string request parameters do not establish an ARN-
        # typed IAM condition key. The service-mediated grant is constrained by
        # ViaService, AWSResource, key, table/function, constraint type and ops.
        for entry in self.R.ceiling_kms_denies():
            if "kms:CreateGrant" not in values(entry.get("Action", [])):
                continue
            for clauses in entry.get("Condition", {}).values():
                self.assertNotIn("kms:RetiringPrincipal", clauses)
                if entry.get("Resource") == self.R.DDB_KEY:
                    self.assertNotIn("kms:GranteePrincipal", clauses)

    def test_exact_keys_region_account_function_service_and_table_scopes(self):
        cases = [("kms:Encrypt", self.R.LAMBDA_KEY, self.lambda_context(0, "lambda")),
                 ("kms:Decrypt", self.R.LAMBDA_KEY, self.lambda_context()),
                 ("kms:DescribeKey", self.R.DDB_KEY, self.common("dynamodb")),
                 ("kms:CreateGrant", self.R.DDB_KEY, self.grant_context(self.R.DDB_KEY))]
        for action, key, context in cases:
            for wrong_key in ("*", key + "-other", key.replace("us-east-2", "us-east-1"), key.replace(self.R.ACCOUNT, "195469705669")):
                with self.subTest(action=action, wrong_key=wrong_key):
                    self.assertEqual(self.cfn(action, wrong_key, context), "explicitDeny")
            for field in ("aws:RequestedRegion", "kms:CallerAccount"):
                self.assertEqual(self.cfn(action, key, {**context, field: "unrelated"}), "explicitDeny")
                self.assertEqual(self.cfn(action, key, {k: v for k, v in context.items() if k != field}), "explicitDeny")
        for field, wrong in (("kms:EncryptionContext:aws:lambda:FunctionArn", self.D.FUNCTIONS[3]),
                             ("kms:EncryptionContext:aws:lambda:FunctionArn", self.D.FUNCTIONS[0] + ":alias"),
                             ("kms:EncryptionContext:aws:lambda:FunctionArn", self.D.FUNCTIONS[0].replace("us-east-2", "us-east-1")),
                             ("kms:EncryptionContext:aws:lambda:FunctionArn", self.D.FUNCTIONS[0].replace(self.R.ACCOUNT, "195469705669"))):
            for action in ("kms:Encrypt", "kms:Decrypt"):
                self.assertEqual(self.cfn(action, self.R.LAMBDA_KEY, {**self.lambda_context(0, "lambda"), field: wrong}), "explicitDeny")
        context = self.grant_context(self.R.DDB_KEY)
        for field in ("kms:EncryptionContext:aws:dynamodb:tableName", "kms:EncryptionContext:aws:dynamodb:subscriberId"):
            self.assertEqual(self.cfn("kms:CreateGrant", self.R.DDB_KEY, {**context, field: "production"}), "explicitDeny")

    def test_unneeded_kms_crypto_cleanup_and_key_management_remain_denied(self):
        for key in (self.R.DDB_KEY, self.R.LAMBDA_KEY):
            for operation in ("GenerateDataKey", "GenerateDataKeyWithoutPlaintext", "ReEncryptFrom", "ReEncryptTo",
                              "RevokeGrant", "RetireGrant", "CreateKey", "PutKeyPolicy", "DisableKey", "ScheduleKeyDeletion",
                              "CreateAlias", "DeleteAlias", "ReplicateKey", "ImportKeyMaterial"):
                with self.subTest(key=key, operation=operation):
                    context = self.grant_context(key)
                    self.assertEqual(self.cfn("kms:" + operation, key, context), "explicitDeny")
                    self.assertEqual(self.deploy("kms:" + operation, key, context, True), "explicitDeny")

    def test_each_runtime_role_only_decrypts_its_own_lambda_context(self):
        for index in range(3):
            identity, boundary = self.runtime_documents(index)
            for service in (None, "lambda"):
                self.assertEqual(runtime_decision(identity, boundary, "kms:Decrypt", self.R.LAMBDA_KEY,
                                                  self.lambda_context(index, service)), "allowed")
            for other in range(3):
                if index == other:
                    continue
                self.assertEqual(runtime_decision(identity, boundary, "kms:Decrypt", self.R.LAMBDA_KEY,
                                                  self.lambda_context(other), [BROAD]), "explicitDeny")
            context = self.lambda_context(index)
            for field in context:
                self.assertEqual(runtime_decision(identity, boundary, "kms:Decrypt", self.R.LAMBDA_KEY,
                                                  {k: v for k, v in context.items() if k != field}, [BROAD]), "explicitDeny")
                self.assertEqual(runtime_decision(identity, boundary, "kms:Decrypt", self.R.LAMBDA_KEY,
                                                  {**context, field: "production"}, [BROAD]), "explicitDeny")
            for action in ("kms:Encrypt", "kms:CreateGrant", "kms:GenerateDataKey", "kms:RetireGrant", "kms:GetKeyPolicy"):
                self.assertEqual(runtime_decision(identity, boundary, action, self.R.LAMBDA_KEY, context, [BROAD]), "explicitDeny")
            self.assertEqual(runtime_decision(identity, boundary, "kms:Decrypt", self.R.LAMBDA_KEY + "-other", context, [BROAD]), "explicitDeny")

    def test_only_cases_and_calculations_decrypt_the_exact_dynamodb_table(self):
        context = self.ddb_context()
        for index in range(3):
            identity, boundary = self.runtime_documents(index)
            expected = "explicitDeny" if index == 0 else "allowed"
            self.assertEqual(runtime_decision(identity, boundary, "kms:Decrypt", self.R.DDB_KEY, context), expected)
            for field in context:
                for changed in ({k: v for k, v in context.items() if k != field}, {**context, field: "production"}):
                    self.assertEqual(runtime_decision(identity, boundary, "kms:Decrypt", self.R.DDB_KEY, changed, [BROAD]), "explicitDeny")
            for other in (self.R.DDB_KEY + "-other", self.R.DDB_KEY.replace("us-east-2", "us-east-1"),
                          self.R.DDB_KEY.replace(self.R.ACCOUNT, "195469705669")):
                self.assertEqual(runtime_decision(identity, boundary, "kms:Decrypt", other, context, [BROAD]), "explicitDeny")
            for action in ("kms:Encrypt", "kms:CreateGrant", "kms:GenerateDataKey", "kms:RevokeGrant", "kms:DescribeKey"):
                self.assertEqual(runtime_decision(identity, boundary, action, self.R.DDB_KEY, context, [BROAD]), "explicitDeny")

    def test_deployer_evidence_reads_and_function_verification_only(self):
        for key in (self.R.DDB_KEY, self.R.LAMBDA_KEY):
            for action in ("kms:DescribeKey", "kms:GetKeyPolicy", "kms:ListGrants"):
                self.assertEqual(self.deploy(action, key, self.common()), "allowed")
                for context in ({}, {"aws:RequestedRegion": "us-east-1"}):
                    self.assertEqual(self.deploy(action, key, context, True), "explicitDeny")
                self.assertEqual(self.deploy(action, key + "-unrelated", self.common(), True), "explicitDeny")
        for index in range(3):
            for service in (None, "lambda"):
                self.assertEqual(self.deploy("kms:Decrypt", self.R.LAMBDA_KEY, self.lambda_context(index, service)), "allowed")
        for context in (self.lambda_context(0), self.ddb_context()):
            self.assertEqual(self.deploy("kms:Decrypt", self.R.DDB_KEY, context, True), "explicitDeny")
        self.assertEqual(self.deploy("kms:Decrypt", self.R.LAMBDA_KEY,
                                     {**self.lambda_context(), "kms:EncryptionContext:aws:lambda:FunctionArn": self.D.FUNCTIONS[3]}, True), "explicitDeny")
        self.assertEqual(self.deploy("kms:Decrypt", self.R.LAMBDA_KEY, self.common(), True), "explicitDeny")
        for key in (self.R.DDB_KEY, self.R.LAMBDA_KEY):
            for action in ("kms:Encrypt", "kms:CreateGrant", "kms:ListAliases", "kms:EnableKeyRotation"):
                self.assertEqual(self.deploy(action, key, self.grant_context(key), True), "explicitDeny")

    def test_new_boundaries_can_be_read_but_never_versioned_or_deleted_by_deployer(self):
        for arn in TEST_BOUNDARY_ARNS:
            for action in ("iam:GetPolicy", "iam:GetPolicyVersion", "iam:ListPolicyVersions"):
                self.assertEqual(self.deploy(action, arn, {}), "allowed")
            for action in ("iam:CreatePolicyVersion", "iam:SetDefaultPolicyVersion", "iam:DeletePolicyVersion", "iam:DeletePolicy"):
                self.assertEqual(self.deploy(action, arn, {}, True), "explicitDeny")
        for arn in self.D.POLICIES + self.D.BOUNDARIES + self.D.OWNER_POLICIES:
            for action in ("iam:CreatePolicyVersion", "iam:SetDefaultPolicyVersion"):
                self.assertEqual(self.deploy(action, arn, {}), "allowed" if arn in self.D.EDITABLE else "explicitDeny")
            self.assertEqual(self.deploy("iam:DeletePolicyVersion", arn, {}, True), "explicitDeny")

    def test_all_non_kms_guardrails_and_existing_core_permissions_are_preserved(self):
        def normalized(statements):
            kept = []
            for entry in statements:
                if "kms:" in json.dumps(entry).lower():
                    entry = copy.deepcopy(entry)
                    for action_key in ("Action", "NotAction"):
                        if action_key in entry:
                            original = values(entry[action_key])
                            filtered = [action for action in original if not action.lower().startswith("kms:")]
                            if not filtered:
                                break
                            entry[action_key] = filtered if isinstance(entry[action_key], list) else filtered[0]
                    else:
                        kept.append(entry)
                        continue
                    if action_key in entry and not filtered:
                        continue
                else:
                    kept.append(copy.deepcopy(entry))
            return kept

        before = [s for doc in self.original_ceilings for s in doc["Statement"]]
        after = [s for doc in self.ceilings for s in doc["Statement"]]
        self.assertEqual(normalized(after), normalized(before))
        before_deployer = [s for doc in self.original_deployer for s in doc["Statement"]]
        after_deployer = copy.deepcopy([s for doc in self.deployer for s in doc["Statement"]])
        new_boundary_reads = [entry for entry in after_deployer if entry.get("Sid") == "ReadCoreKmsBoundaries"]
        self.assertEqual(len(new_boundary_reads), 1)
        self.assertEqual(new_boundary_reads[0], {"Sid": "ReadCoreKmsBoundaries", "Effect": "Allow",
                         "Action": ["iam:GetPolicy", "iam:GetPolicyVersion", "iam:ListPolicyVersions"],
                         "Resource": list(TEST_BOUNDARY_ARNS)})
        after_deployer.remove(new_boundary_reads[0])
        for entry in after_deployer:
            access_stack = DELEGATED.resolved({"Ref": "AWS::StackId"})
            if entry["Effect"] == "Allow" and entry.get("Resource") == access_stack:
                self.assertEqual(entry["Action"], ["cloudformation:DescribeStacks", "cloudformation:GetTemplate"])
                entry["Action"] = "cloudformation:DescribeStacks"
        self.assertEqual(normalized(after_deployer), normalized(before_deployer))
        for index in range(3):
            identity, boundary = self.runtime_documents(index)
            old = json.loads((HERE / "generated" / (self.D.STACK + "-" + self.D.SLUGS[index] + "-boundary.json")).read_text())
            self.assertEqual(normalized(boundary["Statement"]), old["Statement"])
            self.assertEqual(normalized(identity["Statement"]), [s for s in old["Statement"] if s["Effect"] == "Allow"])
        for case in TAGGING.CORE.core_request_cases():
            # IAM creation/mutation does not belong to the delegated core stack.
            if case["action"].startswith("iam:"):
                continue
            before_decision = decision(self.original_ceilings + list(self.source.values()), case["action"], case["resource"], case["context"])
            self.assertEqual(decision(self.ceilings + list(self.source.values()), case["action"], case["resource"], case["context"]), before_decision, case)

    def test_deployer_cannot_change_owner_safeguards_or_other_stacks(self):
        for role in (self.D.EXECUTOR, self.D.DEPLOYER, *self.D.ROLES, *self.D.ALIASES):
            for action in ("iam:CreateRole", "iam:UpdateAssumeRolePolicy", "iam:PutRolePolicy", "iam:PutRolePermissionsBoundary",
                           "iam:DeleteRolePermissionsBoundary", "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:DeleteRole"):
                self.assertEqual(self.cfn(action, role, self.common()), "explicitDeny")
                self.assertEqual(self.deploy(action, role, self.common(), True), "explicitDeny")
        for role in self.D.ROLES[:3]:
            self.assertEqual(self.cfn("iam:GetRole", role, {}), "allowed")
            self.assertEqual(self.cfn("iam:PassRole", role, {"iam:PassedToService": "lambda.amazonaws.com"}), "allowed")
            self.assertEqual(self.cfn("iam:PassRole", role, {"iam:PassedToService": "ec2.amazonaws.com"}), "explicitDeny")
        for stack in (self.D.STACK_ID.replace(self.D.STACK + "/", self.D.ACCESS_STACK + "/"),
                      self.D.STACK_ID.replace(self.D.STACK + "/", "production/")):
            for action in ("cloudformation:CreateChangeSet", "cloudformation:ExecuteChangeSet", "cloudformation:ContinueUpdateRollback"):
                self.assertEqual(self.deploy(action, stack, self.common(), True), "explicitDeny")
        self.assertEqual(self.cfn("apigateway:DELETE", self.D.API, self.common()), "explicitDeny")
        self.assertEqual(self.cfn("apigateway:PATCH", self.D.API.replace("l52iwors8c", "production"), self.common()), "explicitDeny")
        self.assertEqual(self.deploy("lambda:InvokeFunction", self.D.FUNCTIONS[0], self.common(), True), "explicitDeny")

    def test_policy_quotas_no_broad_kms_allow_and_input_immutability(self):
        untouched = copy.deepcopy(self.baseline)
        candidate = self.R.repair_template(self.baseline)
        self.assertEqual(self.baseline, untouched)
        self.assertEqual(candidate, self.candidate)
        for name, resource in candidate["Resources"].items():
            if resource["Type"] != "AWS::IAM::ManagedPolicy":
                continue
            document = resource["Properties"]["PolicyDocument"]
            self.assertLessEqual(self.R.expanded_policy_size(document), self.R.MAX_POLICY_SIZE, name)
            for statement in document["Statement"]:
                if statement["Effect"] == "Allow":
                    self.assertFalse(any(action.lower() == "kms:*" for action in values(statement.get("Action", []))))
        self.assertEqual(len(self.ceilings), 3)
        self.assertEqual(len(self.deployer), 4)
        # Console upload/TemplateURL supports a 1 MB template. If the compact
        # document exceeds 51,200 bytes it cannot use inline TemplateBody.
        self.assertLessEqual(self.D.compact_size(candidate), 1024 * 1024)

    def test_unreviewed_baseline_or_unknown_nested_resource_fields_fail_closed(self):
        for change in (lambda value: value["Resources"]["HealthFunctionRole"]["Properties"].update({"UnknownNestedField": {"Enabled": True}}),
                       lambda value: value["Resources"]["DeployerRole"]["Properties"]["AssumeRolePolicyDocument"]["Statement"][0].pop("Condition"),
                       lambda value: value["Resources"]["ExecutionCeiling1"]["Properties"]["PolicyDocument"]["Statement"].append(BROAD["Statement"][0]),
                       lambda value: value["Resources"].update({"UnexpectedKey": {"Type": "AWS::KMS::Key", "Properties": {}}})):
            tampered = copy.deepcopy(self.baseline)
            change(tampered)
            with self.subTest(tampered_type=list(tampered["Resources"])[-1]), self.assertRaises(ValueError):
                self.R.repair_template(tampered)
        for index in (3, 4, -1):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.R.runtime_boundary(index, {"Statement": []})

    def test_unreviewed_candidate_changes_cannot_pass_final_validator(self):
        for change in (lambda value: value["Resources"]["DeployerPolicy1"]["Properties"]["PolicyDocument"]["Statement"].append(BROAD["Statement"][0]),
                       lambda value: value["Resources"]["HealthFunctionRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"].append(BROAD["Statement"][0]),
                       lambda value: value["Resources"][BOUNDARY_IDS[0]].pop("DeletionPolicy"),
                       lambda value: value["Resources"][BOUNDARY_IDS[1]]["Properties"].update({"UnknownNestedField": {"Enabled": True}})):
            tampered = copy.deepcopy(self.candidate)
            change(tampered)
            with self.assertRaises(ValueError):
                self.R.validate_candidate(self.baseline, tampered)

    def test_policy_dependencies_install_guards_before_unlocking_actions(self):
        resources = self.candidate["Resources"]
        self.assertEqual(resources["ExecutionCeiling1"]["DependsOn"], ["ExecutionCeiling2", "ExecutionCeiling3"])
        self.assertEqual(resources["DeployerPolicy4"]["DependsOn"], ["DeployerPolicy3"])
        graph, forward = dependency_order(self.candidate)
        rollback = list(reversed(forward))
        for unlock, guards in (("ExecutionCeiling1", ["ExecutionCeiling2", "ExecutionCeiling3"]),
                               ("DeployerPolicy4", ["DeployerPolicy3"])):
            for guard in guards:
                self.assertIn(guard, graph[unlock])
                self.assertLess(forward.index(guard), forward.index(unlock))
                # Reversing the dependency order closes the action exceptions
                # before reverting their safeguards. IAM propagation remains
                # a separate post-update gate; a graph cannot simulate it.
                self.assertLess(rollback.index(unlock), rollback.index(guard))
        for prefix, unlock, guard_prefix in (("ExecutionCeiling", "ExecutionCeiling1", "CeilingKms"),
                                             ("DeployerPolicy", "DeployerPolicy4", "DeployerKms")):
            for logical, resource in resources.items():
                if not logical.startswith(prefix) or logical == unlock:
                    continue
                statements = resource["Properties"]["PolicyDocument"]["Statement"]
                if any(entry.get("Sid", "").startswith(guard_prefix) for entry in statements):
                    # Do not assume future packing keeps safeguards in the
                    # currently expected shard: every external guard shard
                    # must still precede the action-list exception update.
                    self.assertIn(logical, graph[unlock])
        for logical, boundary in zip(self.D.LOGICAL[:3], BOUNDARY_IDS):
            self.assertIn(boundary, graph[logical + "Role"])
            self.assertLess(forward.index(boundary), forward.index(logical + "Role"))
        for logical in ("ExecutionCeiling1", "DeployerPolicy4"):
            tampered = copy.deepcopy(self.candidate)
            tampered["Resources"][logical].pop("DependsOn")
            with self.assertRaises(ValueError):
                self.R.validate_candidate(self.baseline, tampered)


class KmsPostRepairVerificationTests(unittest.TestCase):
    policies = staticmethod(KmsRepairTests.policies)

    @classmethod
    def setUpClass(cls):
        KmsRepairTests.setUpClass.__func__(cls)
        spec = importlib.util.spec_from_file_location("post_repair_verification", HERE / "verify-kms-repair.py")
        cls.W = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.W)
        modules = {id(module): module for module in (cls.W.D, cls.W.K.D, cls.W.V.D)}
        for module in modules.values():
            source_patch = patch.object(module, "POLICY_SOURCE", cls.R.D.POLICY_SOURCE)
            source_patch.start()
            cls.addClassCleanup(source_patch.stop)

    def setUp(self):
        self.calls = []
        self.stack_id = self.R.ACCESS_STACK_ID
        self.app_id = "d1exampleonly"
        self.app_arn = f"arn:aws:amplify:{self.D.REGION}:{self.D.ACCOUNT}:apps/{self.app_id}"
        self.boundary_arns = dict(zip(BOUNDARY_IDS, TEST_BOUNDARY_ARNS))
        self.identity = {"Account": self.D.ACCOUNT,
                         "Arn": f"arn:aws:sts::{self.D.ACCOUNT}:assumed-role/{self.D.DEPLOYER_NAME}/synthetic-session",
                         "UserId": "SYNTHETICDEPLOYER:synthetic-session"}
        self.access = {"StackId": self.stack_id, "StackStatus": "UPDATE_COMPLETE", "Outputs": [
            {"OutputKey": "DeployerRoleArn", "OutputValue": self.D.DEPLOYER},
            {"OutputKey": "FrontendAppId", "OutputValue": self.app_id},
            {"OutputKey": "FrontendAppArn", "OutputValue": self.app_arn},
        ]}
        self.backend = {"StackId": self.D.STACK_ID, "StackStatus": "UPDATE_ROLLBACK_COMPLETE",
                        "RoleARN": self.D.EXECUTOR, "DisableRollback": False}
        self.template = copy.deepcopy(self.candidate)
        self.documents, self.roles, self.inline = {}, {}, {}
        self.versions, self.attachments = {}, {}
        self.inventory = []
        for logical, resource in self.template["Resources"].items():
            properties = resource["Properties"]
            if resource["Type"] == "AWS::IAM::ManagedPolicy":
                arn = self.boundary_arns.get(logical) or f"arn:aws:iam::{self.D.ACCOUNT}:policy/" + properties["ManagedPolicyName"]
                self.documents[arn] = self.resolve_live(properties["PolicyDocument"])
                self.versions[arn] = 2 if logical in self.W.CHANGED_OWNER_POLICIES else 1
                physical = arn
            elif resource["Type"] == "AWS::IAM::Role":
                name = properties["RoleName"]
                physical = name
                arn = self.D.DEPLOYER if logical == "DeployerRole" else self.D.ROLES[self.D.LOGICAL.index(logical.removesuffix("Role"))]
                role = {"Arn": arn, "RoleName": name, "RoleId": "SYNTHETICDEPLOYER" if logical == "DeployerRole" else "SYNTHETICRUNTIME",
                        "Path": properties.get("Path", "/"),
                        "AssumeRolePolicyDocument": copy.deepcopy(properties["AssumeRolePolicyDocument"]),
                        "MaxSessionDuration": properties.get("MaxSessionDuration", 3600)}
                if "PermissionsBoundary" in properties:
                    role["PermissionsBoundary"] = {"PermissionsBoundaryArn": self.resolve_live(properties["PermissionsBoundary"])}
                self.roles[name] = role
                self.inline[name] = {entry["PolicyName"]: copy.deepcopy(entry["PolicyDocument"]) for entry in properties.get("Policies", [])}
            else:
                physical = self.app_id
            self.inventory.append({"LogicalResourceId": logical, "ResourceType": resource["Type"],
                                   "PhysicalResourceId": physical, "ResourceStatus": "CREATE_COMPLETE"})
        self.roles[self.D.STACK + "-cfn"] = {"Arn": self.D.EXECUTOR, "RoleId": "SYNTHETICEXECUTION",
            "AssumeRolePolicyDocument": self.D.doc([{"Effect": "Allow", "Principal": {"Service": "cloudformation.amazonaws.com"}, "Action": "sts:AssumeRole"}])}
        self.inline[self.D.STACK + "-cfn"] = {}
        for arn, slug in zip(self.D.BOUNDARIES, self.D.SLUGS):
            self.documents[arn] = json.loads((HERE / "generated" / (self.D.STACK + "-" + slug + "-boundary.json")).read_text())
            self.versions[arn] = 1
        for arn, count in zip(self.D.POLICIES, (1, 1, 5, 2, 3)):
            name = arn.rsplit("-cfn-", 1)[1] + ".json"
            self.documents[arn] = copy.deepcopy(self.source[name])
            self.versions[arn] = count
        self.attachments[self.D.DEPLOYER_NAME] = [arn for arn in self.D.OWNER_POLICIES if "-deployer-" in arn]
        self.attachments[self.D.STACK + "-cfn"] = self.D.POLICIES + [arn for arn in self.D.OWNER_POLICIES if "-owner-ceiling-" in arn]
        self.evidence = {"access_stack_template": {"TemplateBody": copy.deepcopy(self.baseline)}, "keys": {}}
        for label, arn in (("dynamodb", self.R.DDB_KEY), ("lambda", self.R.LAMBDA_KEY)):
            self.evidence["keys"][label] = {"metadata": {"KeyMetadata": {
                "Arn": arn, "AWSAccountId": self.D.ACCOUNT, "KeyId": arn.rsplit("/", 1)[1],
                "KeyManager": "AWS", "KeyState": "Enabled", "Enabled": True,
                "KeySpec": "SYMMETRIC_DEFAULT", "KeyUsage": "ENCRYPT_DECRYPT", "Origin": "AWS_KMS", "MultiRegion": False}},
                "policy": {"Policy": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
                    "Principal": {"AWS": f"arn:aws:iam::{self.D.ACCOUNT}:root"}, "Action": ["kms:DescribeKey", "kms:GetKeyPolicy", "kms:ListGrants"], "Resource": "*"}]}},
                "grants": {"Grants": []}}
        self.live_keys = copy.deepcopy(self.evidence["keys"])
        self.api = {"ApiId": "l52iwors8c", "ProtocolType": "HTTP", "DisableExecuteApiEndpoint": True}

    def resolve_live(self, value):
        if isinstance(value, list):
            return [self.resolve_live(item) for item in value]
        if not isinstance(value, dict):
            return value
        if value == {"Ref": "AWS::StackId"}:
            return self.stack_id
        if value.get("Ref") in self.boundary_arns and set(value) == {"Ref"}:
            return self.boundary_arns[value["Ref"]]
        if value == {"Fn::GetAtt": ["FrontendApp", "Arn"]}:
            return self.app_arn
        if "Fn::Sub" in value:
            text, mapping = value["Fn::Sub"]
            for key, item in mapping.items():
                text = text.replace("${" + key + "}", self.resolve_live(item))
            return text
        return {key: self.resolve_live(item) for key, item in value.items()}

    def read(self, service, operation, *arguments):
        self.calls.append((service, operation, *arguments))
        args = dict(zip(arguments[::2], arguments[1::2]))
        if (service, operation) == ("sts", "get-caller-identity"):
            return copy.deepcopy(self.identity)
        if service == "cloudformation":
            owner = args.get("--stack-name") in (self.D.ACCESS_STACK, self.stack_id)
            if operation == "describe-stacks":
                return {"Stacks": [copy.deepcopy(self.access if owner else self.backend)]}
            if operation == "get-template":
                return {"TemplateBody": copy.deepcopy(self.template)}
            if operation == "list-stack-resources":
                return {"StackResourceSummaries": copy.deepcopy(self.inventory if owner else [
                    {"LogicalResourceId": "HttpApi", "ResourceType": "AWS::ApiGatewayV2::Api", "PhysicalResourceId": "l52iwors8c", "ResourceStatus": "CREATE_COMPLETE"}])}
        if service == "iam":
            arn, name = args.get("--policy-arn"), args.get("--role-name")
            if operation == "get-policy":
                return {"Policy": {"Arn": arn, "DefaultVersionId": "v" + str(self.versions[arn])}}
            if operation == "list-policy-versions":
                return {"Versions": [{"VersionId": "v" + str(version), "IsDefaultVersion": version == self.versions[arn]} for version in range(1, self.versions[arn] + 1)]}
            if operation == "get-policy-version":
                return {"PolicyVersion": {"Document": copy.deepcopy(self.documents[arn]),
                                          "VersionId": args["--version-id"], "IsDefaultVersion": True}}
            if operation == "get-role":
                return {"Role": copy.deepcopy(self.roles[name])}
            if operation == "get-role-policy":
                return {"PolicyDocument": copy.deepcopy(self.inline[name][args["--policy-name"]])}
            if operation == "list-role-policies":
                return {"PolicyNames": list(self.inline[name])}
            if operation == "list-attached-role-policies":
                return {"AttachedPolicies": [{"PolicyArn": policy} for policy in self.attachments.get(name, [])]}
        if service == "kms":
            key = next(value for value in self.live_keys.values() if value["metadata"]["KeyMetadata"]["Arn"] == args["--key-id"])
            if operation == "describe-key":
                return copy.deepcopy(key["metadata"])
            if operation == "get-key-policy":
                return {"Policy": json.dumps(key["policy"]["Policy"])}
            if operation == "list-grants":
                return copy.deepcopy(key["grants"])
        if service == "apigatewayv2":
            if operation == "get-api":
                return copy.deepcopy(self.api)
            if operation in ("get-routes", "get-stages"):
                return {"Items": []}
        raise AssertionError("Unexpected fake-AWS read: " + repr((service, operation, arguments)))

    def test_complete_post_repair_readback_uses_generated_boundary_arns(self):
        report = self.W.verify(self.read, self.candidate, self.evidence)
        self.assertTrue(report["status"].startswith("PASS"))
        self.assertEqual(report["AWS_mutations"], 0)
        allowed = self.W.V.READS | {("cloudformation", "get-template"), ("kms", "describe-key"),
                                    ("kms", "get-key-policy"), ("kms", "list-grants")}
        self.assertTrue(all(call[:2] in allowed for call in self.calls))
        for arn in TEST_BOUNDARY_ARNS:
            self.assertTrue(any(call[:2] == ("iam", "get-policy") and arn in call for call in self.calls))
        self.assertEqual(report.get("deployment_ready", False), False)

    def test_root_user_foreign_and_wrong_role_identity_stop_after_sts(self):
        for identity in ({"Account": self.D.ACCOUNT, "Arn": f"arn:aws:iam::{self.D.ACCOUNT}:root"},
                         {"Account": self.D.ACCOUNT, "Arn": self.D.DEVELOPER},
                         {"Account": "195469705669", "Arn": "arn:aws:sts::195469705669:assumed-role/production/session"},
                         {"Account": self.D.ACCOUNT, "Arn": f"arn:aws:sts::{self.D.ACCOUNT}:assumed-role/other/session"}):
            self.identity = identity
            self.calls = []
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                self.W.verify(self.read, self.candidate, self.evidence)
            self.assertEqual(self.calls, [("sts", "get-caller-identity")])

    def test_access_template_boundary_and_role_mismatches_fail_closed(self):
        scenarios = (
            lambda: self.template["Resources"]["DeployerRole"]["Properties"].update({"MaxSessionDuration": 7200}),
            lambda: self.roles[self.D.STACK + "-health-role"]["PermissionsBoundary"].update({"PermissionsBoundaryArn": self.D.BOUNDARIES[0]}),
            lambda: self.roles[self.D.STACK + "-health-role"]["PermissionsBoundary"].update({"PermissionsBoundaryArn": TEST_BOUNDARY_ARNS[0].replace(self.D.ACCOUNT, "195469705669")}),
            lambda: self.documents[TEST_BOUNDARY_ARNS[1]]["Statement"].append(BROAD["Statement"][0]),
            lambda: self.inline[self.D.STACK + "-calculations-role"]["OwnerFixedRuntime"]["Statement"].append(BROAD["Statement"][0]),
            lambda: self.roles[self.D.DEPLOYER_NAME]["AssumeRolePolicyDocument"]["Statement"][0].pop("Condition"),
            lambda: self.api.update({"DisableExecuteApiEndpoint": False}),
            lambda: self.access.update({"StackStatus": "UPDATE_IN_PROGRESS"}),
            lambda: self.backend.update({"StackStatus": "UPDATE_COMPLETE"}),
        )
        for index, mutate in enumerate(scenarios):
            self.setUp()
            mutate()
            with self.subTest(scenario=index), self.assertRaises(ValueError):
                self.W.verify(self.read, self.candidate, self.evidence)

    def test_changed_key_policy_or_key_state_is_detected_against_saved_evidence(self):
        for label in ("dynamodb", "lambda"):
            for mutation in (lambda key: key["metadata"]["KeyMetadata"].update({"Enabled": False, "KeyState": "Disabled"}),
                             lambda key: key["policy"]["Policy"]["Statement"].append({"Effect": "Deny", "Principal": {"AWS": "*"}, "Action": "kms:Decrypt", "Resource": "*"})):
                self.setUp()
                mutation(self.live_keys[label])
                with self.subTest(key=label), self.assertRaises(ValueError):
                    self.W.verify(self.read, self.candidate, self.evidence)

    def test_access_denied_is_propagated_without_retry_or_fallback(self):
        calls = []

        def denied(service, operation, *arguments):
            calls.append((service, operation))
            if service == "kms":
                raise self.W.V.AwsReadError(service, operation, "AccessDeniedException")
            return self.read(service, operation, *arguments)

        with self.assertRaises(self.W.V.AwsReadError):
            self.W.verify(denied, self.candidate, self.evidence)
        self.assertEqual(sum(service == "kms" for service, operation in calls), 1)

    def test_cli_root_profile_and_ambient_static_credentials_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config"
            for profile, login, environment in (
                ("actionbridge", f"arn:aws:iam::{self.D.ACCOUNT}:root", {}),
                ("actionbridge-staging-deployer", f"arn:aws:iam::{self.D.ACCOUNT}:root", {}),
                ("actionbridge-staging-deployer", self.D.DEVELOPER, {}),
                ("actionbridge-staging-deployer", self.D.DEPLOYER, {"AWS_ACCESS_KEY_ID": "synthetic-placeholder"}),
            ):
                config.write_text(f"[profile {profile}]\nlogin_session = {login}\n")
                with patch.dict(os.environ, {"AWS_CONFIG_FILE": str(config), **environment}, clear=True), \
                        patch.object(self.W.V.subprocess, "run") as run, self.assertRaises(ValueError):
                    self.W.ReadOnlyAws(profile)
                run.assert_not_called()

    def test_cli_writes_foreign_keys_and_endpoint_overrides_never_reach_aws(self):
        runner, base = Mock(), Mock()
        with patch.object(self.W.V, "validate_profile"):
            reader = self.W.ReadOnlyAws("actionbridge-staging-deployer", base_reader=base, runner=runner)
        forbidden = [
            ("iam", "create-policy-version", "--policy-arn", self.D.POLICIES[2]),
            ("cloudformation", "continue-update-rollback", "--stack-name", self.D.STACK),
            ("cloudformation", "execute-change-set", "--change-set-name", "synthetic"),
            ("kms", "decrypt", "--key-id", self.R.LAMBDA_KEY),
            ("kms", "describe-key", "--key-id", self.R.LAMBDA_KEY + "-foreign"),
            ("kms", "describe-key", "--key-id", self.R.LAMBDA_KEY, "--endpoint-url", "http://127.0.0.1"),
            ("kms", "describe-key", "--key-id", self.R.LAMBDA_KEY, "--profile", "root"),
            ("kms", "describe-key", "--key-id", self.R.LAMBDA_KEY, "--query", "KeyMetadata"),
            ("kms", "describe-key", "--key-id"),
            ("cloudformation", "get-template", "--stack-name", self.D.STACK_ID),
            ("cloudformation", "get-template", "--stack-name", self.R.ACCESS_STACK_ID),
            ("cloudformation", "get-template", "--stack-name", self.R.ACCESS_STACK_ID, "--template-stage", "Processed"),
            ("cloudformation", "get-template", "--stack-name", self.R.ACCESS_STACK_ID, "--template-stage", "Original", "--change-set-name", "unapproved"),
        ]
        for arguments in forbidden:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                reader(*arguments)
            runner.assert_not_called()
            base.assert_not_called()

    def test_cli_allowed_reads_keep_profile_region_and_one_attempt(self):
        result = self.W.subprocess.CompletedProcess([], 0, stdout='{"synthetic":"metadata"}', stderr="")
        runner, base = Mock(return_value=result), Mock(return_value={"synthetic": "identity"})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".staging").mkdir()
            with patch.object(self.W, "ROOT", root), patch.object(self.W.V, "validate_profile"):
                reader = self.W.ReadOnlyAws(base_reader=base, runner=runner)
                self.assertEqual(reader("kms", "describe-key", "--key-id", self.R.DDB_KEY), {"synthetic": "metadata"})
                command = runner.call_args.args[0]
                self.assertEqual(command[command.index("--profile") + 1], "actionbridge-staging-deployer")
                self.assertEqual(command[command.index("--region") + 1], "us-east-2")
                self.assertEqual(runner.call_args.kwargs["env"]["AWS_MAX_ATTEMPTS"], "1")
                self.assertEqual(runner.call_args.kwargs["env"]["AWS_IGNORE_CONFIGURED_ENDPOINT_URLS"], "true")
                self.assertEqual(reader("cloudformation", "get-template", "--stack-name", self.R.ACCESS_STACK_ID,
                                        "--template-stage", "Original"), {"synthetic": "metadata"})
                self.assertEqual(reader("sts", "get-caller-identity"), {"synthetic": "identity"})
                base.assert_called_once_with("sts", "get-caller-identity")
                runner.reset_mock()
                runner.return_value = self.W.subprocess.CompletedProcess([], 255, stdout="", stderr="An error occurred (AccessDeniedException)")
                with self.assertRaises(self.W.V.AwsReadError):
                    reader("kms", "describe-key", "--key-id", self.R.LAMBDA_KEY)
                self.assertEqual(runner.call_count, 1)

    def test_cli_requires_reviewed_candidate_digest_before_any_aws_or_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate, evidence, output = root / "candidate.json", root / "evidence.json", root / "output"
            candidate.write_text("{}")
            evidence.write_text("{}")
            arguments = ["verify-kms-repair.py", "--candidate", str(candidate), "--expected-key-evidence", str(evidence), "--output", str(output)]
            with patch("sys.argv", arguments), patch.object(self.W, "ReadOnlyAws") as aws, \
                    patch.object(self.W.argparse.ArgumentParser, "error", side_effect=ValueError("Missing required digest")) as parser_error:
                with self.assertRaisesRegex(ValueError, "Missing required digest"):
                    self.W.main()
                parser_error.assert_called_once()
                aws.assert_not_called()
            with patch("sys.argv", arguments + ["--candidate-sha256", "0" * 64]), patch.object(self.W, "ReadOnlyAws") as aws:
                with self.assertRaisesRegex(ValueError, "Approved candidate bytes changed"):
                    self.W.main()
                aws.assert_not_called()
            self.assertFalse(output.exists())

    def test_default_and_retained_versions_must_be_consistent(self):
        arn = self.D.OWNER_POLICIES[0]
        for rows in ([{"VersionId": "v2", "IsDefaultVersion": True}],
                     [{"VersionId": "v1", "IsDefaultVersion": True}, {"VersionId": "v2", "IsDefaultVersion": True}]):
            def changed(service, operation, *arguments):
                if operation == "list-policy-versions" and arn in arguments:
                    return {"Versions": rows}
                return self.read(service, operation, *arguments)
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.W.verify(changed, self.candidate, self.evidence)

    def test_key_policy_normalization_only_changes_service_array_order(self):
        policy = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {
            "Service": ["lambda.us-east-2.amazonaws.com", "lambda.amazonaws.com"]}, "Action": "kms:DescribeKey", "Resource": "*"}]}
        reordered = copy.deepcopy(policy)
        reordered["Statement"][0]["Principal"]["Service"].reverse()
        self.assertEqual(self.W.normalize_key_policy(policy), self.W.normalize_key_policy(reordered))
        for mutate in (lambda value: value["Statement"][0]["Principal"]["Service"].append("unrelated.amazonaws.com"),
                       lambda value: value["Statement"][0].update({"Action": "kms:*"})):
            changed = copy.deepcopy(policy)
            mutate(changed)
            self.assertNotEqual(self.W.normalize_key_policy(policy), self.W.normalize_key_policy(changed))

    def test_service_grant_retirement_is_accepted_but_new_or_changed_grants_stop(self):
        grant = {"GrantId": "synthetic-grant", "GranteePrincipal": self.R.LAMBDA_GRANTEES[0],
                 "Operations": ["Decrypt", "RetireGrant"], "CreationDate": "synthetic-old-time",
                 "Constraints": {"EncryptionContextEquals": {"aws:lambda:FunctionArn": self.R.CORE_FUNCTIONS[0]}}}
        actual = copy.deepcopy(grant)
        actual["Operations"].reverse()
        actual["CreationDate"] = "synthetic-new-presentation"
        self.assertEqual(self.W.verify_grants([actual], [grant])["new_or_changed_grants"], 0)
        self.assertEqual(self.W.verify_grants([], [grant])["previously_observed_grants_absent"], ["synthetic-grant"])
        for mutate in (lambda value: value.update({"GrantId": "unexpected-new-grant"}),
                       lambda value: value["Operations"].append("CreateGrant"),
                       lambda value: value["Constraints"]["EncryptionContextEquals"].update({"aws:lambda:FunctionArn": self.D.FUNCTIONS[3]})):
            changed = copy.deepcopy(grant)
            mutate(changed)
            with self.assertRaises(ValueError):
                self.W.verify_grants([changed], [grant])


if __name__ == "__main__":
    unittest.main()
