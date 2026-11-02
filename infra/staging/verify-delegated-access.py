#!/usr/bin/env python3
"""Read-only, fail-closed post-setup verification. Never logs tokens or case data.

Run after the owner-approved access stack reaches CREATE_COMPLETE and the owner
has completed a developer-MFA SwitchRole / aws login. No CLI retries or fallback
profiles. This tool does not apply IAM changes or execute/create change sets.
"""
import argparse
import base64
import configparser
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

SPEC = importlib.util.spec_from_file_location("delegation", Path(__file__).with_name("prepare-delegated-access.py"))
D = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D)
READS = {("sts", "get-caller-identity"), ("cloudformation", "describe-stacks"), ("cloudformation", "list-stack-resources"),
         ("cloudformation", "get-template-summary"), ("cloudformation", "validate-template"),
         ("iam", "get-role"), ("iam", "list-attached-role-policies"), ("iam", "list-role-policies"), ("iam", "get-role-policy"),
         ("iam", "get-policy"), ("iam", "get-policy-version"), ("iam", "list-policy-versions"),
         ("iam", "simulate-principal-policy"), ("iam", "simulate-custom-policy"), ("accessanalyzer", "validate-policy"),
         ("apigatewayv2", "get-api"), ("apigatewayv2", "get-routes"), ("apigatewayv2", "get-stages"),
         ("s3api", "head-object"), ("amplify", "get-app"), ("amplify", "get-branch"), ("amplify", "list-branches")}


def require(condition, message):
    if not condition:
        raise ValueError(message)


class AwsReadError(ValueError):
    def __init__(self, service, operation, code):
        self.service, self.operation, self.code = service, operation, code
        super().__init__(f"{service}:{operation} failed ({code}); no retry or fallback performed")


