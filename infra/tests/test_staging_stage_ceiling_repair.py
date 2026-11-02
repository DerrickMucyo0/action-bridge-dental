"""Stage exception regression tests: public fixtures, no account exports or AWS."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_staging_kms_repair as KMS

HERE = Path(__file__).resolve().parents[1] / "staging"
SPEC = importlib.util.spec_from_file_location("stage_ceiling_repair", HERE / "prepare-stage-ceiling-repair.py")
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


class StageCeilingRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("stage_test_kms_fixture", HERE / "prepare-kms-repair.py")
        repair = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(repair)
        cls.legacy = KMS.TAGGING.PROPOSAL.proposal_documents(KMS.TAGGING.PREVIOUS.recovery_a_baseline())
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            for name, document in cls.legacy.items():
                (source / name).write_text(json.dumps(document))
            with patch.object(repair.D, "POLICY_SOURCE", source):
                cls.baseline = repair.repair_template(repair.D.access_template())
        cls.policies = {R.PREFIX + "cfn-" + name.removesuffix(".json"): value for name, value in cls.legacy.items()}
        cls.policies.update({R.PREFIX + f"owner-ceiling-{i}": cls.baseline["Resources"][f"ExecutionCeiling{i}"]["Properties"]["PolicyDocument"] for i in (1, 2, 3)})
        cls.candidate = R.repair_template(cls.baseline, cls.policies)

    def test_pinned_public_fixture_and_exact_single_resource_change(self):
        self.assertEqual(R.canonical_sha(self.baseline), R.BASELINE_SHA)
        self.assertTrue(R.validate_candidate(self.baseline, self.candidate))
        resources = self.baseline["Resources"]
        self.assertEqual(len(resources), 17)
        self.assertEqual([key for key in resources if resources[key] != self.candidate["Resources"][key]], ["ExecutionCeiling1"])
        old = resources["ExecutionCeiling1"]["Properties"]["PolicyDocument"]["Statement"][0]
        new = self.candidate["Resources"]["ExecutionCeiling1"]["Properties"]["PolicyDocument"]["Statement"][0]
        self.assertEqual(old["NotAction"], new["NotAction"])
        self.assertEqual(new["NotResource"], R.STAGE_PATHS)
        self.assertEqual(set(new), {"Sid", "Effect", "NotAction", "NotResource"})
        self.assertEqual(len(json.dumps(self.candidate["Resources"]["ExecutionCeiling1"]["Properties"]["PolicyDocument"], separators=(",", ":"))), 5311)

    def test_matrix_matches_independent_full_condition_evaluator(self):
        checks = R.review_matrix(self.policies, self.candidate)
        self.assertEqual(len(checks), 107)
        before = [self.policies[R.PREFIX + suffix] for suffix in R.POLICY_PINS]
        after = copy.deepcopy(before)
        after[list(R.POLICY_PINS).index("owner-ceiling-1")] = self.candidate["Resources"]["ExecutionCeiling1"]["Properties"]["PolicyDocument"]
        for row in checks:
            extra = [KMS.BROAD] if row["adversarial_simulation_only_Allow"] else []
            for documents, label in ((before, "before"), (after, "after")):
                self.assertEqual(KMS.decision(documents + extra, row["action"], row["resource"], row["context"]), row[label], row)
        aliases = [row for row in checks if row["label"].startswith("diagnostic_identifier")]
        self.assertEqual(len(aliases), 6)
        self.assertTrue(all(row["before"] == "explicitDeny" and row["after"] == "implicitDeny" for row in aliases))

    def test_original_API_deletion_and_other_APIs_stay_explicitly_denied(self):
        docs = list(self.policies.values())
        after = [self.candidate["Resources"]["ExecutionCeiling1"]["Properties"]["PolicyDocument"] if d == self.policies[R.PREFIX + "owner-ceiling-1"] else d for d in docs]
        for documents in (docs, after):
            for resource in (R.API, R.API.replace("l52iwors8c", "production")):
                self.assertEqual(KMS.decision(documents + [KMS.BROAD], "apigateway:DELETE", resource, {"aws:RequestedRegion": R.REGION}), "explicitDeny")

    def test_baseline_policy_drift_unknown_fields_and_missing_inputs_fail_closed(self):
        for mutate in (lambda d: d["Resources"]["ExecutionCeiling2"]["Properties"]["PolicyDocument"]["Statement"].pop(),
                       lambda d: d["Resources"]["HealthFunctionRole"]["Properties"].update(PermissionsBoundary="other"),
                       lambda d: d["Resources"]["ExecutionCeiling1"].update(UnfamiliarNestedField={"Allow": True})):
            altered = copy.deepcopy(self.baseline)
            mutate(altered)
            with self.assertRaises(ValueError):
                R.repair_template(altered, self.policies)
        for key in self.policies:
            altered = copy.deepcopy(self.policies)
            del altered[key]
            with self.assertRaises(ValueError):
                R.repair_template(self.baseline, altered)
        altered = copy.deepcopy(self.policies)
        altered[R.PREFIX + "cfn-identity-03"]["Statement"].append(copy.deepcopy(KMS.BROAD["Statement"][0]))
        with self.assertRaises(ValueError):
            R.repair_template(self.baseline, altered)

    def test_candidate_cannot_add_permission_widen_paths_or_change_KMS(self):
        for change in (lambda d: d["Resources"]["ExecutionCeiling1"]["Properties"]["PolicyDocument"]["Statement"][0]["NotResource"].append(R.API + "/*"),
                       lambda d: d["Resources"]["ExecutionCeiling1"]["Properties"]["PolicyDocument"]["Statement"].extend(KMS.BROAD["Statement"]),
                       lambda d: d["Resources"].pop("HealthFunctionKmsBoundary")):
            altered = copy.deepcopy(self.candidate)
            change(altered)
            with self.assertRaises(ValueError):
                R.validate_candidate(self.baseline, altered)

    def test_writer_json_patch_reproduces_exact_candidate_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, policies, output = root / "baseline.json", root / "policies.json", root / "candidate"
            source.write_text(json.dumps(self.baseline))
            policies.write_text(json.dumps(self.policies))
            baseline_copy = copy.deepcopy(self.baseline)
            review = R.prepare(source, policies, output)
            self.assertEqual(self.baseline, baseline_copy)
            self.assertEqual(review["new_Allow_statements"], 0)
            self.assertEqual(review["AWS_calls"], 0)
            self.assertIn("implicitDeny", review["caveat"])
            patch_data = json.loads((output / "exact-json-patch.json").read_text())
            target = baseline_copy["Resources"]["ExecutionCeiling1"]["Properties"]["PolicyDocument"]["Statement"][0]
            self.assertEqual(target["Resource"], patch_data[0]["value"])
            del target["Resource"]
            target["NotResource"] = patch_data[2]["value"]
            self.assertEqual(baseline_copy, json.loads((output / "access-stack-stage-tagging-repair.json").read_text()))
            with self.assertRaises(ValueError):
                R.prepare(source, policies, output)

    def test_invalid_JSON_and_unsupported_applicable_conditions_are_rejected(self):
        for raw in ('{"Statement": [], "Statement": []}', '{"x": NaN}'):
            with self.assertRaises(ValueError):
                R.decode(raw)
        unknown = {"Statement": [{"Effect": "Allow", "Action": "apigateway:POST", "Resource": R.STAGE_PATHS[0], "Condition": {"NewOperator": {"key": "value"}}}]}
        with self.assertRaises(ValueError):
            R.api_decision([unknown], "apigateway:POST", R.STAGE_PATHS[0], {})
        with self.assertRaises(ValueError):
            R.api_decision([KMS.BROAD], "iam:CreateRole", "*", {})


if __name__ == "__main__":
    unittest.main()
