#!/usr/bin/env python3
"""Read back the approved owner KMS repair without changing AWS state.

Run only after the owner access-stack update reaches UPDATE_COMPLETE. All AWS
requests are serialized, use the dedicated keyless deployment profile, have
one attempt, and are read-only. No IAM/KMS edits, grant cleanup, deployment,
Lambda invocation, change-set creation or traffic activation is implemented.
"""
import argparse
import copy
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


V = module("delegation_verification", HERE / "verify-delegated-access.py")
K = module("kms_repair", HERE / "prepare-kms-repair.py")
D = K.D
PROFILE = "actionbridge-staging-deployer"
EXTRA_READS = frozenset({("kms", "describe-key"), ("kms", "get-key-policy"), ("kms", "list-grants"),
                         ("cloudformation", "get-template")})
READS = frozenset(V.READS) | EXTRA_READS
LEGACY_DEFAULTS = {"identity-01": "v1", "identity-02": "v1", "identity-03": "v5", "guardrails-01": "v2", "guardrails-02": "v3"}
CHANGED_OWNER_POLICIES = {"ExecutionCeiling1", "ExecutionCeiling2", "ExecutionCeiling3", "DeployerPolicy1", "DeployerPolicy3", "DeployerPolicy4"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_read_scope(service, operation, arguments):
    require((service, operation) in READS, "Operation is outside the read-only allowlist")
    require(not any(arg.startswith(("--profile", "--endpoint", "--cli-input", "--no-sign-request")) for arg in arguments), "Profile/endpoint/input overrides are forbidden")
    if (service, operation) in EXTRA_READS:
        flag = "--key-id" if service == "kms" else "--stack-name"
        require(flag in arguments and arguments.count(flag) == 1, "Exact resource flag is required")
        require(arguments.index(flag) + 1 < len(arguments), "Exact resource value is required")
        value = arguments[arguments.index(flag) + 1]
        require(value in K.KEYS if service == "kms" else value == K.ACCESS_STACK_ID, "Unapproved key or owner-stack resource")
        expected = [flag, value]
        if operation == "get-key-policy":
            expected += ["--policy-name", "default"]
        elif operation == "get-template":
            expected += ["--template-stage", "Original"]
        require(list(arguments) == expected, "Unexpected extra read arguments")


class ReadOnlyAws:
    """Compose the existing reader; add four scoped reads without altering it."""
    def __init__(self, profile=PROFILE, base_reader=None, runner=None):
        V.validate_profile(profile)
        self.profile = profile
        self.base = base_reader if base_reader is not None else V.AwsReads(profile)
        self.runner = runner if runner is not None else subprocess.run

    def __call__(self, service, operation, *arguments):
        validate_read_scope(service, operation, arguments)
        if (service, operation) not in EXTRA_READS:
            return self.base(service, operation, *arguments)
        with (ROOT / ".staging/delegated-access-cli.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.runner(["aws", service, operation, *arguments, "--profile", self.profile, "--region", D.REGION,
                                  "--output", "json", "--no-cli-pager", "--cli-connect-timeout", "10", "--cli-read-timeout", "30"],
                                 capture_output=True, text=True, timeout=45,
                                 env={**os.environ, "AWS_MAX_ATTEMPTS": "1", "AWS_PAGER": "", "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS": "true"})
        if result.returncode:
            match = re.search(r"An error occurred \(([A-Za-z0-9_.-]+)\)", result.stderr)
            raise V.AwsReadError(service, operation, match.group(1) if match else "CLI_AUTH_OR_TRANSPORT_ERROR")
        return json.loads(result.stdout)


def parse_document(value):
    result = json.loads(value) if isinstance(value, str) else value
    require(isinstance(result, dict), "Expected a complete JSON document")
    return result


def resolve_policy(value, boundary_arns, app_arn, access_stack_id):
    if isinstance(value, list):
        return [resolve_policy(item, boundary_arns, app_arn, access_stack_id) for item in value]
    if not isinstance(value, dict):
        return value
    if value == {"Ref": "AWS::StackId"}:
        return access_stack_id
    if set(value) == {"Ref"} and value["Ref"] in boundary_arns:
        return boundary_arns[value["Ref"]]
    if value == {"Fn::GetAtt": ["FrontendApp", "Arn"]}:
        return app_arn
    if "Fn::Sub" in value:
        text, mapping = value["Fn::Sub"]
        for key, replacement in mapping.items():
            text = text.replace("${" + key + "}", resolve_policy(replacement, boundary_arns, app_arn, access_stack_id))
        require("${" not in text, "Unresolved policy substitution")
        return text
    require(not any(key in value for key in ("Ref", "Fn::GetAtt")), "Unexpected policy intrinsic")
    return {key: resolve_policy(item, boundary_arns, app_arn, access_stack_id) for key, item in value.items()}


