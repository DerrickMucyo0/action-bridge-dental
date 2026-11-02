"""Recognized HTTP Stage Tags proposal: exact scope and combined explicit Denies.

Only public fixtures are used. IAM recognition, local policy math, owner-reported
Console validation, and actual provider execution are separate evidence classes.
"""
import ast
import copy
import json
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote

import yaml

import test_staging_api_recovery as RECOVERY
import test_staging_core_forward_iam as PREVIOUS
import test_staging_core_iam as CORE
from test_staging_role_lifecycle import decision


HERE = Path(__file__).resolve().parents[1] / "staging"
SPEC = importlib.util.spec_from_file_location("http_stage_tagging_proposal", HERE / "prepare-http-stage-tagging.py")
PROPOSAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROPOSAL)
OHIO = {"aws:RequestedRegion": PROPOSAL.REGION}
BROAD = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]}
CATALOG = PREVIOUS.RECOGNIZED_HTTP_CATALOG


class HttpStageTaggingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = PREVIOUS.recovery_a_baseline()
        cls.proposed = PROPOSAL.proposal_documents(cls.original)
        cls.docs = list(cls.proposed.values())

    def test_exact_two_policy_delta_and_tenth_identity_statement_amendment(self):
        self.assertEqual({n for n in PROPOSAL.FILES if self.original[n] != self.proposed[n]}, set(PROPOSAL.CHANGED))
        before = self.original["identity-03.json"]["Statement"]
        after = self.proposed["identity-03.json"]["Statement"]
        self.assertEqual(before[:9], after[:9])
        expected = copy.deepcopy(before[9])
        expected["NotResource"].append(PROPOSAL.TAGS)
        self.assertEqual(after[9], expected)
        self.assertNotEqual(before, after[:10])
        self.assertEqual((len(after), len(self.proposed["guardrails-02.json"]["Statement"])), (11, 14))
        self.assertEqual(PROPOSAL.STRICT.compact_size(self.proposed["identity-03.json"]), 4474)
        self.assertEqual(PROPOSAL.STRICT.compact_size(self.proposed["guardrails-02.json"]), 5788)
        for name in PROPOSAL.FILES:
            self.assertLessEqual(PROPOSAL.STRICT.compact_size(self.proposed[name]), 6144)
            self.assertEqual(RECOVERY.apply_patches(self.original[name], PROPOSAL.proposal_patches(self.original, self.proposed).get(name, [])), self.proposed[name])

    def test_all_api_action_names_are_recognized_http_verbs_not_provider_operation_labels(self):
        for doc in self.proposed.values():
            PROPOSAL.STRICT.validate_action_recognition(doc, CATALOG)
        text = json.dumps(self.proposed)
        self.assertNotIn("apigateway:TagResource", text)
        self.assertNotIn("apigateway:UntagResource", text)
        self.assertEqual(PROPOSAL.TAGS, f"arn:aws:apigateway:{PROPOSAL.REGION}::/tags/" + quote(PROPOSAL.STAGE, safe=""))
        self.assertNotIn("*", PROPOSAL.TAGS)

    def test_exact_tag_scope_and_deep_negative_uri_api_region_context_matrix(self):
        prefix, encoded = PROPOSAL.TAGS.split("/tags/", 1)
        bad = [PROPOSAL.TAGS.replace("l52iwors8c", "z9y8x7w6v5"),
               PROPOSAL.TAGS.replace("%2Fstaging", "%2Fproduction"), PROPOSAL.TAGS + "-other",
               PROPOSAL.TAGS + "%2Fchild", prefix + "/tags/" + quote(PROPOSAL.API + "/stages", safe=""),
               prefix + "/tags/" + PROPOSAL.STAGE, prefix + "/tags/" + quote(encoded, safe=""),
               prefix + "/tags/" + encoded.lower(), PROPOSAL.TAGS.replace("%2Fapis%2F", "%2Fv2%2Fapis%2F"),
               PROPOSAL.TAGS.replace("us-east-2", "us-east-1"), prefix + "/tags/*", "*"]
        contexts = [OHIO, {"AWS:REQUESTEDREGION": "us-east-2"}, {"aws:RequestedRegion": "us-east-1"},
                    {}, {"aws:RequestedRegion": ""}, {"aws:RequestedRegion": None}]
        for action in PROPOSAL.METHODS:
            for resource in [PROPOSAL.TAGS, *bad]:
                for context in contexts:
                    for extra in ([], [BROAD]):
                        expected = "allowed" if resource == PROPOSAL.TAGS and context in (OHIO, {"AWS:REQUESTEDREGION": "us-east-2"}) else "explicitDeny"
                        with self.subTest(action=action, resource=resource, context=context, broad=bool(extra)):
                            self.assertEqual(decision(self.docs + extra, action, resource, context), expected)

    def test_both_old_deny_statements_must_change_for_recognized_tags_lifecycle(self):
        exact_allow = {"Version": "2012-10-17", "Statement": [self.proposed["identity-03.json"]["Statement"][10]]}
        for action in PROPOSAL.METHODS:
            self.assertEqual(decision(list(self.original.values()) + [exact_allow], action, PROPOSAL.TAGS, OHIO), "explicitDeny")
        guard_only = copy.deepcopy(self.original)
        guard_only["guardrails-02.json"] = self.proposed["guardrails-02.json"]
        self.assertEqual(decision(list(guard_only.values()) + [exact_allow], "apigateway:POST", PROPOSAL.TAGS, OHIO), "allowed")
        self.assertEqual(decision(list(guard_only.values()) + [exact_allow], "apigateway:DELETE", PROPOSAL.TAGS, OHIO), "explicitDeny")

    def test_cors_api_root_delete_boundaries_unrelated_resources_and_mapping_guards_survive(self):
        for case in CORE.core_request_cases():
            self.assertEqual(decision(self.docs, case["action"], case["resource"], case["context"]),
                             decision(list(self.original.values()), case["action"], case["resource"], case["context"]))
        self.assertEqual(decision(self.docs, "apigateway:DELETE", PROPOSAL.API + "/cors", OHIO), "allowed")
        self.assertEqual(decision(self.docs + [BROAD], "apigateway:DELETE", PROPOSAL.API, OHIO), "explicitDeny")
        role = "arn:aws:iam::631367363628:role/actionbridge/staging/actionbridge-dental-staging/actionbridge-dental-staging-health-role"
        for action, resource, context in (("iam:DeleteRolePermissionsBoundary", role, {}),
                                          ("iam:CreatePolicyVersion", "arn:aws:iam::631367363628:policy/example", {}),
                                          ("lambda:DeleteFunction", "arn:aws:lambda:us-east-2:631367363628:function:production", OHIO),
                                          ("lambda:DeleteEventSourceMapping", "*", OHIO)):
            self.assertEqual(decision(self.docs + [BROAD], action, resource, context), "explicitDeny")
        for name in PROPOSAL.FILES:
            for marker in ("iam:", "EventSourceMapping"):
                self.assertEqual([s for s in self.original[name]["Statement"] if marker in json.dumps(s)],
                                 [s for s in self.proposed[name]["Statement"] if marker in json.dumps(s)])

    def test_lambda_deny_merge_preserves_combined_decisions(self):
        for slug in ("health", "cases", "calculations", "jobs", "job-worker", "production"):
            for suffix in ("", ":alias"):
                arn = f"arn:aws:lambda:us-east-2:631367363628:function:actionbridge-dental-staging-{slug}" + suffix
                for action in ("lambda:AddPermission", "lambda:RemovePermission", "lambda:GetPolicy", "lambda:GetFunction", "lambda:DeleteFunction"):
                    for context in (OHIO, {**OHIO, "lambda:Principal": "apigateway.amazonaws.com"}, {}):
                        self.assertEqual(decision(self.docs + [BROAD], action, arn, context),
                                         decision(list(self.original.values()) + [BROAD], action, arn, context))

    def test_core_recognized_lifecycle_math_is_kept_separate_from_unrecognized_stage_labels(self):
        template = yaml.safe_load((HERE / "generated/core.yaml").read_text())
        rows = PREVIOUS.resource_lifecycle_cases(template)
        self.assertEqual(len({row["logical_id"] for row in rows}), 44)
        unsupported = []
        for row in rows:
            if row["action"] in ("apigateway:TagResource", "apigateway:UntagResource"):
                unsupported.append(row)
                with self.assertRaises(ValueError):
                    PROPOSAL.STRICT.validate_action_recognition({"Statement": [{"Action": row["action"]}]}, CATALOG)
                continue
            self.assertEqual(decision(self.docs, row["action"], row["resource"], row["context"]), row["expected"])
        self.assertEqual(len(unsupported), 6)

    def fixture(self, base):
        source, live, counter = base / "source", base / "saved", base / "counter"
        source.mkdir(); live.mkdir(); counter.mkdir()
        for name, doc in self.original.items():
            (source / name).write_text(json.dumps(doc, indent=3))
            if name in PROPOSAL.STRICT.SAVED_EXPORTS:
                (live / PROPOSAL.STRICT.SAVED_EXPORTS[name]).write_text(json.dumps(doc, separators=(",", ":")))
            raw = PROPOSAL.STRICT.encoded(self.proposed[name]) if name in PROPOSAL.CHANGED else (source / name).read_bytes()
            (counter / name).write_bytes(raw)
        report = {"source": "Owner report: Console drafts validated then discarded", "independent_server_validation_by_assistant": False,
                  "live_IAM_changes_reported": False, "policies": {name: {"path": str(counter / name), "raw_sha256": PROPOSAL.COUNTER_RAW[name],
                    "canonical_sha256": PROPOSAL.COUNTER_CANONICAL[name], "errors": 0, "warnings": 0, "security_findings": 0, "suggestions": 0,
                    "validation_reported_by_owner": True} for name in PROPOSAL.CHANGED}}
        owner = base / "owner-report.json"; owner.write_text(json.dumps(report))
        return source, live, counter, owner

    def test_writer_copies_exact_validated_bytes_and_exclusively_preserves_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve(); source, live, counter, owner = self.fixture(base)
            before = {p.name: p.read_bytes() for p in source.iterdir()}
            with patch.object(PROPOSAL.STRICT, "load_authorization_catalog", return_value=CATALOG):
                review = PROPOSAL.write_proposal(source, live, counter, base / "public-catalog-fixture", owner, base / "output")
                self.assertEqual(review["status"], "PASS_POLICY_SECURITY_REVIEW_RUNTIME_CREATESTAGE_UNPROVEN_AWAITING_APPROVAL")
                self.assertFalse(review["actual_tagged_CreateStage_authorization_verified"])
                self.assertFalse(review["original_ten_identity_statements_unchanged"])
                self.assertTrue(review["original_first_nine_identity_statements_unchanged"])
                for name in PROPOSAL.FILES:
                    self.assertEqual((base / "output" / name).read_bytes(), (counter / name).read_bytes() if name in PROPOSAL.CHANGED else before[name])
                for name, patches in PROPOSAL.proposal_patches(self.original, self.proposed).items():
                    self.assertEqual(RECOVERY.apply_patches(self.original[name], patches), self.proposed[name])
                with self.assertRaises(ValueError):
                    PROPOSAL.write_proposal(source, live, counter, base / "catalog", owner, base / "output")
            self.assertEqual({p.name: p.read_bytes() for p in source.iterdir()}, before)

    def test_any_baseline_counter_console_evidence_or_json_drift_fails_closed(self):
        for name in PROPOSAL.FILES:
            modified = copy.deepcopy(self.original); modified[name]["Statement"].append(BROAD["Statement"][0])
            with self.subTest(name=name), self.assertRaises(ValueError):
                PROPOSAL.proposal_documents(modified)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve(); source, live, counter, owner = self.fixture(base)
            report = PROPOSAL.STRICT.decode_json(owner.read_bytes())
            report["policies"]["identity-03.json"]["warnings"] = 1
            with self.assertRaises(ValueError):
                PROPOSAL.validate_owner_report(report, counter)
            report["policies"]["identity-03.json"]["warnings"] = False
            with self.assertRaises(ValueError):
                PROPOSAL.validate_owner_report(report, counter)
            # Even semantically identical reformatting invalidates the exact
            # Console-validation byte binding; do not silently rewrite it.
            path = counter / "identity-03.json"; path.write_text(json.dumps(self.proposed["identity-03.json"]))
            with self.assertRaises(ValueError):
                PROPOSAL.write_proposal(source, live, counter, base / "catalog", owner, base / "output")
            self.assertFalse((base / "output").exists())
            with self.assertRaises(ValueError):
                PROPOSAL.STRICT.decode_json('{"Statement":[],"Statement":[]}')

    def test_no_aws_network_or_process_execution_dependencies(self):
        tree = ast.parse((HERE / "prepare-http-stage-tagging.py").read_text())
        imports = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imports |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertFalse(imports & {"boto3", "botocore", "subprocess", "socket", "urllib.request", "requests"})


if __name__ == "__main__":
    unittest.main()
