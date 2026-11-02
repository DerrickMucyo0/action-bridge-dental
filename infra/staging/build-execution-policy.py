#!/usr/bin/env python3
"""Build local CloudFormation policy drafts. Never contacts AWS or reads private parameters.

The bootstrap draft is public and deterministic. Backend drafts require an API ID
captured and reviewed by the owner after bootstrap; syntax validation is not an
ownership check. Output files are created exclusively, never overwritten.
"""
import argparse
import json
from pathlib import Path
import re
import sys


HERE = Path(__file__).resolve().parent
BOOTSTRAP = HERE / "generated/bootstrap-execution-policy.json"
FUNCTIONS = ("HealthFunction", "CasesFunction", "CalculationsFunction", "JobsFunction", "JobWorkerFunction")
BASIC = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
SQS = "arn:aws:iam::aws:policy/service-role/AWSLambdaSQSQueueExecutionRole"
API_ID = re.compile(r"[a-z0-9]{10}")


def manifest():
    value = json.loads((HERE / "resources.json").read_text())
    if (value["account"], value["region"], value["stack_name"]) != ("631367363628", "us-east-2", "actionbridge-dental-staging"):
        raise ValueError("Manifest must target the reviewed staging account, Region and stack.")
    if set(value["functions"]) != set(FUNCTIONS):
        raise ValueError("Manifest must contain exactly the five reviewed functions.")
    for spec in value["functions"].values():
        if not re.fullmatch(r"actionbridge-dental-staging-[a-z-]{1,30}", spec["name"]):
            raise ValueError("Invalid staging function name.")
        if spec["role_name"] != spec["name"] + "-role" or len(spec["role_name"]) > 64:
            raise ValueError("Invalid named staging role.")
        if spec["boundary_policy_name"] != spec["name"] + "-boundary":
            raise ValueError("Invalid staging boundary policy name.")
    if value["role_path"] != "/actionbridge/staging/actionbridge-dental-staging/":
        raise ValueError("Unexpected runtime-role path.")
    if value["artifact_prefix"] != value["stack_name"] + "/":
        raise ValueError("Unexpected artifact prefix.")
    if value["api"] != {"name": value["stack_name"], "stage": "staging"}:
        raise ValueError("Unexpected API name or stage.")
    for name in [value["table"]["name"], *value["queues"].values(), value["execution_role_name"]]:
        if not re.fullmatch(r"actionbridge-dental-staging-[a-z-]{1,30}", name):
            raise ValueError("Invalid staging resource name.")
    for bucket in value["buckets"].values():
        if not re.fullmatch(r"ab-dental-staging-[a-z-]+-631367363628-us-east-2", bucket) or len(bucket) > 63:
            raise ValueError("Invalid staging bucket name.")
    return value


def allow(action, resource, condition=None):
    result = {"Effect": "Allow", "Action": action, "Resource": resource}
    if condition:
        result["Condition"] = condition
    return result


def deny(action, resource="*", condition=None):
    result = {"Effect": "Deny", "Action": action, "Resource": resource}
    if condition:
        result["Condition"] = condition
    return result


def bootstrap_policy(config=None):
    cfg = config or manifest()
    collection = f"arn:aws:apigateway:{cfg['region']}::/apis"
    return {"Version": "2012-10-17", "Statement": [
        {"Effect": "Deny", "NotAction": ["apigateway:GET", "apigateway:POST"], "Resource": "*"},
        allow("apigateway:POST", collection, {
            "StringEquals": {"aws:RequestedRegion": cfg["region"], "apigateway:Request/ApiName": cfg["api"]["name"]},
            "Bool": {"apigateway:Request/DisableExecuteApiEndpoint": "true"},
        }),
        allow("apigateway:GET", collection + "/*", {"StringEquals": {"aws:RequestedRegion": cfg["region"]}}),
        deny("apigateway:*", condition={"StringNotEquals": {"aws:RequestedRegion": cfg["region"]}}),
        deny(["apigateway:PATCH", "apigateway:PUT", "apigateway:DELETE"]),
        {"Effect": "Deny", "Action": "apigateway:POST", "NotResource": collection},
        deny("apigateway:POST", collection, {"StringNotEquals": {"apigateway:Request/ApiName": cfg["api"]["name"]}}),
        deny("apigateway:POST", collection, {"BoolIfExists": {"apigateway:Request/DisableExecuteApiEndpoint": "false"}}),
    ]}