def normalize_key_policy(document):
    result = copy.deepcopy(parse_document(document))
    # Service principal arrays are OR lists, whose ordering is not significant.
    # Every other field remains present and must match the actual saved policy.
    for statement in result.get("Statement", []):
        principal = statement.get("Principal")
        if isinstance(principal, dict) and isinstance(principal.get("Service"), list):
            principal["Service"] = sorted(principal["Service"])
    return result


def policy_document(read, arn, expected, default_version, retained_versions):
    metadata = read("iam", "get-policy", "--policy-arn", arn)["Policy"]
    versions = read("iam", "list-policy-versions", "--policy-arn", arn)["Versions"]
    require(metadata["Arn"] == arn and metadata["DefaultVersionId"] == default_version, "Unexpected policy/default version: " + arn)
    require({row["VersionId"] for row in versions} == set(retained_versions), "Unexpected retained policy versions: " + arn)
    defaults = [row["VersionId"] for row in versions if row["IsDefaultVersion"]]
    require(defaults == [default_version], "Policy default changed during verification")
    version = read("iam", "get-policy-version", "--policy-arn", arn, "--version-id", default_version)["PolicyVersion"]
    require(version["VersionId"] == default_version and version["IsDefaultVersion"] is True, "Inconsistent policy-version response")
    require(parse_document(version["Document"]) == expected, "Live policy document mismatch: " + arn)
    return {"arn": arn, "default_version": default_version, "retained_versions": sorted(retained_versions), "canonical_sha256": D.canonical_sha(expected)}


def verify_grants(actual, expected):
    def normalized(grant):
        value = copy.deepcopy(grant)
        value.pop("CreationDate", None)  # Timestamp presentation is not authorization.
        value["Operations"] = sorted(value.get("Operations", []))
        return value
    previous = {row["GrantId"]: normalized(row) for row in expected}
    ids = set()
    for grant in actual:
        identifier = grant["GrantId"]
        require(identifier not in ids, "Duplicate KMS grant in response")
        ids.add(identifier)
        require(identifier in previous and normalized(grant) == previous[identifier], "A KMS grant appeared or changed since the approved evidence")
    # Service-managed retirement is permitted; no retirement/deletion is performed.
    return {"current_count": len(actual), "new_or_changed_grants": 0, "previously_observed_grants_absent": sorted(set(previous) - ids)}


