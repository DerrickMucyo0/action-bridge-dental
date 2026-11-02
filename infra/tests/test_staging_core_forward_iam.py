"""Blocked Stage candidate: pattern math is not IAM action recognition.

Committed tests use public templates and a public provider-contract fixture only;
owner exports and the downloaded full schema are verified separately by the CLI.
The bounded evaluator tests IAM precedence, not live AWS enforcement or action
recognition. The writer must reject the unsupported literal-action candidate.
"""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote

import yaml

import test_staging_api_recovery as RECOVERY
import test_staging_core_iam as CORE
from test_staging_role_lifecycle import decision


HERE = Path(__file__).resolve().parents[1] / "staging"
SPEC = importlib.util.spec_from_file_location("core_forward_stage_repair", HERE / "prepare-core-forward-repair.py")
REPAIR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPAIR)
OHIO = {"aws:RequestedRegion": REPAIR.REGION}
BROAD = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]}
PROVIDER_CONTRACT = {
    "typeName": "AWS::ApiGatewayV2::Stage",
    "handlers": {
        "create": {"permissions": ["apigateway:POST", "apigateway:TagResource"]},
        "update": {"permissions": ["apigateway:PATCH", "apigateway:POST", "apigateway:DELETE", "apigateway:TagResource", "apigateway:UntagResource"]},
        "read": {"permissions": ["apigateway:GET"]}, "list": {"permissions": ["apigateway:GET"]},
        "delete": {"permissions": ["apigateway:DELETE"]},
    },
    "tagging": {"permissions": ["apigateway:POST", "apigateway:TagResource", "apigateway:UntagResource"],
                "taggable": True, "tagOnCreate": True, "tagUpdatable": True, "cloudFormationSystemTags": True},
}
RECOGNIZED_HTTP_CATALOG = {"source": REPAIR.CATALOG_SOURCE, "raw_sha256": REPAIR.CATALOG_SHA256,
                           "recognized_actions": ["apigateway:" + verb for verb in ("GET", "POST", "PUT", "PATCH", "DELETE")]}


def recovery_a_baseline():
    result = RECOVERY.REPAIR.recovery_documents(CORE.current_reviewed_baseline())
    REPAIR.validate_original(result)
    return result