def backend_policy(api_id, event_source_mapping_id=None, config=None):
    if not API_ID.fullmatch(api_id):
        raise ValueError("API ID must be exactly ten lowercase letters/digits; ownership must be checked separately.")
    if event_source_mapping_id is not None and not re.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", event_source_mapping_id):
        raise ValueError("Event-source-mapping ID must be a lowercase UUID.")
    cfg = config or manifest()
    account, region = cfg["account"], cfg["region"]
    regional = {"StringEquals": {"aws:RequestedRegion": region}}
    functions = [f"arn:aws:lambda:{region}:{account}:function:{cfg['functions'][key]['name']}" for key in FUNCTIONS]
    roles = [f"arn:aws:iam::{account}:role{cfg['role_path']}{cfg['functions'][key]['role_name']}" for key in FUNCTIONS]
    boundaries = [f"arn:aws:iam::{account}:policy/{cfg['functions'][key]['boundary_policy_name']}" for key in FUNCTIONS]
    statements = []
    for key, role, boundary in zip(FUNCTIONS, roles, boundaries):
        statements.append(allow(["iam:CreateRole", "iam:PutRolePolicy", "iam:UpdateAssumeRolePolicy"], role,
                                {"ArnEquals": {"iam:PermissionsBoundary": boundary}}))
        # These actions support both condition keys. No arbitrary policy attachment.
        statements.append(allow(["iam:AttachRolePolicy", "iam:DetachRolePolicy"], role, {"ArnEquals": {
            "iam:PermissionsBoundary": boundary,
            "iam:PolicyARN": [BASIC, SQS] if key == "JobWorkerFunction" else BASIC,
        }}))
    statements += [
        allow(["iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies",
               "iam:ListRoleTags", "iam:DeleteRole", "iam:DeleteRolePolicy", "iam:TagRole", "iam:UntagRole"], roles),
        allow("iam:PassRole", roles, {"StringEquals": {"iam:PassedToService": "lambda.amazonaws.com"}}),
        deny(["iam:PutRolePermissionsBoundary", "iam:DeleteRolePermissionsBoundary"]),
        deny(["iam:CreatePolicy", "iam:CreatePolicyVersion", "iam:SetDefaultPolicyVersion", "iam:DeletePolicyVersion", "iam:DeletePolicy"]),
        deny("iam:*", f"arn:aws:iam::{account}:role/{cfg['execution_role_name']}"),
        allow(["lambda:CreateFunction", "lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:UpdateFunctionCode",
               "lambda:UpdateFunctionConfiguration", "lambda:DeleteFunction", "lambda:ListTags", "lambda:TagResource", "lambda:UntagResource"], functions, regional),
        allow(["lambda:AddPermission", "lambda:RemovePermission"], functions[:-1], {
            "StringEquals": {"aws:RequestedRegion": region, "lambda:Principal": "apigateway.amazonaws.com"}}),
        allow("lambda:GetPolicy", functions[:-1], regional),
        allow("lambda:CreateEventSourceMapping", "*", {
            "StringEquals": {"aws:RequestedRegion": region}, "ArnEquals": {"lambda:FunctionArn": functions[-1]}}),
        # Get/Delete rollback errors used Resource '*'. Scope all lifecycle
        # grants with Lambda's supported FunctionArn condition; the guardrail
        # retains additional mapping-ARN isolation specifically for Update.
        allow(["lambda:GetEventSourceMapping", "lambda:UpdateEventSourceMapping", "lambda:DeleteEventSourceMapping"],
              "*", {
                  "StringEquals": {"aws:RequestedRegion": region}, "ArnEquals": {"lambda:FunctionArn": functions[-1]}}),
        allow(["dynamodb:CreateTable", "dynamodb:DescribeTable", "dynamodb:UpdateTable", "dynamodb:DeleteTable",
               "dynamodb:DescribeTimeToLive", "dynamodb:UpdateTimeToLive", "dynamodb:ListTagsOfResource", "dynamodb:TagResource", "dynamodb:UntagResource"],
              f"arn:aws:dynamodb:{region}:{account}:table/{cfg['table']['name']}", regional),
    ]
    bucket = f"arn:aws:s3:::{cfg['buckets']['uploads']}"
    owner = {"StringEquals": {"s3:ResourceAccount": account}}
    statements += [
        allow("s3:CreateBucket", bucket, {"StringEquals": {"s3:LocationConstraint": region}}),
        allow(["s3:DeleteBucket", "s3:GetBucketLocation", "s3:ListBucket", "s3:GetBucketCORS", "s3:PutBucketCORS",
               "s3:GetLifecycleConfiguration", "s3:PutLifecycleConfiguration", "s3:GetEncryptionConfiguration", "s3:PutEncryptionConfiguration",
               "s3:GetBucketPublicAccessBlock", "s3:PutBucketPublicAccessBlock", "s3:GetBucketOwnershipControls", "s3:PutBucketOwnershipControls",
               "s3:GetBucketTagging", "s3:PutBucketTagging"], bucket, owner),
        allow("s3:GetObject", f"arn:aws:s3:::{cfg['buckets']['artifacts']}/{cfg['artifact_prefix']}*", owner),
        allow("s3:GetBucketLocation", f"arn:aws:s3:::{cfg['buckets']['artifacts']}", owner),
        allow(["sqs:CreateQueue", "sqs:GetQueueUrl", "sqs:GetQueueAttributes", "sqs:SetQueueAttributes", "sqs:DeleteQueue",
               "sqs:ListQueueTags", "sqs:TagQueue", "sqs:UntagQueue"],
              [f"arn:aws:sqs:{region}:{account}:{name}" for name in cfg["queues"].values()], regional),
    ]
    groups = [f"arn:aws:logs:{region}:{account}:log-group:/aws/lambda/{cfg['functions'][key]['name']}" for key in FUNCTIONS]
    statements += [
        allow(["logs:CreateLogGroup", "logs:PutRetentionPolicy", "logs:DeleteRetentionPolicy", "logs:DeleteLogGroup",
               "logs:ListTagsLogGroup", "logs:TagLogGroup", "logs:UntagLogGroup"], [arn + ":*" for arn in groups], regional),
        allow(["logs:ListTagsForResource", "logs:TagResource", "logs:UntagResource"], groups, regional),
        allow("logs:DescribeLogGroups", "*", regional),
    ]
    api = f"arn:aws:apigateway:{region}::/apis/{api_id}"
    api_resources = [api]
    for child in ("authorizers", "integrations", "routes"):
        api_resources += [f"{api}/{child}", f"{api}/{child}/*"]
    api_resources += [f"{api}/stages", f"{api}/stages/{cfg['api']['stage']}"]
    statements += [
        allow(["apigateway:GET", "apigateway:PATCH", "apigateway:PUT", "apigateway:POST", "apigateway:DELETE"], api_resources, regional),
        deny(["apigateway:POST", "apigateway:PUT"], f"arn:aws:apigateway:{region}::/apis"),
        {"Effect": "Deny", "NotAction": ["iam:*", "s3:*"], "Resource": "*",
         "Condition": {"StringNotEquals": {"aws:RequestedRegion": region}}},
    ]
    # IAM takes RoleName, not Path, for these calls. Before creation (or after
    # deletion), authorization can use the exact root-path alias rather than the
    # intended role ARN. Keep all creation and role configuration path-scoped.
    aliases = [f"arn:aws:iam::{account}:role/{cfg['functions'][key]['role_name']}" for key in FUNCTIONS]
    statements.append(allow("iam:GetRole", aliases))
    for key, alias in zip(FUNCTIONS, aliases):
        statements.append(allow("iam:DetachRolePolicy", alias, {
            "ArnEquals": {"iam:PolicyARN": [BASIC, SQS] if key == "JobWorkerFunction" else BASIC},
            "Null": {"iam:PermissionsBoundary": "true"},
        }))
    # Null means key absence, not proof that the role is missing. An existing
    # unbounded root role with a reserved name has the same cleanup context.
    # The owner must review this bounded exception and recheck name absence.
    return {"Version": "2012-10-17", "Statement": statements}