def verify(read, candidate, expected_key_evidence):
    """Pure verification orchestration; tests supply a fake read callable."""
    baseline = parse_document(expected_key_evidence["access_stack_template"]["TemplateBody"])
    K.validate_candidate(baseline, candidate)
    identity = read("sts", "get-caller-identity")
    require(identity["Account"] == D.ACCOUNT and identity["Arn"].startswith(f"arn:aws:sts::{D.ACCOUNT}:assumed-role/{D.DEPLOYER_NAME}/"), "Unexpected AWS identity")
    access = read("cloudformation", "describe-stacks", "--stack-name", K.ACCESS_STACK_ID)["Stacks"][0]
    require(access["StackId"] == K.ACCESS_STACK_ID and access["StackStatus"] == "UPDATE_COMPLETE", "Owner access stack must be UPDATE_COMPLETE")
    fetched = read("cloudformation", "get-template", "--stack-name", K.ACCESS_STACK_ID, "--template-stage", "Original")
    require(parse_document(fetched["TemplateBody"]) == candidate, "Live owner template differs from approved repair")
    outputs = {row["OutputKey"]: row["OutputValue"] for row in access["Outputs"]}
    require(outputs["DeployerRoleArn"] == D.DEPLOYER, "Unexpected deployment-role output")
    app_arn = outputs["FrontendAppArn"]
    require(app_arn == f"arn:aws:amplify:{D.REGION}:{D.ACCOUNT}:apps/" + outputs["FrontendAppId"], "Invalid frontend app ARN output")
    own = read("iam", "get-role", "--role-name", D.DEPLOYER_NAME)["Role"]
    own_props = candidate["Resources"]["DeployerRole"]["Properties"]
    require(own["Arn"] == D.DEPLOYER and own["RoleId"] == identity["UserId"].split(":", 1)[0], "Assumed role identity/ID differs")
    require(own["AssumeRolePolicyDocument"] == own_props["AssumeRolePolicyDocument"] and own["MaxSessionDuration"] == 3600 and not own.get("PermissionsBoundary"), "Deployer MFA trust/session safeguard changed")
    owner_arns = {f"arn:aws:iam::{D.ACCOUNT}:policy/{D.STACK}-deployer-{i}" for i in range(1, 5)}
    require({row["PolicyArn"] for row in read("iam", "list-attached-role-policies", "--role-name", D.DEPLOYER_NAME)["AttachedPolicies"]} == owner_arns, "Deployer attachment set changed")
    require(not read("iam", "list-role-policies", "--role-name", D.DEPLOYER_NAME)["PolicyNames"], "Unexpected deployer inline policy")

    boundary_arns, runtime = {}, []
    for index, logical in enumerate(D.LOGICAL):
        props = candidate["Resources"][logical + "Role"]["Properties"]
        role = read("iam", "get-role", "--role-name", props["RoleName"])["Role"]
        require(role["Arn"] == D.ROLES[index] and role["Path"] == props["Path"] and role["RoleName"] == props["RoleName"], "Runtime role ARN/path/name differs")
        require(role["AssumeRolePolicyDocument"] == props["AssumeRolePolicyDocument"], "Runtime Lambda-only trust differs")
        boundary = role.get("PermissionsBoundary", {}).get("PermissionsBoundaryArn")
        if index < 3:
            require(isinstance(boundary, str) and re.fullmatch(f"arn:aws:iam::{D.ACCOUNT}:policy/[A-Za-z0-9+=,.@_-]{{1,128}}", boundary), "New runtime boundary is not a same-account generated policy ARN")
            require(boundary not in D.BOUNDARIES and boundary not in boundary_arns.values(), "Original/shared boundary still assigned to core role")
            boundary_arns[props["PermissionsBoundary"]["Ref"]] = boundary
        else:
            require(boundary == D.BOUNDARIES[index], "Deferred role boundary changed")
        require(not read("iam", "list-attached-role-policies", "--role-name", props["RoleName"])["AttachedPolicies"], "Unexpected runtime managed-policy attachment")
        require(read("iam", "list-role-policies", "--role-name", props["RoleName"])["PolicyNames"] == ["OwnerFixedRuntime"], "Unexpected runtime inline policies")
        inline = read("iam", "get-role-policy", "--role-name", props["RoleName"], "--policy-name", "OwnerFixedRuntime")["PolicyDocument"]
        require(inline == props["Policies"][0]["PolicyDocument"], "OwnerFixedRuntime document differs")
        runtime.append({"role": role["Arn"], "boundary": boundary, "inline_exact": True})
    require(set(boundary_arns) == set(K.NEW_BOUNDARY_IDS), "Missing generated boundary references")

    policies = []
    for logical, resource in candidate["Resources"].items():
        if resource["Type"] != "AWS::IAM::ManagedPolicy":
            continue
        props = resource["Properties"]
        arn = boundary_arns[logical] if logical in boundary_arns else f"arn:aws:iam::{D.ACCOUNT}:policy/" + props["ManagedPolicyName"]
        expected = resolve_policy(props["PolicyDocument"], boundary_arns, app_arn, access["StackId"])
        changed = logical in CHANGED_OWNER_POLICIES
        policies.append(policy_document(read, arn, expected, "v2" if changed else "v1", ["v1", "v2"] if changed else ["v1"]))
    for index, arn in enumerate(D.BOUNDARIES):
        expected = json.loads((HERE / "generated" / (D.STACK + "-" + D.SLUGS[index] + "-boundary.json")).read_text())
        if index < 3:
            require(D.canonical_sha(expected) == K.ORIGINAL_BOUNDARY_SHA256[D.SLUGS[index]], "Original boundary source changed")
        policies.append(policy_document(read, arn, expected, "v1", ["v1"]))
    executor = read("iam", "get-role", "--role-name", D.STACK + "-cfn")["Role"]
    require(executor["Arn"] == D.EXECUTOR and not executor.get("PermissionsBoundary"), "Execution-role ARN or boundary changed")
    require(executor["AssumeRolePolicyDocument"] == D.doc([{"Effect": "Allow", "Principal": {"Service": "cloudformation.amazonaws.com"}, "Action": "sts:AssumeRole"}]), "Execution-role trust changed")
    ceilings = {f"arn:aws:iam::{D.ACCOUNT}:policy/{D.STACK}-owner-ceiling-{i}" for i in range(1, 4)}
    require({row["PolicyArn"] for row in read("iam", "list-attached-role-policies", "--role-name", D.STACK + "-cfn")["AttachedPolicies"]} == set(D.POLICIES) | ceilings, "Execution-role attachments changed")
    require(not read("iam", "list-role-policies", "--role-name", D.STACK + "-cfn")["PolicyNames"], "Unexpected execution inline policy")
    for suffix, default in LEGACY_DEFAULTS.items():
        arn = f"arn:aws:iam::{D.ACCOUNT}:policy/{D.STACK}-cfn-{suffix}"
        expected = json.loads((D.POLICY_SOURCE / (suffix + ".json")).read_text())
        policies.append(policy_document(read, arn, expected, default, ["v" + str(i) for i in range(1, int(default[1:]) + 1)]))

    key_checks = {}
    for label, arn in (("dynamodb", K.DDB_KEY), ("lambda", K.LAMBDA_KEY)):
        expected = expected_key_evidence["keys"][label]
        meta = read("kms", "describe-key", "--key-id", arn)["KeyMetadata"]
        require(meta["Arn"] == arn and meta["AWSAccountId"] == D.ACCOUNT and meta["KeyManager"] == "AWS" and meta["Enabled"] is True
                and meta["KeyState"] == "Enabled" and meta["KeySpec"] == "SYMMETRIC_DEFAULT" and meta["KeyUsage"] == "ENCRYPT_DECRYPT"
                and meta["Origin"] == "AWS_KMS" and meta["MultiRegion"] is False, "KMS configuration changed")
        policy = read("kms", "get-key-policy", "--key-id", arn, "--policy-name", "default")["Policy"]
        require(normalize_key_policy(policy) == normalize_key_policy(expected["policy"]["Policy"]), "AWS-managed key policy changed")
        grants = read("kms", "list-grants", "--key-id", arn)["Grants"]
        key_checks[label] = {"arn": arn, "metadata_and_policy_exact": True, **verify_grants(grants, expected["grants"]["Grants"])}
    backend = read("cloudformation", "describe-stacks", "--stack-name", D.STACK_ID)["Stacks"][0]
    require(backend["StackId"] == D.STACK_ID and backend["StackStatus"] == "UPDATE_ROLLBACK_COMPLETE" and backend["RoleARN"] == D.EXECUTOR and backend.get("DisableRollback") is False, "Backend baseline or rollback configuration changed")
    inventory = read("cloudformation", "list-stack-resources", "--stack-name", D.STACK_ID)["StackResourceSummaries"]
    active = [row for row in inventory if row["ResourceStatus"] != "DELETE_COMPLETE"]
    require(len(active) == 1 and active[0]["LogicalResourceId"] == "HttpApi" and active[0]["PhysicalResourceId"] == "l52iwors8c", "Unexpected deployed backend resources")
    api = read("apigatewayv2", "get-api", "--api-id", "l52iwors8c")
    require(api["ApiId"] == "l52iwors8c" and api["ProtocolType"] == "HTTP" and api["DisableExecuteApiEndpoint"] is True, "Original API protection changed")
    require(not read("apigatewayv2", "get-routes", "--api-id", "l52iwors8c")["Items"], "Unexpected API routes")
    require(not read("apigatewayv2", "get-stages", "--api-id", "l52iwors8c")["Items"], "Unexpected API stages")
    return {"status": "PASS_POST_OWNER_KMS_REPAIR_READBACK", "checked_at_utc": datetime.now(timezone.utc).isoformat(), "identity": identity,
            "access_stack_status": access["StackStatus"], "complete_owner_template_exact": True, "generated_boundary_arns": boundary_arns,
            "runtime_roles": runtime, "policies": policies, "key_checks": key_checks, "backend_status": backend["StackStatus"],
            "api_id": "l52iwors8c", "endpoint_disabled": True, "routes": 0, "stages": 0, "AWS_mutations": 0,
            "limitations": ["Readback verifies documents and configuration, not a live KMS cryptographic call or Lambda runtime.",
                            "IAM is eventually consistent; separate effective-permission and deployment preflight remain required.",
                            "Generated boundary ARNs are read from role references; no unauthorized owner-stack resource listing is used."],
            "deployment_retry_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--expected-key-evidence", type=Path, required=True)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.candidate.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == args.candidate_sha256, "Approved candidate bytes changed")
    require(not args.output.exists(), "Refusing to overwrite verification evidence")
    args.output.mkdir(parents=True)
    aws = ReadOnlyAws()
    records = []

    def recorded(service, operation, *arguments):
        try:
            data = aws(service, operation, *arguments)
            records.append({"service": service, "operation": operation, "arguments": list(arguments), "data": data})
        except Exception as exc:
            records.append({"service": service, "operation": operation, "arguments": list(arguments), "error": str(exc)})
            (args.output / "reads.json").write_text(json.dumps(records, indent=2) + "\n")
            raise
        (args.output / "reads.json").write_text(json.dumps(records, indent=2) + "\n")
        print(service + ":" + operation + " PASS", flush=True)
        return data

    try:
        report = verify(recorded, json.loads(raw), json.loads(args.expected_key_evidence.read_text()))
    except Exception as exc:
        report = {"status": "STOPPED_POST_REPAIR_READ_ONLY", "error": str(exc), "AWS_mutations": 0, "automatic_retries": 0, "deployment_retry_authorized": False}
    (args.output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report["status"] == "PASS_POST_OWNER_KMS_REPAIR_READBACK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
