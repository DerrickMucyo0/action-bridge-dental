"""Security regression checks on local boundary drafts, not AWS authorization tests."""
import importlib.util
import json
import socket
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1] / "staging"
SPEC = importlib.util.spec_from_file_location("staging_boundaries", HERE / "build-boundaries.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MANIFEST = json.loads((HERE / "resources.json").read_text())


def allowed(document, action):
    return [item for item in document["Statement"] if item["Effect"] == "Allow" and action in item["Action"]]


class RuntimeBoundaryTests(unittest.TestCase):
    def setUp(self):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("Network prohibited")):
            self.documents = MODULE.boundaries(MANIFEST)

    def role(self, logical):
        return self.documents[MANIFEST["functions"][logical]["boundary_policy_name"]]

    def test_all_five_public_drafts_match_and_fit_managed_policy_limit(self):
        self.assertEqual(len(self.documents), 5)
        for name, document in self.documents.items():
            self.assertEqual(json.loads((HERE / "generated" / (name + ".json")).read_text()), document)
            self.assertLessEqual(len(json.dumps(document, separators=(",", ":"))), 6144)

    def test_each_role_can_write_only_its_own_log_streams_and_cannot_create_groups(self):
        for logical, function in MANIFEST["functions"].items():
            document = self.role(logical)
            for action in ("logs:CreateLogStream", "logs:PutLogEvents"):
                self.assertEqual(allowed(document, action)[0]["Resource"],
                                 f"arn:aws:logs:us-east-2:631367363628:log-group:/aws/lambda/{function['name']}:log-stream:*")
            self.assertFalse(allowed(document, "logs:CreateLogGroup"))

    def test_health_has_no_data_or_billable_permissions_and_calculation_is_read_only(self):
        for logical, expected in (("HealthFunction", {"logs:CreateLogStream", "logs:PutLogEvents"}),
                                  ("CalculationsFunction", {"logs:CreateLogStream", "logs:PutLogEvents", "dynamodb:GetItem"})):
            actions = {action for item in self.role(logical)["Statement"] if item["Effect"] == "Allow" for action in item["Action"]}
            self.assertEqual(actions, expected)

    def test_jobs_cannot_invoke_models_or_poll_queue_and_worker_cannot_send(self):
        for action in ("bedrock:InvokeModel", "sqs:ReceiveMessage", "sqs:DeleteMessage", "s3:GetObject", "dynamodb:Query"):
            self.assertFalse(allowed(self.role("JobsFunction"), action))
        for action in ("sqs:SendMessage", "s3:PutObject", "dynamodb:Query", "polly:SynthesizeSpeech"):
            self.assertFalse(allowed(self.role("JobWorkerFunction"), action))

    def test_data_resources_are_exact_staging_resources_and_s3_owner_is_required(self):
        for document in self.documents.values():
            for item in document["Statement"]:
                if item["Effect"] != "Allow":
                    continue
                for action in item["Action"]:
                    self.assertNotIn("*", action)
                    if action.startswith("dynamodb:"):
                        self.assertEqual(item["Resource"], "arn:aws:dynamodb:us-east-2:631367363628:table/actionbridge-dental-staging-cases")
                    if action.startswith("s3:"):
                        self.assertEqual(item["Resource"], "arn:aws:s3:::ab-dental-staging-uploads-631367363628-us-east-2/uploads/*")
                        self.assertEqual(item["Condition"]["StringEquals"]["s3:ResourceAccount"], "631367363628")
                    if action.startswith("sqs:"):
                        self.assertEqual(item["Resource"], "arn:aws:sqs:us-east-2:631367363628:actionbridge-dental-staging-jobs")

    def test_quota_scope_requires_present_and_matching_partition_keys(self):
        item = allowed(self.role("JobsFunction"), "dynamodb:UpdateItem")[0]
        self.assertEqual(item["Condition"], {"ForAllValues:StringLike": {"dynamodb:LeadingKeys": ["STAGING_QUOTA#*"]},
                                             "Null": {"dynamodb:LeadingKeys": "false"}})
        self.assertFalse(allowed(self.role("CasesFunction"), "dynamodb:UpdateItem"))

    def test_bedrock_models_are_only_available_through_exact_profile(self):
        items = allowed(self.role("JobWorkerFunction"), "bedrock:InvokeModel")
        self.assertEqual(len(items), 2)
        profile = "arn:aws:bedrock:us-east-2:631367363628:inference-profile/us.amazon.nova-2-lite-v1:0"
        self.assertEqual(items[0]["Resource"], profile)
        self.assertEqual(items[1]["Condition"], {"StringEquals": {"bedrock:InferenceProfileArn": profile}})
        self.assertEqual(set(items[1]["Resource"]), {f"arn:aws:bedrock:{r}::foundation-model/amazon.nova-2-lite-v1:0" for r in MODULE.DESTINATIONS})

    def test_required_wildcard_processing_is_explicit_and_region_limited(self):
        expected = {"polly:SynthesizeSpeech", "transcribe:StartTranscriptionJob", "textract:DetectDocumentText", "textract:StartDocumentTextDetection", "textract:GetDocumentTextDetection"}
        actual = set()
        for document in self.documents.values():
            for item in document["Statement"]:
                if item["Effect"] == "Allow" and item["Resource"] == "*":
                    actual.update(item["Action"])
                    self.assertIn(item["Condition"]["StringEquals"]["aws:RequestedRegion"], ("us-east-1", "us-east-2"))
        self.assertEqual(actual, expected)

    def test_explicit_deny_rejects_other_actions_and_resource_policy_scope_escapes(self):
        for document in self.documents.values():
            allows = {action for item in document["Statement"] if item["Effect"] == "Allow" for action in item["Action"]}
            no_other = next(item for item in document["Statement"] if item["Sid"] == "NoOtherActions")
            self.assertEqual(set(no_other["NotAction"]), allows)
            self.assertEqual(no_other["Effect"], "Deny")
            for item in document["Statement"]:
                if item["Effect"] == "Allow" and item["Resource"] != "*":
                    for action in item["Action"]:
                        self.assertTrue(any(guard["Effect"] == "Deny" and action in guard.get("Action", []) and "NotResource" in guard for guard in document["Statement"]))


if __name__ == "__main__":
    unittest.main()
