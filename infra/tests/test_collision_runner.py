"""Offline runner safety checks. Every AWS subprocess is mocked; no account access."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parents[1] / "staging"
SPEC = importlib.util.spec_from_file_location("approved_collision_runner", HERE / "run-collision-checks.py")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)
CHECKS = RUNNER.prepared_plan("actionbridge-developer")
PRIVATE_FIXTURE = "SYNTHETIC_PRIVATE_VALUE_DO_NOT_PRINT"


def completed(stdout="", stderr="", code=0):
    return subprocess.CompletedProcess([], code, stdout, stderr)


def success(data):
    return completed(json.dumps(data))


def error(check, code, message="Synthetic service diagnostic", prefix=""):
    operation = RUNNER.OPERATIONS[RUNNER.operation(check["command"])]
    return completed(stderr=f"\n{prefix}An error occurred ({code}) when calling the {operation} operation: {message}\n", code=254)


def envelope(records, **overrides):
    return {"Records": records, "NextToken": None, "ServiceToken": None, "Marker": None,
            "Position": None, "Truncated": None, **overrides}


def check_for(service, operation):
    return next(check for check in CHECKS if RUNNER.operation(check["command"]) == (service, operation))


def absent_fixture(command):
    check = next(item for item in CHECKS if item["command"] == command)
    kind = RUNNER.operation(command)
    if kind == ("sts", "get-caller-identity"):
        return success({"Account": RUNNER.EXPECTED_ACCOUNT, "Arn": RUNNER.EXPECTED_USER})
    if kind == ("ec2", "describe-regions"):
        return success(envelope([{"Region": "us-east-2", "Status": "opt-in-not-required"}]))
    if kind == ("cloudformation", "describe-stacks"):
        return error(check, "ValidationError", "Stack with id actionbridge-dental-staging does not exist")
    if kind in (("lambda", "get-function-configuration"), ("dynamodb", "describe-table")):
        return error(check, "ResourceNotFoundException")
    if kind in (("iam", "get-role"), ("iam", "get-policy")):
        return error(check, "NoSuchEntity")
    if kind == ("sqs", "get-queue-url"):
        return error(check, "AWS.SimpleQueueService.NonExistentQueue")
    if kind == ("s3api", "head-bucket"):
        return error(check, "404", "Not Found")
    return success(envelope([]))


class CollisionRunnerTests(unittest.TestCase):
    def test_default_and_incomplete_approval_flags_never_invoke_aws(self):
        cases = [([], 0), (["--profile", "actionbridge-developer"], 0),
                 (["--execute", "--profile", "actionbridge-developer"], 2),
                 (["--approve-read-only-checks", "--profile", "actionbridge-developer"], 2),
                 (["--execute", "--approve-read-only-checks"], 2)]
        with patch.object(RUNNER.subprocess, "run", side_effect=AssertionError("AWS execution prohibited")) as invoke:
            for arguments, expected in cases:
                with self.subTest(arguments=arguments), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    if expected == 2:
                        with self.assertRaises(SystemExit) as result:
                            RUNNER.main(arguments)
                        self.assertEqual(result.exception.code, 2)
                    else:
                        self.assertEqual(RUNNER.main(arguments), expected)
            invoke.assert_not_called()

    def test_unrecognized_arguments_are_not_echoed(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output), self.assertRaises(SystemExit):
            RUNNER.main(["--token", PRIVATE_FIXTURE])
        self.assertNotIn(PRIVATE_FIXTURE, output.getvalue())

    def test_library_execution_also_requires_explicit_approval(self):
        with self.assertRaisesRegex(ValueError, "approval"):
            RUNNER.run_checks(CHECKS, invoke=lambda command: self.fail("AWS call prohibited"))

    def test_library_refuses_commands_not_generated_by_the_reviewed_plan(self):
        altered = copy.deepcopy(CHECKS)
        altered[1]["command"][8:10] = ["iam", "create-user"]
        for plan in ([], CHECKS[1:], altered):
            with self.assertRaisesRegex(ValueError, "reviewed 32-check plan"):
                RUNNER.run_checks(plan, invoke=lambda command: self.fail("AWS call prohibited"), approved=True)

    def test_profile_injection_and_unreviewed_operations_fail_before_execution(self):
        with self.assertRaises(ValueError):
            RUNNER.prepared_plan("profile;unexpected-command")
        plan = RUNNER.PLAN.command_plan(RUNNER.PLAN.load_manifest(), "actionbridge-developer")
        plan[-1]["command"][8:10] = ["iam", "create-user"]
        with patch.object(RUNNER.PLAN, "command_plan", return_value=plan), self.assertRaises(ValueError):
            RUNNER.prepared_plan("actionbridge-developer")

    def test_authentication_must_be_exact_expected_user_before_any_other_read(self):
        for identity in (
            {"Account": "195469705669", "Arn": RUNNER.EXPECTED_USER},
            {"Account": RUNNER.EXPECTED_ACCOUNT, "Arn": "arn:aws:iam::631367363628:root"},
            {"Account": RUNNER.EXPECTED_ACCOUNT, "Arn": "arn:aws:sts::631367363628:assumed-role/admin/session"},
            {"Account": RUNNER.EXPECTED_ACCOUNT, "Arn": "arn:aws:iam::631367363628:user/another-user"},
            {"Account": RUNNER.EXPECTED_ACCOUNT, "Root": False},
            {"Account": RUNNER.EXPECTED_ACCOUNT, "Arn": RUNNER.EXPECTED_USER, "UserId": PRIVATE_FIXTURE},
        ):
            calls = []
            def invoke(command):
                calls.append(command)
                return success(identity)
            with self.subTest(identity_fields=list(identity)):
                findings = RUNNER.run_checks(CHECKS, invoke=invoke, approved=True)
                self.assertEqual(len(calls), 1)
                self.assertEqual(len(findings), 32)
                self.assertTrue(all(item["status"] == "UNKNOWN" for item in findings))

    def test_auth_errors_do_not_attempt_login_or_remaining_checks(self):
        for failure in (error(CHECKS[0], "ExpiredToken"), error(CHECKS[0], "AccessDenied"),
                        completed(stderr="Error retrieving credentials: " + PRIVATE_FIXTURE, code=255)):
            calls = []
            findings = RUNNER.run_checks(CHECKS, invoke=lambda command: calls.append(command) or failure, approved=True)
            self.assertEqual(len(calls), 1)
            self.assertTrue(all(item["status"] == "UNKNOWN" for item in findings))
            self.assertNotIn(PRIVATE_FIXTURE, json.dumps(findings))

    def test_scoped_explicit_missing_resources_are_available_but_denials_are_unknown(self):
        for service, operation in (("lambda", "get-function-configuration"), ("dynamodb", "describe-table"), ("iam", "get-role")):
            check = check_for(service, operation)
            missing = "NoSuchEntity" if service == "iam" else "ResourceNotFoundException"
            with self.subTest(service=service):
                finding = RUNNER.classify(check, error(check, missing))
                self.assertEqual(finding["status"], "AVAILABLE")
                self.assertEqual(finding["exit_code"], 254)
                self.assertEqual(finding["error_code"], missing)
                self.assertEqual(RUNNER.classify(check, error(check, "AccessDenied"))["status"], "UNKNOWN")
                self.assertEqual(RUNNER.classify(check, error(check, "ThrottlingException"))["status"], "UNKNOWN")

    def test_actual_cli_v2_lambda_error_is_available(self):
        check = check_for("lambda", "get-function-configuration")
        response = completed(stderr="aws: [ERROR]: An error occurred (ResourceNotFoundException) when calling the GetFunctionConfiguration operation: Function not found", code=254)
        finding = RUNNER.classify(check, response)
        self.assertEqual(finding["status"], "AVAILABLE")
        self.assertEqual(finding["error_code"], "ResourceNotFoundException")
        self.assertEqual(finding["exit_code"], 254)

    def test_legacy_and_cli_v2_formats_recognize_only_service_specific_not_found(self):
        cases = (
            ("lambda", "get-function-configuration", "ResourceNotFoundException", "Function not found"),
            ("dynamodb", "describe-table", "ResourceNotFoundException", "Requested resource not found: Table not found"),
            ("iam", "get-role", "NoSuchEntity", "The role cannot be found"),
            ("cloudformation", "describe-stacks", "ValidationError", "Stack with id actionbridge-dental-staging does not exist"),
        )
        for service, operation, code, message in cases:
            check = check_for(service, operation)
            for prefix in ("", "aws: [ERROR]: "):
                with self.subTest(service=service, prefix=prefix):
                    finding = RUNNER.classify(check, error(check, code, message, prefix=prefix))
                    self.assertEqual(finding["status"], "AVAILABLE")
                    self.assertEqual(finding["error_code"], code)
                    self.assertEqual(finding["exit_code"], 254)

    def test_cli_exit_254_alone_never_establishes_availability(self):
        check = check_for("lambda", "get-function-configuration")
        unknown = (
            completed(code=254),
            completed(stderr="aws: [ERROR]: " + PRIVATE_FIXTURE, code=254),
            completed(stderr="Could not connect to the endpoint URL: " + PRIVATE_FIXTURE, code=254),
            error(check, "SomeUnrecognizedError", PRIVATE_FIXTURE, prefix="aws: [ERROR]: "),
            completed(stdout=PRIVATE_FIXTURE, stderr=error(check, "ResourceNotFoundException", prefix="aws: [ERROR]: ").stderr, code=254),
        )
        findings = [RUNNER.classify(check, response) for response in unknown]
        self.assertTrue(all(item["status"] == "UNKNOWN" for item in findings))
        output = io.StringIO()
        self.assertEqual(RUNNER.render(findings, output), 2)
        self.assertNotIn(PRIVATE_FIXTURE, output.getvalue())

    def test_cli_v2_denials_and_ambiguous_service_absence_remain_unknown(self):
        for prefix in ("", "aws: [ERROR]: "):
            for check in CHECKS:
                with self.subTest(operation=RUNNER.operation(check["command"]), prefix=prefix):
                    finding = RUNNER.classify(check, error(check, "AccessDenied", PRIVATE_FIXTURE, prefix=prefix))
                    self.assertEqual(finding["status"], "UNKNOWN")
                    self.assertEqual(finding["error_code"], "AccessDenied")
            for service, operation, codes in (
                ("s3api", "head-bucket", ("400", "403", "404", "NoSuchBucket")),
                ("sqs", "get-queue-url", ("QueueDoesNotExist", "AWS.SimpleQueueService.NonExistentQueue")),
                ("iam", "get-policy", ("NoSuchEntity",)),
            ):
                for code in codes:
                    check = check_for(service, operation)
                    with self.subTest(service=service, error_code=code, prefix=prefix):
                        self.assertEqual(RUNNER.classify(check, error(check, code, prefix=prefix))["status"], "UNKNOWN")

    def test_not_found_code_must_match_the_requested_service_and_operation(self):
        for service, operation, wrong_code in (
            ("lambda", "get-function-configuration", "NoSuchEntity"),
            ("dynamodb", "describe-table", "NoSuchEntity"),
            ("iam", "get-role", "ResourceNotFoundException"),
            ("cloudformation", "describe-stacks", "ResourceNotFoundException"),
        ):
            check = check_for(service, operation)
            with self.subTest(service=service):
                self.assertEqual(RUNNER.classify(check, error(check, wrong_code, prefix="aws: [ERROR]: "))["status"], "UNKNOWN")
        check = check_for("lambda", "get-function-configuration")
        wrong_operation = error(check_for("dynamodb", "describe-table"), "ResourceNotFoundException", prefix="aws: [ERROR]: ")
        self.assertEqual(RUNNER.classify(check, wrong_operation)["status"], "UNKNOWN")

    def test_cli_v2_wrapper_does_not_accept_mixed_diagnostics_or_malformed_prefixes(self):
        check = check_for("lambda", "get-function-configuration")
        legacy = error(check, "ResourceNotFoundException").stderr.strip()
        actual = "aws: [ERROR]: " + legacy
        responses = (
            "WARNING " + PRIVATE_FIXTURE + "\n" + actual,
            actual + "\nWARNING " + PRIVATE_FIXTURE,
            actual + "\n" + actual,
            "aws [ERROR]: " + legacy,
            "aws: [ERROR] " + legacy,
            "aws: [WARNING]: " + legacy,
            "some-process: [ERROR]: " + legacy,
        )
        findings = [RUNNER.classify(check, completed(stderr=raw, code=254)) for raw in responses]
        self.assertTrue(all(item["status"] == "UNKNOWN" for item in findings))
        self.assertEqual(RUNNER.classify(check, completed(stderr=actual, code=0))["status"], "UNKNOWN")
        output = io.StringIO()
        self.assertEqual(RUNNER.render(findings, output), 2)
        self.assertNotIn(PRIVATE_FIXTURE, output.getvalue())

    def test_cli_v2_cloudformation_still_requires_exact_named_stack_not_exists(self):
        check = check_for("cloudformation", "describe-stacks")
        for message in ("Stack with id another-stack does not exist", "Something does not exist",
                        "Stack with id actionbridge-dental-staging does not exist; " + PRIVATE_FIXTURE):
            finding = RUNNER.classify(check, error(check, "ValidationError", message, prefix="aws: [ERROR]: "))
            self.assertEqual(finding["status"], "UNKNOWN")

    def test_cloudformation_requires_the_exact_missing_stack_message(self):
        check = check_for("cloudformation", "describe-stacks")
        good = "Stack with id actionbridge-dental-staging does not exist"
        self.assertEqual(RUNNER.classify(check, error(check, "ValidationError", good))["status"], "AVAILABLE")
        for message in ("Something does not exist", good + "; other error", "Stack with id another-stack does not exist", "AccessDenied"):
            self.assertEqual(RUNNER.classify(check, error(check, "ValidationError", message))["status"], "UNKNOWN")
        self.assertEqual(RUNNER.classify(check, success([]))["status"], "UNKNOWN")

    def test_s3_queue_and_missing_root_path_policy_errors_are_always_unknown(self):
        for service, operation, codes in (
            ("s3api", "head-bucket", ("400", "403", "404", "NoSuchBucket", "AccessDenied")),
            ("sqs", "get-queue-url", ("QueueDoesNotExist", "AWS.SimpleQueueService.NonExistentQueue", "AccessDenied")),
            ("iam", "get-policy", ("NoSuchEntity", "AccessDenied")),
        ):
            check = check_for(service, operation)
            for code in codes:
                with self.subTest(service=service, code=code):
                    self.assertEqual(RUNNER.classify(check, error(check, code))["status"], "UNKNOWN")

    def test_successful_bodyless_s3_head_is_collision_but_malformed_or_warned_is_unknown(self):
        check = check_for("s3api", "head-bucket")
        for raw in ("", " \n", "{}", "null", '{"Region":null}'):
            self.assertEqual(RUNNER.classify(check, completed(stdout=raw))["status"], "COLLISION")
        for response in (completed(stdout="malformed"), completed(stdout="{}", stderr="WARNING"),
                         completed(stderr="Not Found", code=254)):
            self.assertEqual(RUNNER.classify(check, response)["status"], "UNKNOWN")

    def test_all_resource_successes_are_collisions_without_printing_returned_ids(self):
        fixture = RUNNER.PLAN.load_manifest()
        samples = [
            ("cloudformation", "describe-stacks", [{"Name": fixture["stack_name"], "Id": PRIVATE_FIXTURE, "Status": "CREATE_COMPLETE"}]),
            ("lambda", "get-function-configuration", {"Name": fixture["functions"]["HealthFunction"]["name"], "State": "Active"}),
            ("dynamodb", "describe-table", {"Name": fixture["table"]["name"], "Status": "ACTIVE"}),
            ("s3api", "head-bucket", {"Region": "us-east-1"}),
            ("sqs", "get-queue-url", {"QueueUrl": "https://sqs.us-east-2.amazonaws.com/631367363628/" + fixture["queues"]["work"]}),
            ("iam", "get-role", {"Name": fixture["functions"]["HealthFunction"]["role_name"].upper(), "Path": "/different-path/"}),
            ("iam", "get-policy", {"Name": fixture["functions"]["HealthFunction"]["boundary_policy_name"], "Arn": "arn:aws:iam::631367363628:policy/" + fixture["functions"]["HealthFunction"]["boundary_policy_name"]}),
        ]
        findings = []
        for service, operation, response in samples:
            finding = RUNNER.classify(check_for(service, operation), success(response))
            self.assertEqual(finding["status"], "COLLISION")
            findings.append(finding)
        output = io.StringIO()
        self.assertEqual(RUNNER.render(findings, output), 1)
        self.assertNotIn(PRIVATE_FIXTURE, output.getvalue())

    def test_complete_empty_lists_are_available_and_matching_lists_collide(self):
        for service, operation in (("logs", "describe-log-groups"), ("iam", "list-roles"), ("apigatewayv2", "get-apis"), ("apigateway", "get-rest-apis")):
            check = check_for(service, operation)
            self.assertEqual(RUNNER.classify(check, success(envelope([])))["status"], "AVAILABLE")
        api = check_for("apigatewayv2", "get-apis")
        records = [{"Name": "actionbridge-dental-staging", "Id": "exampleapi1", "Protocol": "HTTP"}]
        self.assertEqual(RUNNER.classify(api, success(envelope(records)))["status"], "COLLISION")
        roles = check_for("iam", "list-roles")
        records = [{"Name": "another-role", "Path": "/actionbridge/staging/actionbridge-dental-staging/"}]
        self.assertEqual(RUNNER.classify(roles, success(envelope(records)))["status"], "COLLISION")

    def test_pagination_tokens_truncation_or_missing_evidence_never_mean_available(self):
        check = check_for("logs", "describe-log-groups")
        responses = [[], {}, {"Records": []}, envelope([], NextToken=PRIVATE_FIXTURE),
                     envelope([], ServiceToken=PRIVATE_FIXTURE), envelope([], Marker=PRIVATE_FIXTURE),
                     envelope([], Position=PRIVATE_FIXTURE), envelope([], Truncated=True),
                     envelope([], Truncated="false"), envelope([{}])]
        for data in responses:
            self.assertEqual(RUNNER.classify(check, success(data))["status"], "UNKNOWN")
        failed_page = completed(stdout=json.dumps(envelope([])), stderr="Pagination failed " + PRIVATE_FIXTURE, code=255)
        self.assertEqual(RUNNER.classify(check, failed_page)["status"], "UNKNOWN")

    def test_malformed_duplicate_or_unexpected_response_never_means_available(self):
        check = check_for("lambda", "get-function-configuration")
        for raw in ("not-json", "null", "{}", "[]", '{"Name":"first","Name":"second"}', "NaN"):
            self.assertEqual(RUNNER.classify(check, completed(stdout=raw))["status"], "UNKNOWN")
        check = check_for("logs", "describe-log-groups")
        duplicate_token = '{"Records":[],"NextToken":"hidden","NextToken":null}'
        self.assertEqual(RUNNER.classify(check, completed(stdout=duplicate_token))["status"], "UNKNOWN")

    def test_errors_and_warnings_remain_visible_but_raw_private_values_are_not(self):
        check = check_for("lambda", "get-function-configuration")
        errors = [error(check, "AccessDenied", PRIVATE_FIXTURE), completed(stderr=PRIVATE_FIXTURE, code=255),
                  completed(stdout='{"Name":"unused"}', stderr="WARNING " + PRIVATE_FIXTURE),
                  completed(stdout=PRIVATE_FIXTURE, stderr=PRIVATE_FIXTURE, code=1)]
        findings = [RUNNER.classify(check, value) for value in errors]
        self.assertTrue(all(item["status"] == "UNKNOWN" for item in findings))
        output = io.StringIO()
        self.assertEqual(RUNNER.render(findings, output), 2)
        self.assertNotIn(PRIVATE_FIXTURE, output.getvalue())
        self.assertIn("AccessDenied", output.getvalue())
        self.assertIn("CLI exit 255", output.getvalue())
        self.assertEqual(output.getvalue().count("raw diagnostics withheld"), 4)

    def test_full_run_retains_all_32_results_and_continues_after_non_auth_failures(self):
        calls = []
        def invoke(command):
            calls.append(command)
            return absent_fixture(command)
        findings = RUNNER.run_checks(CHECKS, invoke=invoke, approved=True)
        self.assertEqual(len(calls), 32)
        self.assertEqual(len(findings), 32)
        self.assertEqual(sum(item["status"] == "AVAILABLE" for item in findings), 23)
        self.assertEqual(sum(item["status"] == "UNKNOWN" for item in findings), 9)
        output = io.StringIO()
        self.assertEqual(RUNNER.render(findings, output), 2)
        self.assertIn("AVAILABLE=23, COLLISION=0, UNKNOWN=9", output.getvalue())
        self.assertIn("CLI exit 254", output.getvalue())

    def test_cli_v2_full_mocked_plan_preserves_safe_service_classification(self):
        calls = []
        def invoke(command):
            calls.append(command)
            response = absent_fixture(command)
            if response.returncode:
                response.stderr = "aws: [ERROR]: " + response.stderr.strip()
            return response
        findings = RUNNER.run_checks(CHECKS, invoke=invoke, approved=True)
        self.assertEqual(len(calls), 32)
        self.assertEqual(len(findings), 32)
        self.assertEqual(sum(item["status"] == "AVAILABLE" for item in findings), 23)
        self.assertEqual(sum(item["status"] == "UNKNOWN" for item in findings), 9)
        output = io.StringIO()
        self.assertEqual(RUNNER.render(findings, output), 2)
        self.assertIn("AVAILABLE=23, COLLISION=0, UNKNOWN=9", output.getvalue())
        self.assertNotIn(PRIVATE_FIXTURE, output.getvalue())

    def test_timeouts_process_errors_and_interruptions_are_reported_not_suppressed(self):
        for raised in (subprocess.TimeoutExpired(["aws"], 45, output=PRIVATE_FIXTURE), FileNotFoundError(PRIVATE_FIXTURE), OSError(PRIVATE_FIXTURE)):
            calls = []
            def invoke(command):
                calls.append(command)
                if len(calls) == 1:
                    return absent_fixture(command)
                raise raised
            findings = RUNNER.run_checks(CHECKS, invoke=invoke, approved=True)
            self.assertEqual(len(calls), 32)
            self.assertTrue(all(item["status"] == "UNKNOWN" for item in findings[1:]))
            self.assertNotIn(PRIVATE_FIXTURE, json.dumps(findings))
        calls = []
        def interrupted(command):
            calls.append(command)
            if len(calls) == 1:
                return absent_fixture(command)
            raise KeyboardInterrupt()
        findings = RUNNER.run_checks(CHECKS, invoke=interrupted, approved=True)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(findings), 32)
        self.assertEqual(findings[-1]["error_code"], "SKIPPED")

    def test_subprocess_is_shell_free_bounded_noninteractive_and_endpoint_protected(self):
        with patch.dict(os.environ, {"AWS_ENDPOINT_URL": "https://untrusted.invalid", "AWS_ENDPOINT_URL_STS": "https://untrusted.invalid", "AWS_PROFILE": "other-profile", "AWS_DEFAULT_PROFILE": "other-profile"}), \
                patch.object(RUNNER, "ensure_cli_history_safe") as history_guard, \
                patch.object(RUNNER.subprocess, "run", return_value=success({})) as invoke:
            RUNNER.call_cli(CHECKS[0]["command"])
        history_guard.assert_called_once_with("actionbridge-developer")
        args, kwargs = invoke.call_args
        self.assertEqual(args[0], CHECKS[0]["command"])
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["timeout"], 45)
        self.assertTrue(kwargs["capture_output"])
        environment = kwargs["env"]
        self.assertFalse(any(key.startswith("AWS_ENDPOINT_URL") for key in environment))
        for key in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
            self.assertNotIn(key, environment)
        self.assertEqual(environment["AWS_IGNORE_CONFIGURED_ENDPOINT_URLS"], "true")
        self.assertEqual(environment["AWS_EC2_METADATA_DISABLED"], "true")
        self.assertEqual(environment["AWS_CLI_AUTO_PROMPT"], "off")
        self.assertEqual(environment["AWS_MAX_ATTEMPTS"], "1")
        for check in CHECKS:
            self.assertIn("--cli-connect-timeout", check["command"])
            self.assertIn("--cli-read-timeout", check["command"])
            self.assertIn("--no-cli-auto-prompt", check["command"])
            self.assertNotIn("--no-paginate", check["command"])
            self.assertNotIn("--max-items", check["command"])

    def test_cli_history_guard_accepts_only_disabled_or_absent_in_selected_scopes(self):
        valid = (
            "", "[default]\nregion = us-east-2\n",
            "[default]\ncli_history = disabled\n[profile actionbridge-developer]\ncli_history = disabled\n",
            "[DEFAULT]\ncli_history = disabled\n[profile actionbridge-developer]\nregion = us-east-2\n",
            "[profile another-profile]\ncli_history = enabled\n[profile actionbridge-developer]\nregion = us-east-2\n",
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic-config"
            for content in valid:
                path.write_text(content)
                RUNNER.ensure_cli_history_safe("actionbridge-developer", path, Path(folder) / "absent-credentials")
            RUNNER.ensure_cli_history_safe("actionbridge-developer", Path(folder) / "absent-config", Path(folder) / "absent-credentials")

    def test_cli_history_guard_rejects_enabled_unknown_and_malformed_without_showing_values(self):
        unsafe = (
            "[default]\ncli_history = enabled\n",
            "[profile actionbridge-developer]\ncli_history = enabled\n",
            "[DEFAULT]\ncli_history = enabled\n[profile actionbridge-developer]\ncli_history = disabled\n",
            "[default]\ncli_history = enabled\n[profile actionbridge-developer]\ncli_history = disabled\n",
            "[actionbridge-developer]\ncli_history = enabled\n",
            "[profile actionbridge-developer]\ncli_history = " + PRIVATE_FIXTURE + "\n",
            "[profile actionbridge-developer]\ncli_history =\n",
            "not a valid section " + PRIVATE_FIXTURE,
            "[default]\ncli_history = disabled\ncli_history = enabled\n",
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic-config"
            for content in unsafe:
                path.write_text(content)
                with self.assertRaises(RUNNER.UnsafeCLIHistory) as raised:
                    RUNNER.ensure_cli_history_safe("actionbridge-developer", path, Path(folder) / "absent-credentials")
                self.assertNotIn(PRIVATE_FIXTURE, str(raised.exception))
                self.assertNotIn(str(path), str(raised.exception))

    def test_cli_history_guard_unreadable_or_invalid_encoding_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic-config"
            path.write_bytes(b"\xff\xfe\xff")
            with self.assertRaises(RUNNER.UnsafeCLIHistory):
                RUNNER.ensure_cli_history_safe("actionbridge-developer", path, Path(folder) / "absent-credentials")
            with patch.object(Path, "open", side_effect=PermissionError(PRIVATE_FIXTURE)):
                with self.assertRaises(RUNNER.UnsafeCLIHistory) as raised:
                    RUNNER.ensure_cli_history_safe("actionbridge-developer", path, Path(folder) / "absent-credentials")
                self.assertNotIn(PRIVATE_FIXTURE, str(raised.exception))

    def test_cli_history_guard_honors_only_synthetic_config_override_in_test(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic-config"
            path.write_text("[default]\ncli_history = enabled\n")
            with patch.dict(os.environ, {"AWS_CONFIG_FILE": str(path), "AWS_SHARED_CREDENTIALS_FILE": str(Path(folder) / "absent-credentials")}):
                with self.assertRaises(RUNNER.UnsafeCLIHistory):
                    RUNNER.ensure_cli_history_safe("actionbridge-developer")
        with patch.dict(os.environ, {"AWS_CONFIG_FILE": "", "AWS_SHARED_CREDENTIALS_FILE": "/synthetic-path-not-read"}):
            with self.assertRaises(RUNNER.UnsafeCLIHistory):
                RUNNER.ensure_cli_history_safe("actionbridge-developer")

    def test_shared_credentials_history_is_checked_even_when_config_is_absent_or_disabled(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "synthetic-config"
            credentials = Path(folder) / "synthetic-credentials"
            credentials.write_text("[actionbridge-developer]\ncli_history = enabled\naws_secret_access_key = " + PRIVATE_FIXTURE + "\n")
            for config_content in (None, "[profile actionbridge-developer]\ncli_history = disabled\n"):
                if config_content is not None:
                    config.write_text(config_content)
                with self.assertRaises(RUNNER.UnsafeCLIHistory) as raised:
                    RUNNER.ensure_cli_history_safe("actionbridge-developer", config, credentials)
                self.assertNotIn(PRIVATE_FIXTURE, str(raised.exception))
            config.write_text("[profile actionbridge-developer]\ncli_history = disabled\n")
            credentials.write_text("[actionbridge-developer]\ncli_history = disabled\naws_secret_access_key = " + PRIVATE_FIXTURE + "\n")
            RUNNER.ensure_cli_history_safe("actionbridge-developer", config, credentials)
            with patch.dict(os.environ, {"AWS_CONFIG_FILE": str(config), "AWS_SHARED_CREDENTIALS_FILE": str(credentials)}):
                RUNNER.ensure_cli_history_safe("actionbridge-developer")
                credentials.write_text("[DEFAULT]\ncli_history = enabled\n[actionbridge-developer]\ncli_history = disabled\n")
                with self.assertRaises(RUNNER.UnsafeCLIHistory):
                    RUNNER.ensure_cli_history_safe("actionbridge-developer")

    def test_explicit_history_guard_paths_must_both_be_supplied(self):
        with self.assertRaises(RUNNER.UnsafeCLIHistory):
            RUNNER.ensure_cli_history_safe("actionbridge-developer", "/synthetic-config-not-read")
        with self.assertRaises(RUNNER.UnsafeCLIHistory):
            RUNNER.ensure_cli_history_safe("actionbridge-developer", credentials_path="/synthetic-credentials-not-read")

    def test_unsafe_cli_history_blocks_every_subprocess_and_all_remaining_reads(self):
        with patch.object(RUNNER, "ensure_cli_history_safe", side_effect=RUNNER.UnsafeCLIHistory()), \
                patch.object(RUNNER.subprocess, "run", side_effect=AssertionError("AWS execution prohibited")) as invoke:
            findings = RUNNER.run_checks(CHECKS, invoke=RUNNER.call_cli, approved=True)
        invoke.assert_not_called()
        self.assertEqual(len(findings), 32)
        self.assertEqual(findings[0]["error_code"], "CLI_HISTORY_UNSAFE")
        self.assertTrue(all(item["status"] == "UNKNOWN" for item in findings))


if __name__ == "__main__":
    unittest.main()
