#!/usr/bin/env python3
"""Run the reviewed collision reads only with explicit approval and existing authentication.

Default use is offline. This program never logs in, changes permissions/resources,
reads private parameters, writes reports or prints raw AWS responses/diagnostics.
"""
import argparse
import configparser
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("staging_collision_plan", HERE / "collision-checks.py")
PLAN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLAN)
EXPECTED_ACCOUNT = "631367363628"
EXPECTED_USER = "arn:aws:iam::631367363628:user/actionbridge-developer"
EXPECTED_REGION = "us-east-2"
PROCESS_TIMEOUT = 45
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 10
MAX_RESPONSE = 2 * 1024 * 1024
OPERATIONS = {
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
SAFE_CODES = {
    "AccessDenied", "AccessDeniedException", "UnauthorizedOperation", "UnauthorizedException",
    "AuthFailure", "ExpiredToken", "ExpiredTokenException", "InvalidClientTokenId",
    "UnrecognizedClientException", "SignatureDoesNotMatch", "RequestExpired", "InvalidSignatureException",
    "TooManyRequestsException", "Throttling", "ThrottlingException", "RequestLimitExceeded",
    "ServiceUnavailable", "ServiceUnavailableException", "InternalError", "InternalFailure",
    "InternalServerError", "ResourceNotFoundException", "NoSuchEntity", "NoSuchEntityException",
    "ValidationError", "AWS.SimpleQueueService.NonExistentQueue", "QueueDoesNotExist",
    "NonExistentQueue", "400", "403", "404", "NoSuchBucket", "NotFound", "Forbidden",
    "PermanentRedirect", "IllegalLocationConstraintException",
}
# A text error header is one line. CLI v2's enhanced formatter can append a
# separate modeled-details section; parse that envelope explicitly below.
ERROR = re.compile(
    r"\s*(?:aws:[ \t]+\[ERROR\]:[ \t]+)?"
    r"An error occurred \(([^()\r\n]+)\) when calling the ([A-Za-z0-9]+) operation: ([^\r\n]*)\s*\Z"
)
# Only these exact operation/code pairs establish an unambiguous missing name.
# CloudFormation additionally requires its exact target-stack missing message.
# Collection errors, SQS absence, S3 HEAD errors and root-path policy absence
# remain UNKNOWN even when their error code or CLI exit status is recognized.
NAMED_RESOURCE_NOT_FOUND = {
    ("lambda", "get-function-configuration"): frozenset({"ResourceNotFoundException"}),
    ("dynamodb", "describe-table"): frozenset({"ResourceNotFoundException"}),
    ("iam", "get-role"): frozenset({"NoSuchEntity"}),
}
PAGINATION_FIELDS = "NextToken:NextToken, ServiceToken:nextToken, Marker:Marker, Position:position, Truncated:IsTruncated"


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally repeats supplied arguments; do not echo accidental secrets.
        self.exit(2, "Argument error. Use --help; no AWS checks were run.\n")


class UnsafeCLIHistory(Exception):
    """Static diagnostic only; configuration contents must never leave the guard."""


def operation(command):
    return tuple(command[8:10])


def operand(command, flag):
    return command[command.index(flag) + 1]


def envelope(records):
    return "{Records:" + records + ", " + PAGINATION_FIELDS + "}"


def prepared_plan(profile, *, check="all"):
    """Use only the local reviewed plan, with private identity and pagination projections."""
    resources = PLAN.load_manifest()
    checks = PLAN.command_plan(resources, profile)
    if len(checks) != 32 or operation(checks[0]["command"]) != ("sts", "get-caller-identity"):
        raise ValueError("Reviewed check inventory changed; review the runner first")
    expected_prefix = ["aws", "--profile", profile, "--region", EXPECTED_REGION, "--no-cli-pager", "--output", "json"]
    for entry in checks:
        command = list(entry["command"])
        if command[:8] != expected_prefix or operation(command) not in OPERATIONS:
            raise ValueError("Unreviewed command in collision plan")
        if command[-2] != "--query" or command.count("--query") != 1:
            raise ValueError("Unreviewed response projection in collision plan")
        if any(flag in command for flag in ("--endpoint-url", "--debug", "--no-sign-request", "--no-paginate", "--max-items", "--starting-token")):
            raise ValueError("Unsafe option in collision plan")
        kind = operation(command)
        if kind == ("sts", "get-caller-identity"):
            command[-1] = "{Account:Account,Arn:Arn}"
        elif kind == ("ec2", "describe-regions"):
            command[-1] = envelope("Regions[].{Region:RegionName,Status:OptInStatus}")
        elif kind == ("logs", "describe-log-groups"):
            group = operand(command, "--log-group-name-prefix")
            command[-1] = envelope("logGroups[?logGroupName == '" + group + "'].{Name:logGroupName}")
        elif kind == ("iam", "list-roles"):
            command[-1] = envelope("Roles[].{Name:RoleName,Path:Path}")
        elif kind == ("apigatewayv2", "get-apis"):
            name = resources["api"]["name"]
            command[-1] = envelope("Items[?Name == '" + name + "'].{Name:Name,Id:ApiId,Protocol:ProtocolType}")
        elif kind == ("apigateway", "get-rest-apis"):
            name = resources["api"]["name"]
            command[-1] = envelope("items[?name == '" + name + "'].{Name:name,Id:id}")
        command += ["--no-cli-auto-prompt", "--cli-connect-timeout", str(CONNECT_TIMEOUT), "--cli-read-timeout", str(READ_TIMEOUT)]
        entry["command"] = command
    # Validate/build the full reviewed plan before selecting a fixed smoke read.
    # This is not an arbitrary resource or command selector.
    if check == "health":
        health = resources["functions"]["HealthFunction"]["name"]
        selected = [item for item in checks if operation(item["command"]) == ("lambda", "get-function-configuration")
                    and operand(item["command"], "--function-name") == health]
        if len(selected) != 1:
            raise ValueError("Reviewed health check is missing or duplicated")
        return [checks[0], selected[0]]
    if check != "all":
        raise ValueError("Only all or health checks are supported")
    return checks


def safe_environment():
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("AWS_ENDPOINT_URL") and key not in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE")}
    environment.update({
        "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS": "true", "AWS_EC2_METADATA_DISABLED": "true",
        "AWS_PAGER": "", "AWS_CLI_AUTO_PROMPT": "off", "AWS_MAX_ATTEMPTS": "1",
        "AWS_RETRY_MODE": "standard", "AWS_STS_REGIONAL_ENDPOINTS": "regional",
        # --output json only affects stdout. Error formatting is independent.
        # Modern CLI v2 honors this; older releases retain the text fallback.
        "AWS_CLI_ERROR_FORMAT": "json",
    })
    return environment


def ensure_cli_history_safe(profile, config_path=None, credentials_path=None):
    """Read local configuration only, failing closed before CLI response logging.

    This is called only after explicit execution approval. Both config and shared
    credentials can contribute profile settings. Tests supply both synthetic
    paths or mock the guard; no real credentials/config are inspected by tests.
    RawConfigParser disables interpolation, and no path/value/error is printed.
    """
    try:
        if (config_path is None) != (credentials_path is None):
            raise UnsafeCLIHistory()  # Explicit inspection must supply both paths.
        if config_path is None:
            paths = []
            for variable, fallback in (("AWS_CONFIG_FILE", "~/.aws/config"),
                                       ("AWS_SHARED_CREDENTIALS_FILE", "~/.aws/credentials")):
                configured = os.environ.get(variable, fallback)
                if not configured.strip():
                    raise UnsafeCLIHistory()
                paths.append(Path(os.path.expandvars(os.path.expanduser(configured))))
        else:
            paths = [Path(config_path), Path(credentials_path)]
        for path in paths:
            parser = configparser.RawConfigParser(interpolation=None, strict=True)
            try:
                with path.open("r", encoding="utf-8") as handle:
                    parser.read_file(handle)
            except FileNotFoundError:
                continue  # An absent source cannot enable CLI history.
            values = []
            if "cli_history" in parser.defaults():
                values.append(parser.defaults()["cli_history"])
            for section in {"default", "profile " + profile, profile}:
                if parser.has_section(section) and parser.has_option(section, "cli_history"):
                    values.append(parser.get(section, "cli_history", raw=True))
            if any(not isinstance(value, str) or value.strip().lower() != "disabled" for value in values):
                raise UnsafeCLIHistory()
    except UnsafeCLIHistory:
        raise UnsafeCLIHistory("Local CLI history configuration is unsafe or unverifiable") from None
    except (OSError, ValueError, TypeError, UnicodeError, configparser.Error):
        raise UnsafeCLIHistory("Local CLI history configuration is unsafe or unverifiable") from None


def call_cli(command):
    ensure_cli_history_safe(operand(command, "--profile"))
    return subprocess.run(command, shell=False, stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=PROCESS_TIMEOUT,
                          env=safe_environment(), check=False)


def result(check, status, reason, exit_code=None, error_code=None, diagnostics=False):
    return {"label": check["label"], "status": status, "reason": reason,
            "exit_code": exit_code, "error_code": error_code, "diagnostics_withheld": diagnostics}


def no_duplicate_keys(pairs):
    answer = {}
    for key, value in pairs:
        if key in answer:
            raise ValueError("Duplicate response field")
        answer[key] = value
    return answer


def parse_json(raw):
    if not isinstance(raw, str) or len(raw) > MAX_RESPONSE:
        raise ValueError("Invalid response size")
    return json.loads(raw, object_pairs_hook=no_duplicate_keys,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Invalid JSON constant")))


def service_error(stderr, kind):
    """Return safe code, operation, message, and whether the whole error is valid.

    Message/model fields are transient classification inputs only; they must
    never enter result dictionaries, diagnostic output, logs or report files.
    A recognized header code can still be reported when an unsafe tail forces
    UNKNOWN. Recognition and an availability finding are separate decisions.
    """
    if not isinstance(stderr, str) or len(stderr) > MAX_RESPONSE:
        return None, None, "", False
    text = stderr.strip()
    if text.startswith("{"):
        try:
            document = parse_json(text)
        except (ValueError, TypeError, RecursionError):
            return None, None, "", False
        if not isinstance(document, dict):
            return None, None, "", False
        candidate = document.get("Code")
        code = candidate if isinstance(candidate, str) and candidate in SAFE_CODES else None
        # These reads have only the standard error fields and Lambda's modeled
        # scalar Type. Do not silently accept an extra error object or payload.
        valid = (code is not None and {"Code", "Message"} <= set(document)
                 and set(document) <= {"Code", "Message", "Type"}
                 and isinstance(document["Message"], str)
                 and ("Type" not in document or isinstance(document["Type"], str)))
        return code, None, document.get("Message", "") if valid else "", valid
    lines = text.splitlines()
    if not lines:
        return None, None, "", False
    header = ERROR.fullmatch(lines[0])
    if not header:
        return None, None, "", False
    code = header.group(1) if header.group(1) in SAFE_CODES else None
    tail = [line.strip() for line in lines[1:] if line.strip()]
    valid_tail = not tail
    if tail and kind == ("lambda", "get-function-configuration"):
        # Documented CLI v2 enhanced Lambda errors append exactly this section.
        # Arbitrary warning/network text or another error header is not ignored.
        valid_tail = (len(tail) == 2 and tail[0] == "Additional error details:"
                      and re.fullmatch(r"Type: [^\r\n]+", tail[1]) is not None)
    return code, header.group(2), header.group(3), code is not None and valid_tail


def complete_records(data):
    if not isinstance(data, dict) or not isinstance(data.get("Records"), list):
        raise ValueError("Malformed list response")
    required = {"Records", "NextToken", "ServiceToken", "Marker", "Position", "Truncated"}
    if set(data) != required:
        raise ValueError("Missing pagination evidence")
    for field in ("NextToken", "ServiceToken", "Marker", "Position"):
        if data[field] is not None and data[field] != "":
            raise ValueError("Incomplete pagination")
    if data["Truncated"] is not None and data["Truncated"] is not False:
        raise ValueError("Incomplete pagination")
    return data["Records"]


def named_record(data, expected, extra=None, insensitive=False):
    if not isinstance(data, dict) or not isinstance(data.get("Name"), str):
        return False
    left, right = data["Name"], expected
    matches = left.casefold() == right.casefold() if insensitive else left == right
    return matches and (extra is None or extra(data))


def classify_success(check, data):
    command = check["command"]
    kind = operation(command)
    collision = "COLLISION", "The requested name exists; owner review is required"
    if kind == ("sts", "get-caller-identity"):
        if (isinstance(data, dict) and set(data) == {"Account", "Arn"}
                and data["Account"] == EXPECTED_ACCOUNT and data["Arn"] == EXPECTED_USER):
            return "AVAILABLE", "Authentication verified for the expected IAM user and account"
        return "UNKNOWN", "Authentication/account/principal gate failed; remaining checks are blocked"
    if kind == ("ec2", "describe-regions"):
        records = complete_records(data)
        statuses = {"opt-in-not-required", "opted-in", "not-opted-in"}
        valid = all(isinstance(item, dict) and set(item) == {"Region", "Status"}
                    and isinstance(item["Region"], str) and re.fullmatch(r"[a-z]{2}(?:-[a-z0-9]+)+-\d", item["Region"])
                    and item["Status"] in statuses for item in records)
        enabled = any(item.get("Region") == EXPECTED_REGION and item.get("Status") != "not-opted-in"
                      for item in records if isinstance(item, dict))
        if valid and enabled:
            return "AVAILABLE", "Region coverage read completed; this is not an account inventory"
    elif kind == ("cloudformation", "describe-stacks"):
        expected = operand(command, "--stack-name")
        if isinstance(data, list) and data and all(named_record(item, expected) for item in data):
            return collision
    elif kind == ("lambda", "get-function-configuration"):
        if named_record(data, operand(command, "--function-name")):
            return collision
    elif kind == ("dynamodb", "describe-table"):
        if named_record(data, operand(command, "--table-name")):
            return collision
    elif kind == ("sqs", "get-queue-url"):
        expected = f"https://sqs.{EXPECTED_REGION}.amazonaws.com/{EXPECTED_ACCOUNT}/" + operand(command, "--queue-name")
        if isinstance(data, dict) and data.get("QueueUrl") == expected:
            return collision
    elif kind == ("s3api", "head-bucket"):
        # HEAD is bodyless; older CLI models can produce null/{} despite success.
        if data is None or data == {}:
            return collision
        if isinstance(data, dict) and set(data) == {"Region"} and (data["Region"] is None or isinstance(data["Region"], str)):
            return collision
    elif kind == ("iam", "get-role"):
        if named_record(data, operand(command, "--role-name"), lambda item: isinstance(item.get("Path"), str)
                        and item["Path"].startswith("/") and item["Path"].endswith("/"), insensitive=True):
            return collision
    elif kind == ("iam", "get-policy"):
        expected = operand(command, "--policy-arn")
        if named_record(data, expected.rsplit("/", 1)[-1], lambda item: item.get("Arn") == expected, insensitive=True):
            return collision
    elif kind in (("logs", "describe-log-groups"), ("iam", "list-roles"),
                  ("apigatewayv2", "get-apis"), ("apigateway", "get-rest-apis")):
        records = complete_records(data)
        if kind == ("logs", "describe-log-groups"):
            expected = operand(command, "--log-group-name-prefix")
            valid = all(named_record(item, expected) and set(item) == {"Name"} for item in records)
        elif kind == ("iam", "list-roles"):
            prefix = operand(command, "--path-prefix")
            valid = all(isinstance(item, dict) and set(item) == {"Name", "Path"}
                        and isinstance(item["Name"], str) and item["Name"]
                        and isinstance(item["Path"], str) and item["Path"].startswith(prefix) for item in records)
        else:
            expected = PLAN.load_manifest()["api"]["name"]
            valid = all(named_record(item, expected) and isinstance(item.get("Id"), str) and item["Id"]
                        and (kind[0] != "apigatewayv2" or item.get("Protocol") in ("HTTP", "WEBSOCKET")) for item in records)
        if valid:
            return collision if records else ("AVAILABLE", "Complete exact-name/path list contains no matches")
    return "UNKNOWN", "Unexpected or incomplete response schema; no availability finding"


def classify(check, completed):
    if type(completed.returncode) is not int:
        return result(check, "UNKNOWN", "Malformed process result")
    code = completed.returncode
    stdout, stderr = completed.stdout, completed.stderr
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        return result(check, "UNKNOWN", "Malformed process output", code)
    if code != 0:
        kind = operation(check["command"])
        recognized, error_operation, message, valid_envelope = service_error(stderr, kind)
        error_code = recognized or "UNRECOGNIZED_CLI_OR_AWS_ERROR"
        valid_error = (valid_envelope and not stdout.strip()
                       and (error_operation is None or error_operation == OPERATIONS[kind]))
        if valid_error:
            if error_code in NAMED_RESOURCE_NOT_FOUND.get(kind, ()):
                reason = ("Account-global role name returned a not-found response" if kind == ("iam", "get-role")
                          else "Exact named resource returned a not-found response")
                return result(check, "AVAILABLE", reason, code, error_code, True)
            if kind == ("cloudformation", "describe-stacks") and error_code == "ValidationError":
                missing = "Stack with id " + operand(check["command"], "--stack-name") + " does not exist"
                if message.strip() in (missing, missing + "."):
                    return result(check, "AVAILABLE", "Exact stack name returned the expected not-exists response", code, error_code, True)
        # SQS nonexistence can hide denied access; an absent root-path policy ARN
        # cannot rule out the same global policy name under another IAM path.
        return result(check, "UNKNOWN", "Read failed; denied, ambiguous or unverified absence is not availability", code, error_code, True)
    if stderr.strip():
        return result(check, "UNKNOWN", "CLI produced diagnostics despite exit zero; response is not accepted", code,
                      "CLI_DIAGNOSTICS", True)
    if operation(check["command"]) == ("s3api", "head-bucket") and not stdout.strip():
        return result(check, "COLLISION", "Successful owner-checked HEAD confirms the bucket exists; response has no body", code)
    try:
        status, reason = classify_success(check, parse_json(stdout))
    except (ValueError, TypeError, KeyError, RecursionError):
        status, reason = "UNKNOWN", "Malformed response or incomplete pagination; no availability finding"
    return result(check, status, reason, code)


def run_checks(checks, invoke=call_cli, *, approved=False, check="all"):
    if not approved:
        raise ValueError("Explicit read-only execution approval is required")
    try:
        profile = operand(checks[0]["command"], "--profile")
        trusted = prepared_plan(profile, check=check)
    except (ValueError, KeyError, TypeError, IndexError):
        raise ValueError("Only the reviewed 32-check plan or fixed health verification can be executed") from None
    if checks != trusted:
        raise ValueError("Only the reviewed 32-check plan or fixed health verification can be executed")
    results = []
    for index, check in enumerate(checks):
        try:
            finding = classify(check, invoke(check["command"]))
        except UnsafeCLIHistory:
            finding = result(check, "UNKNOWN", "Local CLI history must be disabled and verifiable before reads",
                             error_code="CLI_HISTORY_UNSAFE")
        except subprocess.TimeoutExpired:
            finding = result(check, "UNKNOWN", "Read timed out; partial output is not accepted", error_code="TIMEOUT", diagnostics=True)
        except FileNotFoundError:
            finding = result(check, "UNKNOWN", "AWS CLI executable is unavailable", error_code="CLI_UNAVAILABLE")
        except OSError:
            finding = result(check, "UNKNOWN", "CLI process could not start or complete", error_code="PROCESS_ERROR")
        except KeyboardInterrupt:
            results.append(result(check, "UNKNOWN", "Interrupted; no availability finding", error_code="INTERRUPTED"))
            results += [result(item, "UNKNOWN", "Skipped after interruption", error_code="SKIPPED") for item in checks[index + 1:]]
            break
        results.append(finding)
        if index == 0 and finding["status"] != "AVAILABLE":
            results += [result(item, "UNKNOWN", "Skipped: authentication/account/principal gate did not pass", error_code="AUTH_GATE_BLOCKED")
                        for item in checks[1:]]
            break
    return results


def render(results, stream=None, *, diagnostic=False):
    stream = stream or sys.stdout
    for index, finding in enumerate(results, 1):
        if diagnostic:
            # Diagnostic mode is JSON-lines only, with this two-field contract.
            # A recognized code does not imply the response proves absence.
            print(json.dumps({"aws_error_code": finding["error_code"] if finding["error_code"] in SAFE_CODES else None,
                              "classification": finding["status"]}), file=stream)
            continue
        details = finding["reason"]
        if finding["exit_code"] is not None:
            details += f"; CLI exit {finding['exit_code']}"
        if finding["error_code"]:
            details += "; error " + finding["error_code"]
        if finding["diagnostics_withheld"]:
            details += "; raw diagnostics withheld to protect private values"
        print(f"[{index:02d}/{len(results)}] {finding['status']} {finding['label']}: {details}", file=stream)
    counts = {status: sum(item["status"] == status for item in results) for status in ("AVAILABLE", "COLLISION", "UNKNOWN")}
    if not diagnostic:
        print("Summary: " + ", ".join(f"{key}={value}" for key, value in counts.items()), file=stream)
        print("Identity/Region AVAILABLE means the prerequisite read succeeded, not that resource names are free.", file=stream)
        print("No finding authorizes creation. UNKNOWN requires owner review; the wider inventory remains incomplete.", file=stream)
    return 2 if counts["UNKNOWN"] else 1 if counts["COLLISION"] else 0


def main(argv=None):
    parser = SafeParser(description=__doc__)
    parser.add_argument("--profile", help="Existing authenticated profile for the actionbridge-developer IAM user")
    parser.add_argument("--check", choices=("all", "health"), default="all", help="All 32 reads, or only authentication plus the fixed staging health-function read")
    parser.add_argument("--diagnostic", action="store_true", help="Print sanitized AWS error-code/classification pairs only; never raw diagnostics")
    parser.add_argument("--execute", action="store_true", help="Execute the reviewed read-only checks, subject to the authentication gate")
    parser.add_argument("--approve-read-only-checks", action="store_true", help="Assert explicit owner approval for the selected reviewed reads after policy review/grant")
    args = parser.parse_args(argv)
    if not args.execute and not args.approve_read_only_checks:
        count = 2 if args.check == "health" else 32
        print(f"OFFLINE: {count} planned read-only checks. No AWS commands were executed.")
        print("After owner policy approval/grant and separate authentication, use --profile, --execute and --approve-read-only-checks together.")
        return 0
    if not args.execute or not args.approve_read_only_checks or not args.profile:
        parser.error("Both approval flags and an existing authenticated profile are required")
    try:
        checks = prepared_plan(args.profile, check=args.check)
    except (ValueError, KeyError, OSError, TypeError):
        print("Reviewed collision plan/profile validation failed. No AWS commands were executed.", file=sys.stderr)
        return 2
    if not args.diagnostic:
        print("Approved read-only run: authentication is checked first; no login, writes or raw AWS responses are produced.")
    return render(run_checks(checks, approved=True, check=args.check), diagnostic=args.diagnostic)


if __name__ == "__main__":
    raise SystemExit(main())