def guardrail_policy(api_id, event_source_mapping_id=None, config=None):
    """Explicit denials to accompany every identity part, not a permissions boundary."""
    cfg = config or manifest()
    identity = backend_policy(api_id, event_source_mapping_id, cfg)
    account, region = cfg["account"], cfg["region"]
    roles = [f"arn:aws:iam::{account}:role{cfg['role_path']}{cfg['functions'][key]['role_name']}" for key in FUNCTIONS]
    aliases = [f"arn:aws:iam::{account}:role/{cfg['functions'][key]['role_name']}" for key in FUNCTIONS]
    functions = [f"arn:aws:lambda:{region}:{account}:function:{cfg['functions'][key]['name']}" for key in FUNCTIONS]
    statements = [statement for statement in identity["Statement"] if statement["Effect"] == "Deny"]
    statements.append({"Effect": "Deny", "Action": "iam:*", "NotResource": roles + aliases})
    statements.append(deny("iam:PassRole", roles, {"StringNotEquals": {"iam:PassedToService": "lambda.amazonaws.com"}}))
    for key, role in zip(FUNCTIONS, roles):
        spec = cfg["functions"][key]
        boundary = f"arn:aws:iam::{account}:policy/{spec['boundary_policy_name']}"
        statements.append(deny(["iam:CreateRole", "iam:PutRolePolicy", "iam:UpdateAssumeRolePolicy",
                                "iam:AttachRolePolicy", "iam:DetachRolePolicy"], role,
                               {"ArnNotEquals": {"iam:PermissionsBoundary": boundary}}))
        statements.append(deny(["iam:AttachRolePolicy", "iam:DetachRolePolicy"], role, {"ArnNotEquals": {
            "iam:PolicyARN": [BASIC, SQS] if key == "JobWorkerFunction" else BASIC,
        }}))
    # Regional providers may need unscoped metadata reads, but never unscoped
    # writes. Each denied action set mirrors one reviewed identity action set.
    for service, selector in (("lambda:", "function:"), ("dynamodb:", "table/"), ("sqs:", ":actionbridge-"),
                              ("logs:", "log-group:"), ("apigateway:", "/apis/")):
        for statement in identity["Statement"]:
            action_list = statement.get("Action", [])
            action_list = [action_list] if isinstance(action_list, str) else action_list
            resource_list = statement.get("Resource", [])
            resource_list = [resource_list] if isinstance(resource_list, str) else resource_list
            if (statement["Effect"] == "Allow" and action_list and all(action.startswith(service) for action in action_list)
                    and resource_list and all(selector in resource for resource in resource_list)):
                statements.append({"Effect": "Deny", "Action": action_list, "NotResource": resource_list})
    mapping = f"arn:aws:lambda:{region}:{account}:event-source-mapping:{event_source_mapping_id or '*'}"
    statements += [
        deny(["lambda:CreateEventSourceMapping", "lambda:GetEventSourceMapping", "lambda:UpdateEventSourceMapping", "lambda:DeleteEventSourceMapping"],
             condition={"ArnNotEquals": {"lambda:FunctionArn": functions[-1]}}),
        # Rollback Get/Delete requests were authorized against Resource '*'.
        # The exact FunctionArn guard still denies missing or unrelated function
        # context. Keep Update additionally restricted to the reviewed mapping
        # ARN: its broader identity grant must never bypass this guardrail.
        {"Effect": "Deny", "Action": ["lambda:UpdateEventSourceMapping"], "NotResource": mapping},
        {"Effect": "Deny", "Action": "s3:*", "NotResource": [
            f"arn:aws:s3:::{cfg['buckets']['uploads']}", f"arn:aws:s3:::{cfg['buckets']['artifacts']}",
            f"arn:aws:s3:::{cfg['buckets']['artifacts']}/{cfg['artifact_prefix']}*",
        ]},
        {"Effect": "Deny", "Action": ["s3:CreateBucket", "s3:DeleteBucket", "s3:PutBucket*", "s3:PutLifecycleConfiguration", "s3:PutEncryptionConfiguration"],
         "NotResource": f"arn:aws:s3:::{cfg['buckets']['uploads']}"},
        deny(["s3:PutObject*", "s3:DeleteObject*", "s3:PutBucketPolicy", "s3:DeleteBucketPolicy", "s3:PutBucketAcl"]),
        {"Effect": "Deny", "Action": "s3:GetObject*", "NotResource": f"arn:aws:s3:::{cfg['buckets']['artifacts']}/{cfg['artifact_prefix']}*"},
        deny(["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan",
              "dynamodb:BatchGetItem", "dynamodb:BatchWriteItem", "dynamodb:ConditionCheckItem", "sqs:SendMessage", "sqs:ReceiveMessage",
              "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:PurgeQueue", "bedrock:InvokeModel*", "textract:*", "transcribe:*",
              "polly:*", "cognito-idp:*", "sts:AssumeRole", "logs:GetLogEvents", "logs:FilterLogEvents", "logs:StartQuery", "logs:GetQueryResults"]),
    ]
    # The alias exception must not become an alternate path for role creation,
    # attachment, inline policies, trust edits, PassRole, or boundary changes.
    statements += [
        {"Effect": "Deny", "NotAction": ["iam:GetRole", "iam:DetachRolePolicy"], "Resource": aliases},
        deny("iam:DetachRolePolicy", aliases, {"Null": {"iam:PermissionsBoundary": "false"}}),
    ]
    for key, alias in zip(FUNCTIONS, aliases):
        statements.append(deny("iam:DetachRolePolicy", alias, {"ArnNotEquals": {
            "iam:PolicyARN": [BASIC, SQS] if key == "JobWorkerFunction" else BASIC,
        }}))
    return {"Version": "2012-10-17", "Statement": statements}


