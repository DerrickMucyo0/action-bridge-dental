"""Both actual tag failures: exact resource paths, full Deny precedence and scope."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import test_staging_stage_ceiling_repair as STAGE

R, KMS = STAGE.R, STAGE.KMS


class ApiTaggingBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        STAGE.StageCeilingRepairTests.setUpClass()
        cls.baseline = STAGE.StageCeilingRepairTests.baseline
        cls.policies = STAGE.StageCeilingRepairTests.policies
        cls.template, cls.proposed = R.repair_bundle(cls.baseline, cls.policies)

    def test_exact_three_policy_change_and_no_broad_allow_or_new_action_names(self):
        changed = {arn.removeprefix(R.PREFIX) for arn in self.policies if self.policies[arn] != self.proposed[arn]}
        self.assertEqual(changed, {"owner-ceiling-1", "cfn-identity-03", "cfn-guardrails-02"})
        self.assertEqual([key for key in self.baseline["Resources"] if self.baseline["Resources"][key] != self.template["Resources"][key]], ["ExecutionCeiling1"])
        before_actions = {json.dumps(s.get("Action", s.get("NotAction"))) for d in self.policies.values() for s in d["Statement"]}
        after_actions = {json.dumps(s.get("Action", s.get("NotAction"))) for d in self.proposed.values() for s in d["Statement"]}
        self.assertEqual(before_actions, after_actions)
        for name, size in (("owner-ceiling-1", 5879), ("cfn-identity-03", 5044), ("cfn-guardrails-02", 6072)):
            self.assertEqual(len(json.dumps(self.proposed[R.PREFIX + name], separators=(",", ":"))), size)

    def test_249_checks_agree_with_independent_full_condition_evaluator(self):
        rows = R.bundle_matrix(self.policies, self.proposed)
        self.assertEqual(len(rows), 249)
        for row in rows:
            extra = [KMS.BROAD] if row["adversarial_simulation_only_Allow"] else []
            for source, phase in ((self.policies, "before"), (self.proposed, "after")):
                self.assertEqual(KMS.decision(list(source.values()) + extra, row["action"], row["resource"], row["context"]), row[phase])
        diagnostic = [row for row in rows if row["label"].startswith("diagnostic_")]
        self.assertEqual(len(diagnostic), 12)
        self.assertTrue(all(row["after"] == "implicitDeny" for row in diagnostic))

    def test_observed_raw_root_tag_POST_denial_is_reproduced_and_corrected(self):
        resource = "arn:aws:apigateway:us-east-2::/tags/arn:aws:apigateway:us-east-2::/apis/l52iwors8c"
        context = {"aws:RequestedRegion": "us-east-2"}
        self.assertEqual(KMS.decision(list(self.policies.values()), "apigateway:POST", resource, context), "explicitDeny")
        self.assertEqual(KMS.decision(list(self.proposed.values()), "apigateway:POST", resource, context), "allowed")
        # Every changed carrier is required for the full lifecycle: patching an
        # Allow alone cannot defeat a remaining NotResource Deny.
        for omitted in ("owner-ceiling-1", "cfn-identity-03", "cfn-guardrails-02"):
            partial = copy.deepcopy(self.proposed)
            partial[R.PREFIX + omitted] = self.policies[R.PREFIX + omitted]
            action = "apigateway:DELETE" if omitted == "cfn-identity-03" else "apigateway:POST"
            self.assertEqual(KMS.decision(list(partial.values()), action, resource, context), "explicitDeny")

    def test_all_KMS_runtime_and_non_API_statements_are_exactly_preserved(self):
        for name in self.baseline["Resources"]:
            if name != "ExecutionCeiling1":
                self.assertEqual(self.baseline["Resources"][name], self.template["Resources"][name])
        for arn in self.policies:
            old = [s for s in self.policies[arn]["Statement"] if "apigateway" not in json.dumps(s)]
            new = [s for s in self.proposed[arn]["Statement"] if "apigateway" not in json.dumps(s)]
            self.assertEqual(old, new)
        cases = [("iam:CreatePolicyVersion", "arn:aws:iam::631367363628:policy/production"),
                 ("kms:Decrypt", "arn:aws:kms:us-east-2:631367363628:key/unrelated"),
                 ("lambda:DeleteFunction", "arn:aws:lambda:us-east-2:631367363628:function:production"),
                 ("bedrock:InvokeModel", "*"), ("iam:DeleteRolePermissionsBoundary", "*")]
        for action, resource in cases:
            for docs in (self.policies, self.proposed):
                self.assertEqual(KMS.decision(list(docs.values()) + [KMS.BROAD], action, resource, {"aws:RequestedRegion": R.REGION}), "explicitDeny")

    def test_minimal_json_differences_reproduce_all_replacements_and_writer_is_local(self):
        def apply(value, rows):
            value = copy.deepcopy(value)
            for row in rows:
                parts = [p.replace("~1", "/").replace("~0", "~") for p in row["path"].split("/")[1:]]
                parent = value
                for key in parts[:-1]:
                    parent = parent[int(key)] if isinstance(parent, list) else parent[key]
                key = int(parts[-1]) if isinstance(parent, list) else parts[-1]
                if row["op"] == "remove":
                    self.assertEqual(parent[key], row["old_value"])
                    del parent[key]
                else:
                    if row["op"] == "replace": self.assertEqual(parent[key], row["old_value"])
                    parent[key] = row["value"]
            return value
        self.assertEqual(apply(self.baseline, R.json_changes(self.baseline, self.template)), self.template)
        for arn in self.policies:
            self.assertEqual(apply(self.policies[arn], R.json_changes(self.policies[arn], self.proposed[arn])), self.proposed[arn])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "before.json").write_text(json.dumps(self.baseline))
            (root / "policies.json").write_text(json.dumps(self.policies))
            report = R.prepare_bundle(root / "before.json", root / "policies.json", root / "out")
            self.assertEqual(report["AWS_calls"], 0)
            self.assertTrue(report["application_blocked_until_complete_evidence_capacity_and_separate_approval"])
            self.assertEqual(report["owner_stack_expected_changes"], {"Add": 0, "Modify": 1, "Remove": 0, "Replacement": False})
            with self.assertRaises(ValueError): R.prepare_bundle(root / "before.json", root / "policies.json", root / "out")

    def test_AWS_simulation_review_checks_each_resource_not_the_aggregate(self):
        request = {"ActionNames": ["apigateway:POST"], "ResourceArns": [R.TAG_PATHS[3], "unrelated"]}
        response = {"EvaluationResults": [{"EvalActionName": "apigateway:POST", "EvalResourceName": "aggregate-placeholder",
                    "EvalDecision": "allowed", "ResourceSpecificResults": [
                        {"EvalResourceName": R.TAG_PATHS[3], "EvalResourceDecision": "allowed"},
                        {"EvalResourceName": "unrelated", "EvalResourceDecision": "explicitDeny"}]}]}
        rows = R.simulation_resource_decisions(request, response)
        self.assertEqual({row["resource"]: row["decision"] for row in rows}, {R.TAG_PATHS[3]: "allowed", "unrelated": "explicitDeny"})
        for mutate in (lambda d: d["EvaluationResults"][0]["ResourceSpecificResults"].pop(),
                       lambda d: d["EvaluationResults"][0].pop("ResourceSpecificResults"),
                       lambda d: d["EvaluationResults"][0]["ResourceSpecificResults"].append(d["EvaluationResults"][0]["ResourceSpecificResults"][0]),
                       lambda d: d.update(IsTruncated=True)):
            altered = copy.deepcopy(response)
            mutate(altered)
            with self.assertRaises(ValueError): R.simulation_resource_decisions(request, altered)


if __name__ == "__main__":
    unittest.main()
