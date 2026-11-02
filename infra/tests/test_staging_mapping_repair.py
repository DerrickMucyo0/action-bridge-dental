"""Evaluate the exact policy parts for observed mapping rollback request shapes.

The local evaluator is deliberately bounded, not a live AWS IAM simulation.
Missing FunctionArn must continue to deny; a Resource '*' error alone does not
prove which function context AWS actually supplied.
"""
import ast
import copy
from fnmatch import fnmatchcase
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import test_staging_execution_repair as ROLE_REPAIR
from test_staging_role_lifecycle import decision


HERE = Path(__file__).resolve().parents[1] / "staging"
SPEC = importlib.util.spec_from_file_location("mapping_repair_proposal", HERE / "prepare-mapping-repair.py")
REPAIR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPAIR)
MAPPING_ID = "35d44f01-0d10-4bae-9a76-60cd087e6d5e"
MAPPING = REPAIR.MAPPING.replace("*", MAPPING_ID)
REGION = {"aws:RequestedRegion": REPAIR.REGION}
WORKER_CONTEXT = {**REGION, "lambda:FunctionArn": REPAIR.WORKER}
ACTIONS = ("lambda:GetEventSourceMapping", "lambda:DeleteEventSourceMapping")
BROAD = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]}


def baseline():
    return ROLE_REPAIR.REPAIR.repair_documents(ROLE_REPAIR.legacy_bundle())


class MappingRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = baseline()
        cls.repaired = REPAIR.repair_documents(cls.original)
        cls.docs = list(cls.repaired.values())

    def test_original_resource_isolation_deny_reproduces_observed_request(self):
        for action in ACTIONS:
            self.assertEqual(decision(list(self.original.values()) + [BROAD], action, "*", WORKER_CONTEXT), "explicitDeny")

    def test_create_stays_limited_to_exact_worker_and_ohio(self):
        action = "lambda:CreateEventSourceMapping"
        self.assertEqual(decision(self.docs, action, "*", WORKER_CONTEXT), "allowed")
        for context in ({}, REGION,
                        {**WORKER_CONTEXT, "aws:RequestedRegion": "us-east-1"},
                        {**WORKER_CONTEXT, "lambda:FunctionArn": REPAIR.WORKER.replace("staging", "production")},
                        {**WORKER_CONTEXT, "lambda:FunctionArn": REPAIR.WORKER + "-other"}):
            self.assertEqual(decision(self.docs + [BROAD], action, "*", context), "explicitDeny")

    def test_both_policy_changes_are_needed_for_the_known_worker_wildcard_shape(self):
        # An Allow cannot override the old ARN-based explicit Deny. Conversely,
        # correcting that Deny alone leaves no applicable Allow for Resource '*'.
        identity_only = copy.deepcopy(self.original)
        identity_only["identity-02.json"] = self.repaired["identity-02.json"]
        guard_only = copy.deepcopy(self.original)
        guard_only["guardrails-02.json"] = self.repaired["guardrails-02.json"]
        for action in ACTIONS:
            self.assertEqual(decision(list(identity_only.values()), action, "*", WORKER_CONTEXT), "explicitDeny")
            self.assertEqual(decision(list(guard_only.values()), action, "*", WORKER_CONTEXT), "implicitDeny")
            self.assertEqual(decision(self.docs, action, "*", WORKER_CONTEXT), "allowed")

    def test_null_request_parameters_is_not_used_as_iam_context_evidence(self):
        # CloudTrail's null requestParameters is not an IAM condition map. Both
        # request shapes remain possible; the proposal safely distinguishes them.
        for action in ACTIONS:
            self.assertEqual(decision(self.docs, action, "*", WORKER_CONTEXT), "allowed")
            self.assertEqual(decision(self.docs, action, "*", REGION), "explicitDeny")

    def test_missing_known_and_unrelated_uuid_cannot_get_an_unscoped_cleanup_fallback(self):
        # UUID is an API path parameter, not a documented Lambda IAM condition
        # key. If AWS exposes only Resource '*' and no FunctionArn, these two
        # distinct API targets have the same available authorization inputs.
        # A known UUID in a local log cannot safely distinguish that request.
        missing_targets = (MAPPING_ID, "00000000-0000-4000-8000-000000000001")
        for action in ACTIONS:
            outcomes = {uuid: decision(self.docs + [BROAD], action, "*", dict(REGION))
                        for uuid in missing_targets}
            self.assertEqual(set(outcomes.values()), {"explicitDeny"})
        # No new wildcard write fallback may bypass the exact supported worker
        # condition, including under an unrelated permissive identity policy.
        cleanup_allows = [statement for doc in self.docs for statement in doc["Statement"]
                          if statement["Effect"] == "Allow"
                          and any(fnmatchcase("lambda:deleteeventsourcemapping", pattern.lower())
                                  for pattern in ([statement["Action"]] if isinstance(statement.get("Action"), str)
                                                  else statement.get("Action", [])))]
        self.assertTrue(cleanup_allows)
        for statement in cleanup_allows:
            self.assertEqual(statement["Condition"]["ArnEquals"]["lambda:FunctionArn"], REPAIR.WORKER)
            self.assertEqual(statement["Condition"]["StringEquals"]["aws:RequestedRegion"], REPAIR.REGION)
            self.assertNotIn("ArnEqualsIfExists", statement["Condition"])

    def test_cleanup_resource_wildcard_requires_exact_worker_and_ohio(self):
        for action in ACTIONS:
            for resource in ("*", MAPPING):
                with self.subTest(action=action, resource=resource):
                    self.assertEqual(decision(self.docs, action, resource, WORKER_CONTEXT), "allowed")
                    for context in ({}, REGION, {**WORKER_CONTEXT, "aws:RequestedRegion": "us-east-1"},
                                    {**WORKER_CONTEXT, "lambda:FunctionArn": REPAIR.WORKER.replace("staging", "production")},
                                    {**WORKER_CONTEXT, "lambda:FunctionArn": REPAIR.WORKER.replace("631367363628", "195469705669")},
                                    {**WORKER_CONTEXT, "lambda:FunctionArn": REPAIR.WORKER + ":production"}):
                        self.assertEqual(decision(self.docs + [BROAD], action, resource, context), "explicitDeny", context)

    def test_missing_context_remains_explicit_denied_not_assumed_to_be_missing_resource(self):
        for action in ACTIONS:
            self.assertEqual(decision(self.docs, action, "*", REGION), "explicitDeny")
            self.assertEqual(decision(self.docs, action, MAPPING, REGION), "explicitDeny")

    def test_update_retains_mapping_arn_guard_and_optional_uuid_narrowing(self):
        update = "lambda:UpdateEventSourceMapping"
        self.assertEqual(decision(self.docs, update, MAPPING, WORKER_CONTEXT), "allowed")
        self.assertEqual(decision(self.docs + [BROAD], update, "*", WORKER_CONTEXT), "explicitDeny")
        self.assertEqual(decision(self.docs + [BROAD], update, MAPPING.replace("us-east-2", "us-east-1"), WORKER_CONTEXT), "explicitDeny")
        generated = [ROLE_REPAIR.EXECUTION.backend_policy(REPAIR.API, MAPPING_ID),
                     ROLE_REPAIR.EXECUTION.guardrail_policy(REPAIR.API, MAPPING_ID)]
        self.assertEqual(decision(generated, update, MAPPING, WORKER_CONTEXT), "allowed")
        self.assertEqual(decision(generated + [BROAD], update, MAPPING.replace(MAPPING_ID, "00000000-0000-4000-8000-000000000001"), WORKER_CONTEXT), "explicitDeny")

    def test_generator_and_exact_owner_replacements_agree_on_mapping_decisions(self):
        generated = [ROLE_REPAIR.EXECUTION.backend_policy(REPAIR.API), ROLE_REPAIR.EXECUTION.guardrail_policy(REPAIR.API)]
        for action in (*ACTIONS, "lambda:CreateEventSourceMapping", "lambda:UpdateEventSourceMapping"):
            for resource in ("*", MAPPING):
                for context in ({}, REGION, WORKER_CONTEXT, {**WORKER_CONTEXT, "lambda:FunctionArn": REPAIR.WORKER + "-other"}):
                    self.assertEqual(decision(generated, action, resource, context), decision(self.docs, action, resource, context))

    def test_exactly_two_fields_change_and_all_iam_boundary_guards_survive(self):
        expected = copy.deepcopy(self.original)
        expected["identity-02.json"]["Statement"][4]["Resource"] = "*"
        expected["guardrails-02.json"]["Statement"][9]["Action"] = ["lambda:UpdateEventSourceMapping"]
        self.assertEqual(self.repaired, expected)
        self.assertEqual(baseline(), self.original)
        for name in REPAIR.UNCHANGED:
            self.assertEqual(self.repaired[name], self.original[name])
        for name in REPAIR.FILES:
            self.assertLessEqual(REPAIR.compact_size(self.repaired[name]), 6144)
        for action, resource in (("iam:DeleteRolePermissionsBoundary", ROLE_REPAIR.ROLES[0]),
                                 ("iam:CreatePolicyVersion", "arn:aws:iam::631367363628:policy/example"),
                                 ("lambda:DeleteFunction", REPAIR.WORKER.replace("staging", "production")),
                                 ("apigateway:DELETE", "arn:aws:apigateway:us-east-2::/apis/production")):
            self.assertEqual(decision(self.docs + [BROAD], action, resource, REGION), "explicitDeny")

    def test_drift_in_any_baseline_document_fails_closed(self):
        for name in REPAIR.FILES:
            altered = copy.deepcopy(self.original)
            altered[name]["Statement"].append(BROAD["Statement"][0])
            with self.subTest(name=name), self.assertRaises(ValueError):
                REPAIR.repair_documents(altered)

    def test_exclusive_output_and_patches_preserve_original_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            source, target = base / "source", base / "output"
            source.mkdir()
            for name, document in self.original.items():
                (source / name).write_text(json.dumps(document, indent=3))
            before = {p.name: p.read_bytes() for p in source.iterdir()}
            review = REPAIR.write_repair(source, target)
            self.assertEqual(review["aws_calls"], 0)
            self.assertFalse(review["live_source_documents_verified"])
            self.assertEqual({p.name: p.read_bytes() for p in source.iterdir()}, before)
            for name in REPAIR.UNCHANGED:
                self.assertEqual((target / name).read_bytes(), before[name])
            changes = json.loads((target / "changes.json").read_text())["patches"]
            for name, operations in changes.items():
                actual = copy.deepcopy(self.original[name])
                for op in operations:
                    parts = op["path"].split("/")[1:]
                    parent = actual
                    for part in parts[:-1]:
                        parent = parent[int(part)] if isinstance(parent, list) else parent[part]
                    self.assertEqual(parent[parts[-1]], op["old_value"])
                    parent[parts[-1]] = op["value"]
                self.assertEqual(actual, json.loads((target / name).read_text()))
            written = {p.name: p.read_bytes() for p in target.iterdir()}
            with self.assertRaises((ValueError, FileExistsError)):
                REPAIR.write_repair(source, target)
            self.assertEqual({p.name: p.read_bytes() for p in target.iterdir()}, written)

    def test_helper_has_no_network_aws_or_private_parameter_dependencies(self):
        tree = ast.parse((HERE / "prepare-mapping-repair.py").read_text())
        imports = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imports |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertFalse(imports & {"subprocess", "boto3", "botocore", "socket", "urllib", "requests"})


if __name__ == "__main__":
    unittest.main()
