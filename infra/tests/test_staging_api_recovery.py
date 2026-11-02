"""Pinned API rollback repair; neither AWS calls nor the mapping proposal."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import test_staging_core_iam as CORE
import test_staging_role_lifecycle as LIFECYCLE


HERE = Path(__file__).resolve().parents[1] / "staging"
SPEC = importlib.util.spec_from_file_location("api_recovery_proposal", HERE / "prepare-api-recovery.py")
REPAIR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPAIR)
BROAD = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]}
OHIO = {"aws:RequestedRegion": REPAIR.REGION}


def apply_patches(document, operations):
    actual = copy.deepcopy(document)
    for op in operations:
        parts = op["path"].split("/")[1:]
        parent = actual
        for part in parts[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        key = int(parts[-1]) if isinstance(parent, list) and parts[-1] != "-" else parts[-1]
        if "old_value" in op:
            if parent[key] != op["old_value"]:
                raise AssertionError("Patch original-value evidence differs.")
        if op["op"] == "add" and key == "-":
            parent.append(op["value"])
        elif op["op"] in ("add", "replace"):
            parent[key] = op["value"]
        elif op["op"] == "remove":
            del parent[key]
        else:
            raise AssertionError("Unknown patch operation.")
    return actual


class RecoveryRoleLifecycleTests(LIFECYCLE.StagingRoleLifecycleTests):
    """Run the existing complete IAM role lifecycle matrix on exact recovery A."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.documents = [json.loads(json.dumps(doc).replace(REPAIR.API_ID, "a1b2c3d4e5"))
                         for doc in REPAIR.recovery_documents(CORE.current_reviewed_baseline()).values()]


class ApiRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = CORE.current_reviewed_baseline()
        cls.recovery = REPAIR.recovery_documents(cls.original)
        cls.forward = REPAIR.forward_documents(cls.original)

    def test_recovery_changes_only_the_two_policies_and_exact_three_operations(self):
        self.assertEqual(REPAIR.PINS, CORE.PINS)
        self.assertEqual({name for name in self.original if self.original[name] != self.recovery[name]}, set(REPAIR.CHANGED))
        self.assertEqual(self.recovery["identity-03.json"]["Statement"][:8], self.original["identity-03.json"]["Statement"])
        expected_guard = copy.deepcopy(self.original["guardrails-02.json"])
        expected_guard["Statement"][7]["Action"].remove("apigateway:DELETE")
        self.assertEqual(self.recovery["guardrails-02.json"], expected_guard)
        for name in REPAIR.FILES:
            self.assertEqual(apply_patches(self.original[name], REPAIR.patches(self.original).get(name, [])), self.recovery[name])

    def test_allow_alone_cannot_override_the_observed_cors_explicit_deny(self):
        action = "apigateway:DELETE"
        allow_only = copy.deepcopy(self.original)
        allow_only["identity-03.json"] = self.recovery["identity-03.json"]
        guard_only = copy.deepcopy(self.original)
        guard_only["guardrails-02.json"] = self.recovery["guardrails-02.json"]
        for docs, expected in ((self.original, "explicitDeny"), (allow_only, "explicitDeny"),
                               (guard_only, "implicitDeny"), (self.recovery, "allowed")):
            self.assertEqual(LIFECYCLE.decision(list(docs.values()), action, REPAIR.CORS, OHIO), expected)

    def test_effective_delta_is_only_cors_delete_gain_and_api_self_delete_revocation(self):
        resources = [REPAIR.API, REPAIR.CORS, REPAIR.API + "/stages", REPAIR.API + "/stages/staging",
                     REPAIR.API + "/stages/production", REPAIR.API + "/routes/example", REPAIR.API + "/integrations/example",
                     REPAIR.API + "/authorizers/example", REPAIR.API + "/deployments/example", REPAIR.API + "/cors/extra",
                     REPAIR.API.replace(REPAIR.API_ID, "z9y8x7w6v5"), REPAIR.CORS.replace(REPAIR.API_ID, "z9y8x7w6v5"),
                     REPAIR.CORS.replace("us-east-2", "us-east-1"), "*", *REPAIR.tag_arns()]
        for action in ("apigateway:GET", "apigateway:POST", "apigateway:PATCH", "apigateway:PUT", "apigateway:DELETE", "apigateway:TagResource"):
            for resource in resources:
                for context in (OHIO, {"aws:RequestedRegion": "us-east-1"}, {}):
                    for broad in ([], [BROAD]):
                        before = LIFECYCLE.decision(list(self.original.values()) + broad, action, resource, context)
                        after = LIFECYCLE.decision(list(self.recovery.values()) + broad, action, resource, context)
                        expected = before
                        if action == "apigateway:DELETE" and context == OHIO and resource == REPAIR.CORS:
                            expected = "allowed"
                        elif action == "apigateway:DELETE" and resource == REPAIR.API:
                            expected = "explicitDeny"
                        with self.subTest(action=action, resource=resource, context=context, broad=bool(broad)):
                            self.assertEqual(after, expected)

    def test_core_and_cleanup_requests_keep_their_existing_permissions(self):
        for case in CORE.core_request_cases():
            expected = "explicitDeny" if case["action"] == "apigateway:DELETE" and case["resource"] == REPAIR.API else case["expected"]
            self.assertEqual(LIFECYCLE.decision(list(self.recovery.values()), case["action"], case["resource"], case["context"]), expected)

    def test_all_42_core_role_cleanup_contexts_remain_unchanged(self):
        checks = 0
        for slug in CORE.CORE:
            name = CORE.STACK + "-" + slug + "-role"
            role = f"arn:aws:iam::{CORE.ACCOUNT}:role/actionbridge/staging/{CORE.STACK}/{name}"
            alias = f"arn:aws:iam::{CORE.ACCOUNT}:role/{name}"
            boundary = f"arn:aws:iam::{CORE.ACCOUNT}:policy/{CORE.STACK}-{slug}-boundary"
            cases = [("iam:GetRole", alias, {}), ("iam:GetRole", alias, {"iam:PermissionsBoundary": boundary}),
                     ("iam:GetRole", role, {}), ("iam:GetRolePolicy", role, {}),
                     ("iam:ListRolePolicies", role, {}), ("iam:ListAttachedRolePolicies", role, {}),
                     ("iam:ListRoleTags", role, {}), ("iam:DeleteRolePolicy", role, {}),
                     ("iam:DetachRolePolicy", role, {"iam:PermissionsBoundary": boundary, "iam:PolicyARN": CORE.BASIC}),
                     ("iam:DetachRolePolicy", alias, {"iam:PolicyARN": CORE.BASIC}),
                     ("iam:DeleteRole", role, {}), ("iam:TagRole", role, {}), ("iam:UntagRole", role, {}),
                     ("iam:DetachRolePolicy", role, {"iam:PermissionsBoundary": boundary + "-unrelated", "iam:PolicyARN": CORE.BASIC})]
            for action, resource, context in cases:
                before = LIFECYCLE.decision(list(self.original.values()), action, resource, context)
                after = LIFECYCLE.decision(list(self.recovery.values()), action, resource, context)
                self.assertEqual(before, after)
                self.assertEqual(after, "explicitDeny" if context.get("iam:PermissionsBoundary", "").endswith("-unrelated") else "allowed")
                checks += 1
        self.assertEqual(checks, 42)

    def test_mapping_and_iam_statements_are_unchanged_and_undocumented_grant_is_absent(self):
        for name in REPAIR.FILES:
            for needle in ("EventSourceMapping", "iam:"):
                old = [s for s in self.original[name]["Statement"] if needle in json.dumps(s)]
                new = [s for s in self.recovery[name]["Statement"] if needle in json.dumps(s)]
                self.assertEqual(old, new)
        for proposed in (self.recovery, self.forward):
            self.assertNotIn("apigateway:TagResource", json.dumps(proposed))
            self.assertNotIn("apigateway:UntagResource", json.dumps(proposed))

    def test_forward_draft_only_allows_documented_http_verbs_on_exact_encoded_stage_tags(self):
        docs = list(self.forward.values())
        for arn in REPAIR.tag_arns():
            self.assertNotIn("*", arn)
            for action in ("apigateway:GET", "apigateway:POST", "apigateway:PATCH", "apigateway:PUT"):
                self.assertEqual(LIFECYCLE.decision(docs, action, arn, OHIO), "allowed")
                self.assertEqual(LIFECYCLE.decision(docs + [BROAD], action, arn.replace(REPAIR.API_ID, "z9y8x7w6v5"), OHIO), "explicitDeny")
                self.assertEqual(LIFECYCLE.decision(docs + [BROAD], action, arn + "%2Fextra", OHIO), "explicitDeny")
                self.assertEqual(LIFECYCLE.decision(docs + [BROAD], action, arn, {"aws:RequestedRegion": "us-east-1"}), "explicitDeny")
            self.assertEqual(LIFECYCLE.decision(docs + [BROAD], "apigateway:DELETE", arn, OHIO), "explicitDeny")
        # Draft B intentionally does not pretend to fix the service's named
        # TagResource check during tagged CreateStage.
        self.assertEqual(LIFECYCLE.decision(docs, "apigateway:TagResource", REPAIR.API + "/stages", OHIO), "implicitDeny")

    def test_forward_lambda_guard_merge_is_exactly_equivalent(self):
        before = {"Version": "2012-10-17", "Statement": self.original["guardrails-02.json"]["Statement"][1:3]}
        after = {"Version": "2012-10-17", "Statement": [self.forward["guardrails-02.json"]["Statement"][1]]}
        for slug in ("health", "cases", "calculations", "jobs", "job-worker", "production"):
            for suffix in ("", ":version"):
                resource = f"arn:aws:lambda:us-east-2:631367363628:function:actionbridge-dental-staging-{slug}" + suffix
                for action in ("lambda:AddPermission", "lambda:RemovePermission", "lambda:GetPolicy", "lambda:DeleteFunction"):
                    self.assertEqual(LIFECYCLE.decision([before, BROAD], action, resource),
                                     LIFECYCLE.decision([after, BROAD], action, resource))

    def test_drift_in_any_original_or_saved_export_stops_before_writing(self):
        for name in REPAIR.FILES:
            modified = copy.deepcopy(self.original)
            modified[name]["Statement"].append(BROAD["Statement"][0])
            with self.subTest(policy=name), self.assertRaises(ValueError):
                REPAIR.recovery_documents(modified)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            source, live = self.fixture(base)
            (live / REPAIR.LIVE_EXPORTS["identity-03.json"]).write_text(json.dumps(BROAD))
            with self.assertRaises(ValueError):
                REPAIR.write_reviews(source, live, base / "a", base / "b")
            self.assertFalse((base / "a").exists())
            self.assertFalse((base / "b").exists())

    def fixture(self, base):
        source, live = base / "source", base / "live"
        source.mkdir()
        live.mkdir()
        for name, doc in self.original.items():
            (source / name).write_text(json.dumps(doc, indent=3))
            if name in REPAIR.LIVE_EXPORTS:
                (live / REPAIR.LIVE_EXPORTS[name]).write_text(json.dumps(doc, separators=(",", ":")))
        return source, live

    def test_review_bundles_are_exclusive_fit_quotas_and_keep_three_parts_byte_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            source, live = self.fixture(base)
            before = {p.name: p.read_bytes() for p in source.iterdir()}
            reviews = REPAIR.write_reviews(source, live, base / "a", base / "b")
            self.assertEqual([r["status"] for r in reviews], ["UNAPPLIED_RECOVERY_A_OWNER_APPROVAL_REQUIRED", "DRAFT_B_NOT_RECOMMENDED_FOR_LIVE"])
            for folder, expected, forward in ((base / "a", self.recovery, False), (base / "b", self.forward, True)):
                for name in REPAIR.FILES:
                    self.assertEqual(json.loads((folder / name).read_text()), expected[name])
                    self.assertLessEqual(REPAIR.compact_size(expected[name]), 6144)
                    if name in REPAIR.UNCHANGED:
                        self.assertEqual((folder / name).read_bytes(), before[name])
                    self.assertEqual(apply_patches(self.original[name], REPAIR.patches(self.original, forward).get(name, [])), expected[name])
                review = json.loads((folder / "review.json").read_text())
                self.assertFalse(review["event_source_mapping_proposal_applied"])
                self.assertFalse(review["tagged_CreateStage_failure_resolved"])
                self.assertFalse(review["rollback_continuation_authorized"])
            written = {p.name: p.read_bytes() for p in (base / "a").iterdir()}
            with self.assertRaises(ValueError):
                REPAIR.write_reviews(source, live, base / "a")
            self.assertEqual({p.name: p.read_bytes() for p in (base / "a").iterdir()}, written)
            self.assertEqual({p.name: p.read_bytes() for p in source.iterdir()}, before)

    def test_helper_has_no_aws_or_network_execution_dependencies(self):
        tree = ast.parse((HERE / "prepare-api-recovery.py").read_text())
        imports = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imports |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertFalse(imports & {"boto3", "botocore", "subprocess", "socket", "urllib.request", "requests", "http.client"})


if __name__ == "__main__":
    unittest.main()
