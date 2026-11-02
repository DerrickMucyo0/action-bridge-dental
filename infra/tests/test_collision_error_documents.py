"""Offline structured-error contract checks; no subprocess or AWS access."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest


STAGING = Path(__file__).resolve().parents[1] / "staging"
SPEC = importlib.util.spec_from_file_location("collision_document_runner", STAGING / "run-collision-checks.py")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)
CHECKS = RUNNER.prepared_plan("actionbridge-developer")
PRIVATE = "SYNTHETIC_PRIVATE_RESPONSE_VALUE_NEVER_PRINT"


def check_for(service, operation):
    return next(check for check in CHECKS if RUNNER.operation(check["command"]) == (service, operation))


def response(document=None, *, raw=None, stdout="", exit_code=254):
    stderr = raw if raw is not None else json.dumps(document, indent=2)
    return subprocess.CompletedProcess([], exit_code, stdout, stderr)


class CollisionErrorDocumentTests(unittest.TestCase):
    def classify(self, service, operation, document=None, **kwargs):
        return RUNNER.classify(check_for(service, operation), response(document, **kwargs))

    def test_json_absence_is_specific_to_the_trusted_operation(self):
        examples = (
            ("lambda", "get-function-configuration", "ResourceNotFoundException"),
            ("dynamodb", "describe-table", "ResourceNotFoundException"),
            ("iam", "get-role", "NoSuchEntity"),
        )
        for service, operation, code in examples:
            with self.subTest(service=service, operation=operation):
                finding = self.classify(service, operation, {"Code": code, "Message": "Resource is absent"})
                self.assertEqual(finding["status"], "AVAILABLE")
                self.assertEqual(finding["error_code"], code)
                self.assertEqual(finding["exit_code"], 254)
        for service, operation, code in (
            ("lambda", "get-function-configuration", "NoSuchEntity"),
            ("dynamodb", "describe-table", "NoSuchEntity"),
            ("iam", "get-role", "ResourceNotFoundException"),
            ("iam", "get-role", "NoSuchEntityException"),
            ("logs", "describe-log-groups", "ResourceNotFoundException"),
        ):
            self.assertEqual(self.classify(service, operation, {"Code": code, "Message": "Missing"})["status"], "UNKNOWN")

    def test_json_cloudformation_requires_the_exact_target_stack_message(self):
        missing = "Stack with id actionbridge-dental-staging does not exist"
        for message in (missing, missing + "."):
            finding = self.classify("cloudformation", "describe-stacks", {"Code": "ValidationError", "Message": message})
            self.assertEqual(finding["status"], "AVAILABLE")
        for message in ("Stack with id unrelated-stack does not exist", "Validation failed", missing + "\n" + PRIVATE):
            finding = self.classify("cloudformation", "describe-stacks", {"Code": "ValidationError", "Message": message})
            self.assertEqual(finding["status"], "UNKNOWN")
            self.assertNotIn(PRIVATE, json.dumps(finding))

    def test_json_ambiguous_policy_queue_and_bucket_absence_remains_unknown(self):
        examples = (
            ("iam", "get-policy", "NoSuchEntity"),
            ("sqs", "get-queue-url", "QueueDoesNotExist"),
            ("sqs", "get-queue-url", "AWS.SimpleQueueService.NonExistentQueue"),
            ("s3api", "head-bucket", "404"),
            ("s3api", "head-bucket", "NoSuchBucket"),
            ("s3api", "head-bucket", "403"),
        )
        for service, operation, code in examples:
            with self.subTest(service=service, code=code):
                finding = self.classify(service, operation, {"Code": code, "Message": PRIVATE})
                self.assertEqual(finding["status"], "UNKNOWN")
                self.assertEqual(finding["error_code"], code)
                self.assertNotIn(PRIVATE, json.dumps(finding))

    def test_json_denials_network_errors_and_unrecognized_codes_never_mean_available(self):
        for code in ("AccessDenied", "AccessDeniedException", "ExpiredToken", "ThrottlingException", "EndpointConnectionError", PRIVATE):
            finding = self.classify("lambda", "get-function-configuration", {"Code": code, "Message": PRIVATE})
            self.assertEqual(finding["status"], "UNKNOWN")
            self.assertNotIn(PRIVATE, json.dumps(finding))
            if code not in RUNNER.SAFE_CODES:
                self.assertEqual(finding["error_code"], "UNRECOGNIZED_CLI_OR_AWS_ERROR")

    def test_duplicate_trailing_multiple_documents_and_non_json_constants_are_unknown(self):
        valid = '{"Code":"ResourceNotFoundException","Message":"missing"}'
        malformed = (
            '{"Code":"ResourceNotFoundException","Code":"AccessDenied","Message":"missing"}',
            '{"Code":"ResourceNotFoundException","Message":"first","Message":"second"}',
            valid + "\n" + PRIVATE,
            valid + "\n" + valid,
            '{"Code":"ResourceNotFoundException","Message":NaN}',
            '{"Code":"ResourceNotFoundException","Message":"missing","Type":Infinity}',
            '[{"Code":"ResourceNotFoundException","Message":"missing"}]',
            'null',
        )
        for raw in malformed:
            with self.subTest(kind=raw[:1], length=len(raw)):
                finding = self.classify("lambda", "get-function-configuration", raw=raw)
                self.assertEqual(finding["status"], "UNKNOWN")
                self.assertNotIn(PRIVATE, json.dumps(finding))

    def test_recognized_code_does_not_validate_an_unsupported_document_envelope(self):
        documents = (
            {"Code": "ResourceNotFoundException"},
            {"Code": "ResourceNotFoundException", "Message": None},
            {"Code": "ResourceNotFoundException", "Message": {"secret": PRIVATE}},
            {"Code": "ResourceNotFoundException", "Message": "missing", "Type": [PRIVATE]},
            {"Code": "ResourceNotFoundException", "Message": "missing", "Unexpected": PRIVATE},
            {"Code": "ResourceNotFoundException", "Message": "missing", "Error": {"Code": "AccessDenied"}},
            {"Code": "ResourceNotFoundException", "Message": "missing", "Operation": "GetFunctionConfiguration"},
        )
        for document in documents:
            finding = self.classify("lambda", "get-function-configuration", document)
            self.assertEqual(finding["status"], "UNKNOWN")
            self.assertEqual(finding["error_code"], "ResourceNotFoundException")
            self.assertNotIn(PRIVATE, json.dumps(finding))

    def test_multiline_message_and_modeled_values_never_enter_results_or_diagnostics(self):
        document = {"Code": "ResourceNotFoundException", "Message": "Function not found\n" + PRIVATE, "Type": PRIVATE}
        finding = self.classify("lambda", "get-function-configuration", document)
        self.assertEqual(finding["status"], "AVAILABLE")
        self.assertEqual(finding["error_code"], "ResourceNotFoundException")
        self.assertNotIn(PRIVATE, json.dumps(finding))
        stream = io.StringIO()
        self.assertEqual(RUNNER.render([finding], stream, diagnostic=True), 0)
        diagnostic = stream.getvalue()
        self.assertNotIn(PRIVATE, diagnostic)
        documents = [json.loads(line) for line in diagnostic.splitlines() if line.startswith("{")]
        self.assertEqual(documents, [{"aws_error_code": "ResourceNotFoundException", "classification": "AVAILABLE"}])
        self.assertEqual(set(documents[0]), {"aws_error_code", "classification"})

    def test_json_error_does_not_override_partial_stdout_or_successful_exit(self):
        document = {"Code": "ResourceNotFoundException", "Message": "missing"}
        for options in ({"stdout": PRIVATE}, {"exit_code": 0}):
            finding = self.classify("lambda", "get-function-configuration", document, **options)
            self.assertEqual(finding["status"], "UNKNOWN")
            self.assertNotIn(PRIVATE, json.dumps(finding))


if __name__ == "__main__":
    unittest.main()
