#!/usr/bin/env python3
"""Print a scoped read-only collision-check plan. Never execute AWS commands."""

import argparse
import json
from pathlib import Path
import re
import shlex


MANIFEST = Path(__file__).with_name("resources.json")
FUNCTIONS = {
    "HealthFunction", "CasesFunction", "CalculationsFunction", "JobsFunction",
    "JobWorkerFunction",
}


def load_manifest(path=MANIFEST):
    resources = json.loads(Path(path).read_text())
    if (resources.get("account"), resources.get("region"), resources.get("stack_name")) != (
        "631367363628", "us-east-2", "actionbridge-dental-staging"
    ):
        raise ValueError("This plan is restricted to the reviewed staging account, Region and stack.")
    if set(resources["functions"]) != FUNCTIONS:
        raise ValueError("Expected exactly the five reviewed staging functions.")
    if resources["role_path"] != "/actionbridge/staging/actionbridge-dental-staging/":
        raise ValueError("Unexpected staging role path.")
    names = [item["name"] for item in resources["functions"].values()]
    policies = [item["boundary_policy_name"] for item in resources["functions"].values()]
    roles = [item["role_name"] for item in resources["functions"].values()]
    names += [resources["table"]["name"], *resources["queues"].values(),
              resources["execution_role_name"], resources["api"]["name"]]
    for name in names + policies + roles:
        if not re.fullmatch(r"actionbridge-dental-staging-[a-z0-9-]+|actionbridge-dental-staging", name):
            raise ValueError("Unexpected staging resource name.")
    if any(len(set(items)) != 5 for items in (policies, roles, [item["name"] for item in resources["functions"].values()])):
        raise ValueError("Function names and boundary policy names must be distinct.")
    for name in resources["buckets"].values():
        if not re.fullmatch(r"ab-dental-staging-[a-z0-9-]+-631367363628-us-east-2", name):
            raise ValueError("Unexpected staging bucket name.")
    if resources["api"]["stage"] != "staging" or resources["artifact_prefix"] != "actionbridge-dental-staging/":
        raise ValueError("Unexpected staging API stage or artifact prefix.")
    return resources