def resource_lifecycle_cases(template):
    """Expose reviewed request contexts for every exact core logical resource.

    These model configured features, not every optional action in a provider's
    union permission list. Separate metadata/getter paths remain unproven.
    """
    resources = template["Resources"]
    rows = []

    def add(logical, phase, action, resource, context=None, expected="allowed"):
        rows.append({"logical_id": logical, "resource_type": resources[logical]["Type"], "phase": phase,
                     "action": action, "resource": resource, "context": dict(OHIO if context is None else context), "expected": expected})

    def function_arn(logical):
        return f"arn:aws:lambda:{REPAIR.REGION}:{REPAIR.ACCOUNT}:function:" + resources[logical]["Properties"]["FunctionName"]

    for logical, item in resources.items():
        kind, props = item["Type"], item["Properties"]
        if kind == "AWS::IAM::Role":
            role = f"arn:aws:iam::{REPAIR.ACCOUNT}:role" + props["Path"] + props["RoleName"]
            alias = f"arn:aws:iam::{REPAIR.ACCOUNT}:role/" + props["RoleName"]
            bound = {"iam:PermissionsBoundary": props["PermissionsBoundary"]}
            add(logical, "precreate-read", "iam:GetRole", alias, {})
            add(logical, "create", "iam:CreateRole", role, bound)
            for action in ("iam:AttachRolePolicy", "iam:DetachRolePolicy"):
                for policy in props["ManagedPolicyArns"]:
                    add(logical, "create/rollback", action, role, {**bound, "iam:PolicyARN": policy})
                    if action == "iam:DetachRolePolicy":
                        add(logical, "missing-role-cleanup", action, alias, {"iam:PolicyARN": policy})
            for action in ("iam:GetRole", "iam:GetRolePolicy", "iam:ListAttachedRolePolicies", "iam:ListRolePolicies", "iam:ListRoleTags"):
                add(logical, "read", action, role, {})
            if props.get("Policies"):
                add(logical, "create/update", "iam:PutRolePolicy", role, bound)
                add(logical, "rollback", "iam:DeleteRolePolicy", role, {})
            for action in ("iam:TagRole", "iam:UntagRole"):
                add(logical, "tag", action, role, {})
            add(logical, "update-trust", "iam:UpdateAssumeRolePolicy", role, bound)
            add(logical, "rollback", "iam:DeleteRole", role, {})
        elif kind == "AWS::Lambda::Function":
            arn = function_arn(logical)
            for phase, actions in (("create", ["lambda:CreateFunction", "lambda:GetFunction"]),
                                   ("read", ["lambda:GetFunction", "lambda:GetFunctionConfiguration"]),
                                   ("update-configured-fields", ["lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration"]),
                                   ("tag", ["lambda:ListTags", "lambda:TagResource", "lambda:UntagResource"]),
                                   ("rollback", ["lambda:GetFunction", "lambda:DeleteFunction"])):
                for action in actions:
                    add(logical, phase, action, arn)
            role = resources[props["Role"]["Fn::GetAtt"][0]]["Properties"]
            add(logical, "create", "iam:PassRole", f"arn:aws:iam::{REPAIR.ACCOUNT}:role" + role["Path"] + role["RoleName"], {"iam:PassedToService": "lambda.amazonaws.com"})
            slug = props["FunctionName"].removeprefix(REPAIR.STACK + "-")
            add(logical, "artifact-read", "s3:GetObject", "arn:aws:s3:::" + props["Code"]["S3Bucket"] + f"/{REPAIR.STACK}/{slug}/" + "a" * 64 + ".zip", {"s3:ResourceAccount": REPAIR.ACCOUNT})
        elif kind == "AWS::Lambda::Permission":
            arn = function_arn(props["FunctionName"]["Ref"])
            principal = {**OHIO, "lambda:Principal": props["Principal"]}
            add(logical, "create", "lambda:AddPermission", arn, principal)
            add(logical, "read", "lambda:GetPolicy", arn)
            add(logical, "rollback", "lambda:RemovePermission", arn, principal)
        elif kind == "AWS::Logs::LogGroup":
            target = props["LogGroupName"]["Fn::Sub"].removeprefix("/aws/lambda/${").removesuffix("}")
            group = f"arn:aws:logs:{REPAIR.REGION}:{REPAIR.ACCOUNT}:log-group:/aws/lambda/" + resources[target]["Properties"]["FunctionName"]
            add(logical, "create/read/rollback", "logs:DescribeLogGroups", "*")
            for phase, action in (("create", "logs:CreateLogGroup"), ("create/update", "logs:PutRetentionPolicy"), ("update", "logs:DeleteRetentionPolicy"), ("rollback", "logs:DeleteLogGroup")):
                add(logical, phase, action, group + ":*")
            for action in ("logs:ListTagsForResource", "logs:TagResource", "logs:UntagResource"):
                add(logical, "tag/read", action, group)
        elif kind == "AWS::DynamoDB::Table":
            arn = f"arn:aws:dynamodb:{REPAIR.REGION}:{REPAIR.ACCOUNT}:table/" + props["TableName"]
            for phase, actions in (("create", ["dynamodb:CreateTable", "dynamodb:DescribeTable", "dynamodb:UpdateTimeToLive"]),
                                   ("read", ["dynamodb:DescribeTable", "dynamodb:DescribeTimeToLive", "dynamodb:ListTagsOfResource"]),
                                   ("update-configured-fields", ["dynamodb:UpdateTable", "dynamodb:UpdateTimeToLive"]),
                                   ("tag-capability", ["dynamodb:TagResource", "dynamodb:UntagResource"]),
                                   ("rollback", ["dynamodb:DeleteTable", "dynamodb:DescribeTable"])):
                for action in actions:
                    add(logical, phase, action, arn)
        elif kind == "AWS::ApiGatewayV2::Api":
            for phase, action, arn in (("read", "apigateway:GET", REPAIR.API), ("update", "apigateway:PATCH", REPAIR.API),
                                       ("rollback-CORS", "apigateway:DELETE", REPAIR.API + "/cors")):
                add(logical, phase, action, arn)
            add(logical, "preservation-guard", "apigateway:DELETE", REPAIR.API, expected="explicitDeny")
        elif kind in ("AWS::ApiGatewayV2::Authorizer", "AWS::ApiGatewayV2::Integration", "AWS::ApiGatewayV2::Route"):
            child = {"AWS::ApiGatewayV2::Authorizer": "authorizers", "AWS::ApiGatewayV2::Integration": "integrations", "AWS::ApiGatewayV2::Route": "routes"}[kind]
            collection = REPAIR.API + "/" + child
            arn = collection + "/reviewed-child-id"
            add(logical, "create", "apigateway:POST", collection)
            for phase, action in (("read", "apigateway:GET"), ("update", "apigateway:PATCH"), ("update", "apigateway:PUT"), ("rollback", "apigateway:DELETE")):
                add(logical, phase, action, arn)
        elif kind == "AWS::ApiGatewayV2::Stage":
            # Fourteen concrete lifecycle contexts, including provider-required
            # literal actions and the observed create collection ARN.
            for phase, action, arn in (
                ("create", "apigateway:POST", REPAIR.STAGES), ("create-SAR-alternative", "apigateway:PUT", REPAIR.STAGES),
                ("create-tag-on-create", "apigateway:TagResource", REPAIR.STAGES),
                ("read", "apigateway:GET", REPAIR.STAGE), ("list", "apigateway:GET", REPAIR.STAGES),
                ("update", "apigateway:PATCH", REPAIR.STAGE), ("update", "apigateway:POST", REPAIR.STAGE),
                ("update", "apigateway:DELETE", REPAIR.STAGE), ("update", "apigateway:TagResource", REPAIR.STAGE),
                ("update", "apigateway:UntagResource", REPAIR.STAGE),
                ("tag", "apigateway:TagResource", REPAIR.STAGES), ("tag", "apigateway:TagResource", REPAIR.STAGE),
                ("tag", "apigateway:UntagResource", REPAIR.STAGE), ("rollback", "apigateway:DELETE", REPAIR.STAGE)):
                add(logical, phase, action, arn)
        else:
            raise ValueError("Unreviewed core resource type: " + kind)
    if {row["logical_id"] for row in rows} != set(resources):
        raise ValueError("At least one core resource lacks lifecycle coverage.")
    return rows


class CoreForwardIAMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = recovery_a_baseline()
        cls.proposed = REPAIR.repair_documents(cls.original)
        cls.template = yaml.safe_load((HERE / "generated/core.yaml").read_text())

    def test_exactly_identity_03_changes_by_four_bounded_statements(self):
        self.assertEqual({name for name in REPAIR.FILES if self.original[name] != self.proposed[name]}, {REPAIR.CHANGED})
        self.assertEqual(self.proposed[REPAIR.CHANGED]["Statement"][:10], self.original[REPAIR.CHANGED]["Statement"])
        self.assertEqual(self.proposed[REPAIR.CHANGED]["Statement"][10:], REPAIR.tagging_statements())
        self.assertEqual(len(self.proposed[REPAIR.CHANGED]["Statement"]), 14)
        for doc in self.proposed.values():
            self.assertLessEqual(REPAIR.compact_size(doc), 6144)

    def test_candidate_pattern_math_covers_44_resources_but_is_not_recognition_validation(self):
        rows = resource_lifecycle_cases(self.template)
        self.assertEqual(len({row["logical_id"] for row in rows}), 44)
        self.assertEqual(len([row for row in rows if row["logical_id"] == "HttpApiStage"]), 14)
        for row in rows:
            with self.subTest(logical=row["logical_id"], phase=row["phase"], action=row["action"]):
                self.assertEqual(decision(list(self.proposed.values()), row["action"], row["resource"], row["context"]), row["expected"])

    def test_local_pattern_allow_does_not_establish_action_recognition(self):
        self.assertEqual(decision(list(self.original.values()), "apigateway:TagResource", REPAIR.STAGES, OHIO), "implicitDeny")
        self.assertEqual(decision(list(self.proposed.values()), "apigateway:TagResource", REPAIR.STAGES, OHIO), "allowed")
        self.assertTrue(self.template["Resources"]["HttpApiStage"]["Properties"]["Tags"])
        REPAIR.validate_provider_document(PROVIDER_CONTRACT)
        self.assertIn("apigateway:TagResource", PROVIDER_CONTRACT["handlers"]["create"]["permissions"])
        # The pattern matcher accepts arbitrary labels. The independent IAM
        # recognition gate must reject this result despite provider metadata.
        with self.assertRaisesRegex(ValueError, "unrecognized API Gateway IAM actions"):
            REPAIR.validate_action_recognition(self.proposed[REPAIR.CHANGED], RECOGNIZED_HTTP_CATALOG)

    def test_unrelated_api_stage_region_and_nested_resources_stay_explicitly_denied(self):
        wrong = [REPAIR.API, REPAIR.API + "/stages/production", REPAIR.STAGE + "/routesettings",
                 REPAIR.STAGE.replace(REPAIR.API_ID, "z9y8x7w6v5"), REPAIR.STAGES.replace("us-east-2", "us-east-1"), "*"]
        for action, approved in (("apigateway:TagResource", [REPAIR.STAGES, REPAIR.STAGE]), ("apigateway:UntagResource", [REPAIR.STAGE])):
            targets = wrong + ([REPAIR.STAGES] if action.endswith("UntagResource") else [])
            for target in targets:
                self.assertEqual(decision(list(self.proposed.values()) + [BROAD], action, target, OHIO), "explicitDeny")
            for target in approved:
                self.assertEqual(decision(list(self.proposed.values()), action, target, OHIO), "allowed")
                for context in ({}, {"aws:RequestedRegion": "us-east-1"}):
                    self.assertEqual(decision(list(self.proposed.values()) + [BROAD], action, target, context), "explicitDeny")

    def test_http_cors_api_delete_role_boundaries_and_mapping_controls_are_preserved(self):
        docs = list(self.proposed.values())
        for row in CORE.core_request_cases():
            before = decision(list(self.original.values()), row["action"], row["resource"], row["context"])
            self.assertEqual(decision(docs, row["action"], row["resource"], row["context"]), before)
        self.assertEqual(decision(docs + [BROAD], "apigateway:DELETE", REPAIR.API, OHIO), "explicitDeny")
        self.assertEqual(decision(docs, "apigateway:DELETE", REPAIR.API + "/cors", OHIO), "allowed")
        for name in REPAIR.FILES:
            for marker in ("iam:", "EventSourceMapping"):
                self.assertEqual([s for s in self.original[name]["Statement"] if marker in json.dumps(s)],
                                 [s for s in self.proposed[name]["Statement"] if marker in json.dumps(s)])

    def test_provider_contract_pin_and_required_literal_permissions_fail_closed_on_drift(self):
        self.assertEqual(REPAIR.STAGE_SCHEMA_SHA256, "d257a8bc9dbb7e6c47f3396fc4021a60b5cb9cf7920117a3187d1f8f6c2b30e8")
        broken = copy.deepcopy(PROVIDER_CONTRACT)
        broken["handlers"]["create"]["permissions"].remove("apigateway:TagResource")
        with self.assertRaises(ValueError):
            REPAIR.validate_provider_document(broken)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            (base / "aws-apigatewayv2-stage.json").write_text(json.dumps(PROVIDER_CONTRACT))
            with self.assertRaises(ValueError):
                REPAIR.load_provider_schema(base)

    def test_json_loader_rejects_duplicate_keys_and_non_json_constants(self):
        self.assertEqual(REPAIR.decode_json('{"Version":"2012-10-17","Statement":[]}'),
                         {"Version": "2012-10-17", "Statement": []})
        for raw in ('{"Statement":[],"Statement":[]}', '{"Statement":[{"Effect":"Allow","Effect":"Deny"}]}',
                    '{"number":NaN}', '{"number":Infinity}', '{"number":-Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                REPAIR.decode_json(raw)

    def test_duplicate_keys_in_source_saved_export_and_provider_fail_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            source, live = self.fixture(base)
            path = source / REPAIR.CHANGED
            original = path.read_text()
            path.write_text(original[:-1] + ',"Statement":[] }')
            with self.assertRaises(ValueError):
                REPAIR.write_repair(source, live, base / "provider", base / "output")
            self.assertFalse((base / "output").exists())
            path.write_text(original)
            saved = live / REPAIR.SAVED_EXPORTS[REPAIR.CHANGED]
            saved.write_text('{"Statement":[],"Statement":[]}')
            with self.assertRaises(ValueError):
                REPAIR.write_repair(source, live, base / "provider", base / "output")
            self.assertFalse((base / "output").exists())
            provider = base / "provider"
            provider.mkdir()
            raw = b'{"typeName":"AWS::ApiGatewayV2::Stage","typeName":"AWS::ApiGatewayV2::Stage"}'
            (provider / "aws-apigatewayv2-stage.json").write_bytes(raw)
            # Match the test fixture hash to exercise decoding after the pin.
            with patch.object(REPAIR, "STAGE_SCHEMA_SHA256", hashlib.sha256(raw).hexdigest()):
                with self.assertRaises(ValueError):
                    REPAIR.load_provider_schema(provider)

    def fixture(self, base):
        source, live = base / "source", base / "saved"
        source.mkdir(); live.mkdir()
        for name, doc in self.original.items():
            (source / name).write_text(json.dumps(doc, indent=3))
            if name in REPAIR.SAVED_EXPORTS:
                (live / REPAIR.SAVED_EXPORTS[name]).write_text(json.dumps(doc, separators=(",", ":")))
        return source, live

    def test_writer_refuses_application_format_output_for_unrecognized_literal_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            source, live = self.fixture(base)
            before = {p.name: p.read_bytes() for p in source.iterdir()}
            provider = {"raw_sha256": REPAIR.STAGE_SCHEMA_SHA256, "source": REPAIR.SCHEMA_SOURCE,
                        "handlers": PROVIDER_CONTRACT["handlers"], "tagging": PROVIDER_CONTRACT["tagging"]}
            with patch.object(REPAIR, "load_provider_schema", return_value=provider), \
                    patch.object(REPAIR, "load_authorization_catalog", return_value=RECOGNIZED_HTTP_CATALOG):
                with self.assertRaisesRegex(ValueError, "unrecognized API Gateway IAM actions"):
                    REPAIR.write_repair(source, live, base / "public-provider-fixture", base / "output", base / "public-catalog-fixture")
                self.assertFalse((base / "output").exists())
                # Existing directories are also refused without any overwrite.
                (base / "output").mkdir()
                (base / "output/canary").write_text("unchanged")
                with self.assertRaises(ValueError):
                    REPAIR.write_repair(source, live, base / "public-provider-fixture", base / "output")
                self.assertEqual((base / "output/canary").read_text(), "unchanged")
            self.assertEqual({p.name: p.read_bytes() for p in source.iterdir()}, before)

    def test_recognized_http_tag_allow_is_still_denied_by_original_two_policy_guards(self):
        tags = f"arn:aws:apigateway:{REPAIR.REGION}::/tags/" + quote(REPAIR.STAGE, safe="")
        allow = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
                 "Action": RECOGNIZED_HTTP_CATALOG["recognized_actions"], "Resource": tags,
                 "Condition": {"StringEquals": OHIO}}]}
        REPAIR.validate_action_recognition(allow, RECOGNIZED_HTTP_CATALOG)
        for action in RECOGNIZED_HTTP_CATALOG["recognized_actions"]:
            # All ten current identity statements and the current guardrails
            # remain present: an additional exact Allow cannot override either.
            self.assertEqual(decision(list(self.original.values()) + [allow], action, tags, OHIO), "explicitDeny")

        guard_exception_only = copy.deepcopy(self.original)
        guard_exception_only["guardrails-02.json"]["Statement"][7]["NotResource"].append(tags)
        self.assertEqual(decision(list(guard_exception_only.values()) + [allow], "apigateway:POST", tags, OHIO), "allowed")
        self.assertEqual(decision(list(guard_exception_only.values()) + [allow], "apigateway:DELETE", tags, OHIO), "explicitDeny")
        # A narrowly bounded Tags exception in the original DELETE guard is
        # also necessary. That changes original Statement 9, contradicting an
        # instruction to preserve all original ten statements unchanged.
        required_second_edit = copy.deepcopy(guard_exception_only)
        required_second_edit["identity-03.json"]["Statement"][9]["NotResource"].append(tags)
        self.assertNotEqual(required_second_edit["identity-03.json"]["Statement"][:10], self.original["identity-03.json"]["Statement"][:10])
        self.assertEqual(decision(list(required_second_edit.values()) + [allow], "apigateway:DELETE", tags, OHIO), "allowed")
        self.assertEqual(decision(list(required_second_edit.values()) + [allow, BROAD], "apigateway:DELETE", REPAIR.API, OHIO), "explicitDeny")

    def test_action_catalog_pin_and_strict_decoding_fail_closed(self):
        self.assertEqual(REPAIR.CATALOG_SHA256, "a89cf68f8f0c509b726695174f57fa61be969d00320aea4bb35f441e713a5c7b")
        REPAIR.validate_action_recognition(self.original[REPAIR.CHANGED], RECOGNIZED_HTTP_CATALOG)
        for action in ("apigateway:TagResource", "apigateway:UntagResource"):
            for key in ("Action", "NotAction"):
                with self.assertRaisesRegex(ValueError, "unrecognized API Gateway IAM actions"):
                    REPAIR.validate_action_recognition({"Statement": [{key: action}]}, RECOGNIZED_HTTP_CATALOG)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "public-catalog.json"
            raw = b'{"Name":"apigateway","Name":"apigateway","Actions":[]}'
            path.write_bytes(raw)
            with self.assertRaises(ValueError):
                REPAIR.load_authorization_catalog(path)
            with patch.object(REPAIR, "CATALOG_SHA256", hashlib.sha256(raw).hexdigest()):
                with self.assertRaisesRegex(ValueError, "Duplicate JSON"):
                    REPAIR.load_authorization_catalog(path)

    def test_any_policy_or_saved_export_drift_is_rejected(self):
        for name in REPAIR.FILES:
            changed = copy.deepcopy(self.original)
            changed[name]["Statement"].append(BROAD["Statement"][0])
            with self.subTest(policy=name), self.assertRaises(ValueError):
                REPAIR.repair_documents(changed)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            source, live = self.fixture(base)
            (live / REPAIR.SAVED_EXPORTS[REPAIR.CHANGED]).write_text(json.dumps(BROAD))
            with self.assertRaises(ValueError):
                REPAIR.write_repair(source, live, base / "provider", base / "output")
            self.assertFalse((base / "output").exists())

    def test_helper_imports_no_aws_network_or_process_execution_modules(self):
        tree = ast.parse((HERE / "prepare-core-forward-repair.py").read_text())
        imports = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imports |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertFalse(imports & {"boto3", "botocore", "subprocess", "socket", "urllib.request", "requests"})


if __name__ == "__main__":
    unittest.main()