def validate_profile(profile):
    require(profile == "actionbridge-staging-deployer", "Use only the dedicated deployment profile")
    require(not any(os.environ.get(key) for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")),
            "Unset ambient credential overrides; this workflow uses keyless named-profile login")
    config = configparser.RawConfigParser()
    config.read(os.environ.get("AWS_CONFIG_FILE", str(Path.home() / ".aws/config")))
    section = "profile " + profile
    require(config.has_section(section), "Dedicated profile has not been created by aws login")
    login = config.get(section, "login_session", fallback="")
    require(login and not login.endswith(":root"), "A non-root aws-login role session is required")
    require("assumed-role/" + D.DEPLOYER_NAME + "/" in login or login == D.DEPLOYER,
            "Login profile is not bound to the dedicated role")


class AwsReads:
    def __init__(self, profile):
        validate_profile(profile)
        self.profile = profile

    def __call__(self, service, operation, *arguments):
        require((service, operation) in READS, "Refusing an operation outside the read-only allowlist")
        require(not any(arg.startswith("--profile") or arg.startswith("--endpoint") for arg in arguments),
                "Do not override the profile or endpoint")
        # aws-login credential refresh writes a shared cache. Independent AWS
        # reads are not independent at the CLI credential layer. Fail closed if
        # another supported workflow process is already using this profile.
        lock_path = D.ROOT / ".staging/delegated-access-cli.lock"
        with lock_path.open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("Another delegated AWS CLI operation is active; serialize calls") from exc
            result = subprocess.run(["aws", service, operation, *arguments, "--profile", self.profile, "--region", D.REGION,
                                     "--output", "json", "--no-cli-pager", "--cli-connect-timeout", "10", "--cli-read-timeout", "30"],
                                    capture_output=True, text=True, timeout=45,
                                    env={**os.environ, "AWS_MAX_ATTEMPTS": "1", "AWS_PAGER": "",
                                         "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS": "true"}, check=False)
        if result.returncode:
            match = re.search(r"An error occurred \(([A-Za-z0-9_.-]+)\)", result.stderr)
            raise AwsReadError(service, operation, match.group(1) if match else "CLI_AUTH_OR_TRANSPORT_ERROR")
        return json.loads(result.stdout)


def require_unpublished_staging_branch(read, app_id):
    """Read only the approved branch; do not enumerate other branch resources."""
    try:
        read("amplify", "get-branch", "--app-id", app_id, "--branch-name", "staging")
    except AwsReadError as exc:
        if (exc.service, exc.operation, exc.code) in (("amplify", "get-branch", "NotFoundException"),
                                                     ("amplify", "get-branch", "ResourceNotFoundException")):
            return
        raise
    raise ValueError("Frontend staging branch already exists; stop before publishing")


def default_policy(read, arn):
    metadata = read("iam", "get-policy", "--policy-arn", arn)["Policy"]
    versions = read("iam", "list-policy-versions", "--policy-arn", arn)["Versions"]
    document = read("iam", "get-policy-version", "--policy-arn", arn, "--version-id", metadata["DefaultVersionId"])["PolicyVersion"]["Document"]
    require(metadata["Arn"] == arn, "Returned policy ARN differs")
    require(sum(bool(item["IsDefaultVersion"]) for item in versions) == 1, "Unexpected default policy version count")
    require(any(item["VersionId"] == metadata["DefaultVersionId"] and item["IsDefaultVersion"] for item in versions),
            "Policy default changed during read")
    return document, {"arn": arn, "default_version": metadata["DefaultVersionId"], "version_count": len(versions),
                      "new_version_capacity": max(0, 5 - len(versions)), "canonical_sha256": D.canonical_sha(document)}


def resolve_policy(value, app_arn, access_stack_id):
    if isinstance(value, list):
        return [resolve_policy(item, app_arn, access_stack_id) for item in value]
    if not isinstance(value, dict):
        return value
    if value == {"Fn::GetAtt": ["FrontendApp", "Arn"]}:
        return app_arn
    if value == {"Ref": "AWS::StackId"}:
        return access_stack_id
    if "Fn::Sub" in value:
        text, mapping = value["Fn::Sub"]
        require(set(mapping) == {"AppArn"}, "Unexpected policy intrinsic")
        return text.replace("${AppArn}", resolve_policy(mapping["AppArn"], app_arn, access_stack_id))
    require(not any(key in value for key in ("Ref", "Fn::GetAtt")), "Unexpected policy intrinsic")
    return {key: resolve_policy(item, app_arn, access_stack_id) for key, item in value.items()}


def verify(read, setup_dir, expect_applied=False):
    template = json.loads((setup_dir / "access-stack.json").read_text())
    require(template == D.access_template(), "Setup package differs from the reviewed generator output")
    identity = read("sts", "get-caller-identity")
    require(identity["Account"] == D.ACCOUNT and identity["Arn"].startswith(f"arn:aws:sts::{D.ACCOUNT}:assumed-role/{D.DEPLOYER_NAME}/"),
            "Unexpected AWS identity; no fallback identity is allowed")
    access = read("cloudformation", "describe-stacks", "--stack-name", D.ACCESS_STACK)["Stacks"][0]
    require(access["StackStatus"] == "CREATE_COMPLETE", "Access setup is not CREATE_COMPLETE")
    summary = read("cloudformation", "get-template-summary", "--stack-name", D.ACCESS_STACK)
    actual_inventory = {logical: item["ResourceType"] for item in summary["ResourceIdentifierSummaries"]
                        for logical in item["LogicalResourceIds"]}
    require(actual_inventory == {logical: item["Type"] for logical, item in template["Resources"].items()},
            "Deployed access stack resource inventory differs from the reviewed fourteen resources")
    outputs = {value["OutputKey"]: value["OutputValue"] for value in access["Outputs"]}
    require(outputs["DeployerRoleArn"] == D.DEPLOYER, "Unexpected deployment role output")
    require(outputs["FrontendAppArn"] == f"arn:aws:amplify:{D.REGION}:{D.ACCOUNT}:apps/" + outputs["FrontendAppId"], "Unexpected frontend ARN scope")
    own_role = read("iam", "get-role", "--role-name", D.DEPLOYER_NAME)["Role"]
    require(identity["UserId"].split(":", 1)[0] == own_role["RoleId"], "STS session belongs to a different IAM role ID")
    require(own_role["Arn"] == D.DEPLOYER and own_role["AssumeRolePolicyDocument"] ==
            template["Resources"]["DeployerRole"]["Properties"]["AssumeRolePolicyDocument"], "Deployer trust is not the exact MFA trust")
    require(own_role["MaxSessionDuration"] == 3600 and not own_role.get("PermissionsBoundary"), "Unexpected deployer session limit or boundary")
    expected_own = {arn for arn in D.OWNER_POLICIES if "-deployer-" in arn}
    attached_own = read("iam", "list-attached-role-policies", "--role-name", D.DEPLOYER_NAME)["AttachedPolicies"]
    require({item["PolicyArn"] for item in attached_own} == expected_own, "Unexpected deployer permission attachments")
    require(not read("iam", "list-role-policies", "--role-name", D.DEPLOYER_NAME)["PolicyNames"], "Unexpected deployer inline permissions")
    for index, expected in enumerate(D.split_policy(D.deployer_policy()), 1):
        own_policy, _ = default_policy(read, f"arn:aws:iam::{D.ACCOUNT}:policy/{D.STACK}-deployer-{index}")
        require(own_policy == resolve_policy(expected, outputs["FrontendAppArn"], access["StackId"]), "Deployer permissions changed")
    stack = read("cloudformation", "describe-stacks", "--stack-name", D.STACK)["Stacks"][0]
    require(stack["StackId"] == D.STACK_ID and stack["StackStatus"] == "UPDATE_ROLLBACK_COMPLETE", "Staging baseline changed")
    require(stack["RoleARN"] == D.EXECUTOR and not stack.get("DisableRollback", False), "Execution role or rollback configuration changed")
    execution_role = read("iam", "get-role", "--role-name", D.STACK + "-cfn")["Role"]
    require(execution_role["Arn"] == D.EXECUTOR and not execution_role.get("PermissionsBoundary"), "Execution role metadata changed")
    require(execution_role["AssumeRolePolicyDocument"] == D.doc([{"Effect": "Allow", "Principal": {"Service": "cloudformation.amazonaws.com"},
                                                               "Action": "sts:AssumeRole"}]), "Execution role trust changed")
    inventory = read("cloudformation", "list-stack-resources", "--stack-name", D.STACK)["StackResourceSummaries"]
    active = [item for item in inventory if item["ResourceStatus"] != "DELETE_COMPLETE"]
    require(len(active) == 1 and active[0]["LogicalResourceId"] == "HttpApi" and active[0]["PhysicalResourceId"] == "l52iwors8c",
            "Unexpected residual resources; do not delete anything automatically")
    api = read("apigatewayv2", "get-api", "--api-id", "l52iwors8c")
    require(api["ApiId"] == "l52iwors8c" and api["ProtocolType"] == "HTTP" and api.get("DisableExecuteApiEndpoint") is True,
            "API identity/protocol/disabled endpoint differs")
    require(not read("apigatewayv2", "get-routes", "--api-id", "l52iwors8c")["Items"], "Unexpected routes")
    require(not read("apigatewayv2", "get-stages", "--api-id", "l52iwors8c")["Items"], "Unexpected stages")
    policy_results = []
    for arn in D.POLICIES:
        short = arn.rsplit("-cfn-", 1)[1] + ".json"
        original = D.ROOT / ".staging/api-recovery-review/policies-A" / short
        expected_path = D.POLICY_SOURCE / short if expect_applied and short in ("identity-03.json", "guardrails-02.json") else original
        document, metadata = default_policy(read, arn)
        require(document == json.loads(expected_path.read_text()), "Live policy drift: " + arn)
        if not expect_applied and short in ("identity-03.json", "guardrails-02.json"):
            require(metadata["new_version_capacity"] >= 1, "Policy version capacity is full; do not delete prior versions")
        policy_results.append(metadata)
    expected_attachments = set(D.POLICIES)
    for index, ceiling in enumerate(D.ceilings(), 1):
        arn = f"arn:aws:iam::{D.ACCOUNT}:policy/{D.STACK}-owner-ceiling-{index}"
        actual, _ = default_policy(read, arn)
        require(actual == ceiling, "Independent execution ceiling differs")
        expected_attachments.add(arn)
    attached = read("iam", "list-attached-role-policies", "--role-name", D.STACK + "-cfn")["AttachedPolicies"]
    require({item["PolicyArn"] for item in attached} == expected_attachments, "Unexpected execution role policy attachments")
    require(not read("iam", "list-role-policies", "--role-name", D.STACK + "-cfn")["PolicyNames"], "Unexpected inline execution policy")
    for index, (logical, expected) in enumerate(D.runtime_roles().items()):
        props = expected["Properties"]
        actual = read("iam", "get-role", "--role-name", props["RoleName"])["Role"]
        require(actual["Arn"] == D.ROLES[index] and actual["PermissionsBoundary"]["PermissionsBoundaryArn"] == D.BOUNDARIES[index],
                "Runtime role ARN or boundary differs: " + logical)
        require(actual["AssumeRolePolicyDocument"] == props["AssumeRolePolicyDocument"], "Runtime role trust changed")
        require(not read("iam", "list-attached-role-policies", "--role-name", props["RoleName"])["AttachedPolicies"], "Unexpected runtime managed attachment")
        require(read("iam", "list-role-policies", "--role-name", props["RoleName"])["PolicyNames"] == ["OwnerFixedRuntime"], "Unexpected runtime inline policies")
        inline = read("iam", "get-role-policy", "--role-name", props["RoleName"], "--policy-name", "OwnerFixedRuntime")["PolicyDocument"]
        require(inline == props["Policies"][0]["PolicyDocument"], "Runtime identity permissions differ")
        boundary, _ = default_policy(read, D.BOUNDARIES[index])
        require(boundary == json.loads((D.HERE / "generated" / (D.STACK + "-" + D.SLUGS[index] + "-boundary.json")).read_text()),
                "Runtime boundary changed")
    artifacts = []
    for item in json.loads((D.ROOT / ".staging/artifacts/artifact-parameters.json").read_text()):
        key = item["ParameterValue"]
        local = D.ROOT / ".staging/artifacts" / key.removeprefix(D.STACK + "/")
        digest = hashlib.sha256(local.read_bytes()).digest()
        require(local.stem == digest.hex(), "Local artifact hash does not match its immutable key")
        head = read("s3api", "head-object", "--bucket", D.ARTIFACTS.split(":::", 1)[1], "--key", key,
                    "--expected-bucket-owner", D.ACCOUNT, "--checksum-mode", "ENABLED")
        require(head["ChecksumSHA256"] == base64.b64encode(digest).decode() and head["ContentLength"] == local.stat().st_size
                and head["ServerSideEncryption"] == "AES256", "Artifact owner/checksum/bytes/encryption check failed")
        artifacts.append({"key": key, "bytes": head["ContentLength"], "sha256": digest.hex()})
    app = read("amplify", "get-app", "--app-id", outputs["FrontendAppId"])["app"]
    require(app["appArn"] == outputs["FrontendAppArn"] and app["platform"] == "WEB" and not app.get("repository"), "Unexpected frontend app configuration")
    require_unpublished_staging_branch(read, outputs["FrontendAppId"])
    return {"status": "PASS_READ_ONLY_SETUP_PREREQUISITES", "account": identity["Account"], "caller_arn": identity["Arn"],
            "region": D.REGION, "stack_status": stack["StackStatus"], "api_id": api["ApiId"], "api_endpoint_disabled": True,
            "policy_versions": policy_results, "artifact_count": len(artifacts), "artifact_bytes": sum(item["bytes"] for item in artifacts),
            "artifacts": artifacts, "frontend_app_id": outputs["FrontendAppId"], "frontend_staging_branch_exists": False,
            "other_frontend_branches_inventory_verified": False, "aws_mutations": False,
            "deployment_ready": False, "next_gate": "Server-side policy validation/simulation plus separately approved IAM corrections and deployment scope"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="actionbridge-staging-deployer")
    parser.add_argument("--setup-dir", type=Path, required=True)
    parser.add_argument("--expect-tag-policies-applied", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(verify(AwsReads(args.profile), args.setup_dir, args.expect_tag_policies_applied), indent=2))
    except (ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        raise SystemExit("BLOCKED: " + str(exc))