def command_plan(resources, profile):
    """Return argv lists and interpretation notes; no execution capability exists."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:+-]{0,127}", profile):
        raise ValueError("Supply the name of an existing authorized non-root administrator profile.")
    common = ["aws", "--profile", profile, "--region", resources["region"],
              "--no-cli-pager", "--output", "json"]
    checks = []

    def add(label, arguments, query, interpretation):
        checks.append({
            "label": label,
            "command": common + arguments + ["--query", query],
            "interpretation": interpretation,
        })

    add("Verify account and non-root identity", ["sts", "get-caller-identity"],
        "{Account:Account,Root:contains(Arn, ':root')}",
        "STOP unless Account is 631367363628 and Root is false. No login or role assumption is included.")
    add("Record Region coverage", ["ec2", "describe-regions", "--all-regions"],
        "Regions[].{Region:RegionName,Status:OptInStatus}",
        "Record enabled and unavailable Regions; do not enable Regions. This collision plan checks Ohio only.")
    add("New stack name", ["cloudformation", "describe-stacks", "--stack-name", resources["stack_name"]],
        "Stacks[].{Name:StackName,Status:StackStatus,Id:StackId}",
        "Any existing stack, including REVIEW_IN_PROGRESS, requires review. Only an explicit not-exists response is a negative finding.")
    for function in resources["functions"].values():
        name = function["name"]
        add("Function " + name, ["lambda", "get-function-configuration", "--function-name", name],
            "{Name:FunctionName,State:State}",
            "ResourceNotFoundException is a negative finding; an existing function is a collision. Environment values are excluded.")
        group = "/aws/lambda/" + name
        add("Log group " + group, ["logs", "describe-log-groups", "--log-group-name-prefix", group],
            "logGroups[?logGroupName == '" + group + "'].{Name:logGroupName,Arn:arn}",
            "An empty successful result is a negative finding for this exact group; a matching group requires review.")
    add("Table " + resources["table"]["name"],
        ["dynamodb", "describe-table", "--table-name", resources["table"]["name"]],
        "{Name:Table.TableName,Status:Table.TableStatus}",
        "ResourceNotFoundException is a negative finding; do not reuse an existing table.")
    for name in resources["queues"].values():
        add("Queue " + name,
            ["sqs", "get-queue-url", "--queue-name", name, "--queue-owner-aws-account-id", resources["account"]],
            "{QueueUrl:QueueUrl}",
            "QueueDoesNotExist/NonExistentQueue can also mean insufficient access; keep these errors UNKNOWN until independently verified by an authorized owner.")
    for purpose, name in resources["buckets"].items():
        add(purpose.capitalize() + " bucket " + name,
            ["s3api", "head-bucket", "--bucket", name, "--expected-bucket-owner", resources["account"]],
            "{Region:BucketRegion}",
            "Success means the bucket exists with the expected owner. 400/403/404 are not proof of global name availability; keep unresolved until administrator review. Upload bucket must be new; artifact bucket reuse needs explicit approval.")
    add("Reserved runtime role path", ["iam", "list-roles", "--path-prefix", resources["role_path"]],
        "Roles[].{Name:RoleName,Path:Path}",
        "Every existing role under this path requires review. The prepared staging template uses five explicit role names.")
    for function in resources["functions"].values():
        name = function["role_name"]
        add("Runtime role " + name, ["iam", "get-role", "--role-name", name],
            "{Name:Role.RoleName,Path:Role.Path}",
            "NoSuchEntity is a negative finding. IAM role names are account-global even if another path is used; any existing name requires review.")
    add("Execution role " + resources["execution_role_name"],
        ["iam", "get-role", "--role-name", resources["execution_role_name"]],
        "{Name:Role.RoleName,Path:Role.Path}",
        "NoSuchEntity is a negative finding; existing trust/permissions require separate administrator review before reuse.")
    for function in resources["functions"].values():
        name = function["boundary_policy_name"]
        arn = "arn:aws:iam::" + resources["account"] + ":policy/" + name
        add("Boundary policy " + name, ["iam", "get-policy", "--policy-arn", arn],
            "{Name:Policy.PolicyName,Arn:Policy.Arn}",
            "NoSuchEntity means only this exact policy ARN is absent; the same account-global policy name may exist under another path, so name availability remains UNKNOWN.")
    api_name = resources["api"]["name"]
    add("HTTP/WebSocket APIs with the proposed name", ["apigatewayv2", "get-apis"],
        "Items[?Name == '" + api_name + "'].{Name:Name,Id:ApiId,Protocol:ProtocolType}",
        "API names are not unique. Any match requires owner review; never adopt an API merely because its name matches.")
    add("REST APIs with the proposed name", ["apigateway", "get-rest-apis"],
        "items[?name == '" + api_name + "'].{Name:name,Id:id}",
        "A matching REST API is an inventory conflict, not the HTTP API this backend requires.")
    return checks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True,
                        help="Existing authorized non-root administrator profile; this tool never logs in.")
    args = parser.parse_args(argv)
    try:
        checks = command_plan(load_manifest(), args.profile)
    except (KeyError, TypeError, ValueError) as error:
        parser.error(str(error))
    print("# OFFLINE PLAN ONLY: no AWS commands are executed by this program.")
    print("# Run individual reads only after owner authorization. Do not pipe this output to a shell.")
    print("# AccessDenied, throttling, network errors and incomplete pagination mean UNKNOWN, never FREE.")
    print("# The 153-resource inventory is incomplete. Review other Regions, services and global IAM separately.")
    print("# A negative check can race with later creation; recheck before each approved creation.")
    for check in checks:
        print("\n# " + check["label"])
        print("# " + check["interpretation"])
        print(shlex.join(check["command"]))
    print("\n# No resources were inspected or changed. No collision finding is established by printing this plan.")


if __name__ == "__main__":
    main()