def compact_size(document):
    return len(json.dumps(document, separators=(",", ":")))


def parts(document, limit=6144):
    """Split statements into valid managed-policy documents, preserving order."""
    output, current = [], []
    for statement in document["Statement"]:
        candidate = {"Version": document["Version"], "Statement": current + [statement]}
        if compact_size(candidate) > limit:
            if not current:
                raise ValueError("A statement exceeds the managed-policy size quota.")
            output.append({"Version": document["Version"], "Statement": current})
            current = [statement]
            if compact_size({"Version": document["Version"], "Statement": current}) > limit:
                raise ValueError("A statement exceeds the managed-policy size quota.")
        else:
            current.append(statement)
    if current:
        output.append({"Version": document["Version"], "Statement": current})
    return output


def write_backend_bundle(api_id, output_dir, event_source_mapping_id=None):
    identity = parts(backend_policy(api_id, event_source_mapping_id))
    guardrails = parts(guardrail_policy(api_id, event_source_mapping_id))
    documents = {}
    for label, policies in (("identity", identity), ("guardrails", guardrails)):
        for index, policy in enumerate(policies, 1):
            documents[f"{label}-{index:02d}.json"] = policy
    if len(documents) > 10:
        raise ValueError("Review bundle exceeds the default ten managed policies per role; reduce permissions before approval.")
    cfg = manifest()
    review = {
        "account": cfg["account"], "region": cfg["region"], "stack_name": cfg["stack_name"], "api_id": api_id,
        "ownership_verified": False, "execution_permissions_boundary": False,
        "event_source_mapping_id": event_source_mapping_id,
        "identity_policies": [name for name in documents if name.startswith("identity-")],
        "guardrail_policies": [name for name in documents if name.startswith("guardrails-")],
        "compact_sizes": {name: compact_size(policy) for name, policy in documents.items()},
        "review_requirements": [
            "Verify the API ID belongs to this stack in the reviewed account and Region.",
            "Require successful exact-name collision checks before creating named resources.",
            "Review every identity and guardrail part together; attach all guardrail parts.",
            "Do not attach additional or service-full-access policies to the execution role.",
            "The parts are identity policies, not a single permissions-boundary policy.",
            "Only an independent authorized administrator can change execution policies or protected boundary policies.",
            "Validate provider read-back and rollback behavior; unsupported calls remain denied.",
            "Narrow the event-source-mapping ARN to its captured UUID after creation.",
            "Recheck all five reserved role names are absent immediately before a retry; never adopt an existing role.",
            "Root aliases permit GetRole and allowlisted managed-policy detachment with no boundary context only; all other alias operations are denied.",
            "Absent boundary context cannot distinguish a missing role from an existing unbounded root role with the same reserved name; owner review must accept this cleanup exception.",
        ],
    }
    output_dir = safe_output_path(output_dir)
    output_dir.mkdir()  # Exclusive: even an empty existing directory is refused.
    for name, document in documents.items():
        with (output_dir / name).open("x") as handle:
            handle.write(encoded(document))
    with (output_dir / "review.json").open("x") as handle:
        handle.write(encoded(review))
    return review


