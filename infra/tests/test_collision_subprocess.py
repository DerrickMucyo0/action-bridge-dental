"""Exercise the real runner -> subprocess -> parser path with a local fake AWS CLI.

PATH contains only the temporary fake executable. Both AWS configuration paths
point at synthetic files. No AWS CLI installation, credentials or network is used.
"""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "infra/staging/run-collision-checks.py"
PRIVATE_FIXTURE = "SYNTHETIC_PRIVATE_DIAGNOSTIC_MUST_NOT_ESCAPE"

FAKE_AWS = r'''
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
mode = os.environ["COLLISION_TEST_MODE"]
private = "SYNTHETIC_PRIVATE_DIAGNOSTIC_MUST_NOT_ESCAPE"

def fail():
    sys.stderr.write("FAKE_CLI_ARGUMENT_CONTRACT_FAILED\n")
    raise SystemExit(87)

if args[:7] != ["--profile", "actionbridge-developer", "--region", "us-east-2", "--no-cli-pager", "--output", "json"]:
    fail()
if args[-5:] != ["--no-cli-auto-prompt", "--cli-connect-timeout", "5", "--cli-read-timeout", "10"]:
    fail()
if any(flag in args for flag in ("--debug", "--no-sign-request", "--no-paginate", "--max-items", "--endpoint-url")):
    fail()
if args.count("--query") != 1:
    fail()
if os.environ.get("AWS_CLI_ERROR_FORMAT") != "json":
    fail()
query = args[args.index("--query") + 1]
if any(word in query for word in ("Environment", "UserId", "Secret", "TokenValue")):
    fail()
kind = tuple(args[7:9])
operations = {
    ("sts", "get-caller-identity"): "GetCallerIdentity",
    ("ec2", "describe-regions"): "DescribeRegions",
    ("cloudformation", "describe-stacks"): "DescribeStacks",
    ("lambda", "get-function-configuration"): "GetFunctionConfiguration",
    ("logs", "describe-log-groups"): "DescribeLogGroups",
    ("dynamodb", "describe-table"): "DescribeTable",
    ("sqs", "get-queue-url"): "GetQueueUrl",
    ("s3api", "head-bucket"): "HeadBucket",
    ("iam", "list-roles"): "ListRoles",
    ("iam", "get-role"): "GetRole",
    ("iam", "get-policy"): "GetPolicy",
    ("apigatewayv2", "get-apis"): "GetApis",
    ("apigateway", "get-rest-apis"): "GetRestApis",
}
if kind not in operations:
    fail()
with Path(os.environ["COLLISION_TEST_TRACE"]).open("a") as trace:
    trace.write(json.dumps(args) + "\n")

def success(value):
    sys.stdout.write(json.dumps(value) + "\n")
    raise SystemExit(0)

def records(value):
    return {"Records": value, "NextToken": None, "ServiceToken": None,
            "Marker": None, "Position": None, "Truncated": None}

def service_error(code, message, enhanced=False, legacy=False):
    prefix = "" if legacy else "aws: [ERROR]: "
    text = "\n" + prefix + "An error occurred (" + code + ") when calling the " + operations[kind] + " operation: " + message + "\n"
    if enhanced:
        text += "\nAdditional error details:\nType: User\n"
    sys.stderr.write(text)
    raise SystemExit(254)

if kind == ("sts", "get-caller-identity"):
    if query != "{Account:Account,Arn:Arn}":
        fail()
    if mode == "wrong-account":
        success({"Account": "195469705669", "Arn": "arn:aws:iam::195469705669:user/actionbridge-developer"})
    success({"Account": "631367363628", "Arn": "arn:aws:iam::631367363628:user/actionbridge-developer"})
if kind == ("lambda", "get-function-configuration"):
    if query != "{Name:FunctionName,State:State}":
        fail()
    name = args[args.index("--function-name") + 1]
    if name not in {"actionbridge-dental-staging-" + suffix for suffix in ("health", "cases", "calculations", "jobs", "job-worker")}:
        fail()
    if mode == "json":
        sys.stderr.write(json.dumps({"Code": "ResourceNotFoundException", "Message": private, "Type": "User"}) + "\n")
        raise SystemExit(254)
    if mode == "denied":
        service_error("AccessDeniedException", private, enhanced=True)
    if mode == "network":
        sys.stderr.write("Could not connect to the endpoint URL: " + private + "\n")
        raise SystemExit(254)
    if mode == "mixed":
        sys.stderr.write("WARNING: " + private + "\n")
        service_error("ResourceNotFoundException", "Function not found", enhanced=True)
    if mode == "unknown":
        service_error("SyntheticUnrecognizedException", private, enhanced=True)
    service_error("ResourceNotFoundException", "Function not found", enhanced=mode != "legacy", legacy=mode == "legacy")
if kind == ("ec2", "describe-regions"):
    success(records([{"Region": "us-east-2", "Status": "opt-in-not-required"}]))
if kind in (("logs", "describe-log-groups"), ("iam", "list-roles"), ("apigatewayv2", "get-apis"), ("apigateway", "get-rest-apis")):
    success(records([]))
if kind == ("cloudformation", "describe-stacks"):
    service_error("ValidationError", "Stack with id actionbridge-dental-staging does not exist")
if kind == ("dynamodb", "describe-table"):
    service_error("ResourceNotFoundException", "Requested resource not found")
if kind in (("iam", "get-role"), ("iam", "get-policy")):
    service_error("NoSuchEntity", "The requested entity does not exist")
if kind == ("sqs", "get-queue-url"):
    service_error("AWS.SimpleQueueService.NonExistentQueue", "The specified queue does not exist or you do not have access to it")
if kind == ("s3api", "head-bucket"):
    service_error("404", "Not Found")
fail()
'''