def encoded(document):
    return json.dumps(document, indent=2) + "\n"


def safe_output_path(path):
    # absolute() retains symlink components; resolve() would hide them. Inspect
    # every ancestor before any creation, including paths containing '..'.
    output = Path(path).absolute()
    if any(component.is_symlink() for component in (output, *output.parents)):
        raise ValueError("Refusing an output path with a symlink component.")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check the public bootstrap draft without writing.")
    parser.add_argument("--api-id", help="Owner-reviewed HTTP API ID after bootstrap; does not verify ownership.")
    parser.add_argument("--event-source-mapping-id", help="Optional captured mapping UUID to narrow updates; cleanup remains exact-worker scoped.")
    parser.add_argument("--output-dir", type=Path, help="New local backend review-bundle directory; existing directories are never overwritten.")
    args = parser.parse_args(argv)
    if args.api_id is None and (args.output_dir is not None or args.event_source_mapping_id is not None):
        parser.error("--output-dir and --event-source-mapping-id require --api-id")
    if args.api_id is not None and (args.output_dir is None or args.check):
        parser.error("--api-id requires --output-dir and cannot be used with --check")
    try:
        if args.api_id is not None:
            review = write_backend_bundle(args.api_id, args.output_dir, args.event_source_mapping_id)
            print(f"Wrote local unapplied review bundle ({len(review['compact_sizes'])} policy parts, each at most 6144 compact characters). No AWS access.")
            print("Execution parts are identity policies, not a permissions boundary; all guardrail parts and independent administrator review are required.")
            return 0
        document = bootstrap_policy()
        data = encoded(document)
        target = BOOTSTRAP
        if args.check:
            if target.is_symlink() or not target.is_file() or target.read_text() != data:
                raise ValueError("Public bootstrap policy draft is missing or stale.")
            print("Public bootstrap policy draft is current. No AWS access.")
            return 0
        target = safe_output_path(target)
        if target.is_file() and target.read_text() == data:
            print("Public bootstrap policy draft is already current. No AWS access.")
            return 0
        with target.open("x") as handle:
            handle.write(data)
        size = len(json.dumps(document, separators=(",", ":")))
        print(f"Wrote local unapplied policy draft ({size} compact characters). No AWS access.")
        if size > 6144:
            print("Draft exceeds the managed-policy quota: administrator must split identity grants and review a compact execution ceiling before provisioning.")
        return 0
    except (ValueError, OSError) as exc:
        # Messages contain only static descriptions or output paths, never private file contents.
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