class CollisionSubprocessTests(unittest.TestCase):
    def run_runner(self, mode="enhanced", extra=(), approved=True):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            executable = root / "aws"
            executable.write_text("#!" + sys.executable + "\n" + FAKE_AWS)
            executable.chmod(0o700)
            config = root / "config"
            config.write_text("[profile actionbridge-developer]\nregion = us-east-2\ncli_history = disabled\n")
            credentials = root / "credentials"
            credentials.write_text("[actionbridge-developer]\ncli_history = disabled\n")
            trace = root / "commands.jsonl"
            environment = {name: value for name, value in os.environ.items() if not name.startswith("AWS_")}
            environment.update({
                "PATH": str(root),
                "AWS_CONFIG_FILE": str(config),
                "AWS_SHARED_CREDENTIALS_FILE": str(credentials),
                "COLLISION_TEST_MODE": mode,
                "COLLISION_TEST_TRACE": str(trace),
            })
            arguments = [sys.executable, str(RUNNER), "--profile", "actionbridge-developer"]
            if approved:
                arguments += ["--execute", "--approve-read-only-checks"]
            process = subprocess.run(
                [*arguments, *extra],
                cwd=root, env=environment, shell=False, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=20, check=False,
            )
            calls = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
            self.assertNotIn("FAKE_CLI_ARGUMENT_CONTRACT_FAILED", process.stdout + process.stderr)
            self.assertNotIn(PRIVATE_FIXTURE, process.stdout + process.stderr)
            return process, calls

    def test_captured_multiline_bytes_prove_whole_stderr_matching_was_the_failure(self):
        spec = importlib.util.spec_from_file_location("captured_collision_runner", RUNNER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        check = module.prepared_plan("actionbridge-developer", check="health")[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            executable = root / "aws"
            executable.write_text("#!" + sys.executable + "\n" + FAKE_AWS)
            executable.chmod(0o700)
            environment = {name: value for name, value in os.environ.items() if not name.startswith("AWS_")}
            environment.update({
                "PATH": str(root), "AWS_CLI_ERROR_FORMAT": "json",
                "COLLISION_TEST_MODE": "enhanced", "COLLISION_TEST_TRACE": str(root / "trace.jsonl"),
            })
            captured = subprocess.run(
                [str(executable), *check["command"][1:]], cwd=root, env=environment,
                shell=False, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                timeout=20, check=False,
            )
        self.assertEqual(captured.returncode, 254)
        self.assertEqual(captured.stdout, "")
        self.assertIn("\n\nAdditional error details:\nType: User\n", captured.stderr)
        first_line = captured.stderr.strip().splitlines()[0]
        self.assertIsNotNone(module.ERROR.fullmatch(first_line))
        # The previous implementation applied this header regex to ALL stderr.
        # These are the same bytes captured from an actual subprocess above.
        self.assertIsNone(module.ERROR.fullmatch(captured.stderr))
        finding = module.classify(check, captured)
        self.assertEqual(finding["error_code"], "ResourceNotFoundException")
        self.assertEqual(finding["status"], "AVAILABLE")
        output = io.StringIO()
        self.assertEqual(module.render([finding], output, diagnostic=True), 0)
        self.assertEqual(json.loads(output.getvalue()), {
            "aws_error_code": "ResourceNotFoundException", "classification": "AVAILABLE",
        })
        self.assertNotIn("Function not found", output.getvalue())
        self.assertNotIn("Additional error details", output.getvalue())

    def test_real_subprocess_multiline_enhanced_cli_error_preserves_service_classification(self):
        process, calls = self.run_runner()
        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertEqual(len(calls), 32)
        self.assertEqual(calls[0][7:9], ["sts", "get-caller-identity"])
        self.assertIn("AVAILABLE=23, COLLISION=0, UNKNOWN=9", process.stdout)
        self.assertIn("AVAILABLE Function actionbridge-dental-staging-health", process.stdout)
        self.assertIn("ResourceNotFoundException", process.stdout)
        self.assertIn("CLI exit 254", process.stdout)
        for label in (
            "Queue actionbridge-dental-staging-jobs",
            "Queue actionbridge-dental-staging-dlq",
            "Uploads bucket ab-dental-staging-uploads-631367363628-us-east-2",
            "Artifacts bucket ab-dental-staging-artifacts-631367363628-us-east-2",
            "Boundary policy actionbridge-dental-staging-health-boundary",
        ):
            self.assertIn("UNKNOWN " + label, process.stdout)
        self.assertNotIn("Additional error details:", process.stdout + process.stderr)
        self.assertNotIn("Function not found", process.stdout + process.stderr)

    def test_real_subprocess_legacy_cli_errors_still_work(self):
        process, calls = self.run_runner("legacy")
        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertEqual(len(calls), 32)
        self.assertIn("AVAILABLE=23, COLLISION=0, UNKNOWN=9", process.stdout)

    def test_one_health_verification_runs_only_auth_and_health_and_sanitizes_diagnostics(self):
        process, calls = self.run_runner(extra=("--check", "health", "--diagnostic"))
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual([call[7:9] for call in calls], [["sts", "get-caller-identity"], ["lambda", "get-function-configuration"]])
        self.assertEqual(calls[-1][calls[-1].index("--function-name") + 1], "actionbridge-dental-staging-health")
        diagnostics = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual(len(diagnostics), 2)
        for diagnostic in diagnostics:
            self.assertEqual(set(diagnostic), {"aws_error_code", "classification"})
        self.assertIn({"aws_error_code": "ResourceNotFoundException", "classification": "AVAILABLE"}, diagnostics)
        self.assertNotIn("Additional error details:", process.stdout + process.stderr)
        self.assertNotIn("Function not found", process.stdout + process.stderr)

    def test_same_exit_254_denial_network_and_unknown_errors_remain_unknown_end_to_end(self):
        for mode in ("denied", "network", "mixed", "unknown"):
            with self.subTest(mode=mode):
                process, calls = self.run_runner(mode, ("--check", "health", "--diagnostic"))
                self.assertEqual(process.returncode, 2, process.stderr)
                self.assertEqual(len(calls), 2)
                diagnostics = [json.loads(line) for line in process.stdout.splitlines()]
                self.assertEqual(len(diagnostics), 2)
                self.assertEqual(diagnostics[-1]["classification"], "UNKNOWN")
                self.assertNotIn("Additional error details:", process.stdout + process.stderr)
                self.assertNotIn("Function not found", process.stdout + process.stderr)

    def test_requested_json_error_format_is_parsed_without_exposing_the_service_message(self):
        process, calls = self.run_runner("json", ("--check", "health", "--diagnostic"))
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(len(calls), 2)
        diagnostics = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual(diagnostics, [
            {"aws_error_code": None, "classification": "AVAILABLE"},
            {"aws_error_code": "ResourceNotFoundException", "classification": "AVAILABLE"},
        ])

    def test_wrong_authenticated_account_prevents_health_subprocess(self):
        process, calls = self.run_runner("wrong-account", ("--check", "health", "--diagnostic"))
        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][7:9], ["sts", "get-caller-identity"])
        diagnostics = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual(len(diagnostics), 2)
        self.assertTrue(all(item == {"aws_error_code": None, "classification": "UNKNOWN"} for item in diagnostics))

    def test_without_both_explicit_flags_no_aws_executable_is_started(self):
        for extra, expected in ((("--check", "health"), 0), (("--check", "health", "--execute"), 2)):
            with self.subTest(extra=extra):
                process, calls = self.run_runner(extra=extra, approved=False)
                self.assertEqual(process.returncode, expected)
                self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
