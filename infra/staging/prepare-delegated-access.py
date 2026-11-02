#!/usr/bin/env python3
"""Prepare a fixed-account delegation stack; never contacts AWS or edits live state.

The owner controls access and runtime IAM in a separate stack. The application
executor cannot change IAM roles, boundaries, these ceiling policies, or itself.
Only candidate application templates are produced; existing templates stay intact.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ACCOUNT = "631367363628"
REGION = "us-east-2"
STACK = "actionbridge-dental-staging"
STACK_ID = f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{STACK}/474e7340-d02f-11f1-9274-02b90931d9ff"
ACCESS_STACK = STACK + "-access"
EXECUTOR = f"arn:aws:iam::{ACCOUNT}:role/{STACK}-cfn"
DEPLOYER_NAME = STACK + "-deployer"
DEPLOYER = f"arn:aws:iam::{ACCOUNT}:role/{DEPLOYER_NAME}"
DEVELOPER = f"arn:aws:iam::{ACCOUNT}:user/actionbridge-developer"
API = f"arn:aws:apigateway:{REGION}::/apis/l52iwors8c"
STAGE = API + "/stages/staging"
TAG_STAGE = f"arn:aws:apigateway:{REGION}::/tags/" + quote(STAGE, safe="")
TABLE = f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{STACK}-cases"
ARTIFACTS = f"arn:aws:s3:::ab-dental-staging-artifacts-{ACCOUNT}-{REGION}"
UPLOADS = f"arn:aws:s3:::ab-dental-staging-uploads-{ACCOUNT}-{REGION}"
POOL = f"arn:aws:cognito-idp:{REGION}:{ACCOUNT}:userpool/us-east-2_GErUtH894"
SLUGS = ("health", "cases", "calculations", "jobs", "job-worker")
LOGICAL = ("HealthFunction", "CasesFunction", "CalculationsFunction", "JobsFunction", "JobWorkerFunction")
FUNCTIONS = [f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{STACK}-{slug}" for slug in SLUGS]
ROLES = [f"arn:aws:iam::{ACCOUNT}:role/actionbridge/staging/{STACK}/{STACK}-{slug}-role" for slug in SLUGS]
ALIASES = [f"arn:aws:iam::{ACCOUNT}:role/{STACK}-{slug}-role" for slug in SLUGS]
BOUNDARIES = [f"arn:aws:iam::{ACCOUNT}:policy/{STACK}-{slug}-boundary" for slug in SLUGS]
POLICIES = [f"arn:aws:iam::{ACCOUNT}:policy/{STACK}-cfn-{suffix}" for suffix in
            ("identity-01", "identity-02", "identity-03", "guardrails-01", "guardrails-02")]
EDITABLE = [POLICIES[index] for index in (1, 2, 4)]
OWNER_POLICIES = [f"arn:aws:iam::{ACCOUNT}:policy/{STACK}-{suffix}-{index}" for suffix, count in
                 (("owner-ceiling", 3), ("deployer", 4)) for index in range(1, count + 1)]
QUEUES = [f"arn:aws:sqs:{REGION}:{ACCOUNT}:{STACK}-{suffix}" for suffix in ("jobs", "dlq")]
LOGS = [f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/lambda/{STACK}-{slug}" for slug in SLUGS]
OHIO = {"StringEquals": {"aws:RequestedRegion": REGION}}
RESOURCE_TYPES = ["AWS::ApiGatewayV2::Api", "AWS::ApiGatewayV2::Authorizer", "AWS::ApiGatewayV2::Integration",
                  "AWS::ApiGatewayV2::Route", "AWS::ApiGatewayV2::Stage", "AWS::DynamoDB::Table", "AWS::Lambda::Function",
                  "AWS::Lambda::Permission", "AWS::Lambda::EventSourceMapping", "AWS::Logs::LogGroup", "AWS::S3::Bucket", "AWS::SQS::Queue"]
POLICY_SOURCE = ROOT / ".staging/core-forward-deployment-review/policies-http-stage-tagging"
APP = {"Fn::GetAtt": ["FrontendApp", "Arn"]}


def doc(statements):
    return {"Version": "2012-10-17", "Statement": statements}


def statement(effect, actions=None, resource="*", *, not_actions=None, not_resource=None, condition=None, sid=None):
    value = {"Effect": effect, "Action" if actions is not None else "NotAction": actions if actions is not None else not_actions,
             "NotResource" if not_resource is not None else "Resource": not_resource if not_resource is not None else resource}
    if condition:
        value["Condition"] = condition
    if sid:
        value["Sid"] = sid
    return value


def compact_size(value):
    return len(json.dumps(value, separators=(",", ":")))


def split_policy(policy, max_size=5800):
    parts, entries = [], []
    for entry in policy["Statement"]:
        if compact_size(doc(entries + [entry])) > max_size:
            if not entries:
                raise ValueError("Single statement exceeds managed policy quota")
            parts.append(doc(entries))
            entries = []
        entries.append(entry)
    if entries:
        parts.append(doc(entries))
    return parts


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def ceilings():
    """Deny-only independent ceiling, in addition to the existing five policies.

    Deliberately no IAM mutation. External owner-managed runtime roles remove
    the otherwise unenforceable trust-document escalation through CreateRole.
    Mapping metadata reads have no function-condition to survive deletion; mapping
    mutations remain gated by the service-supported lambda:FunctionArn context.
    """
    original = [json.loads((POLICY_SOURCE / (name + ".json")).read_text()) for name in
                ("identity-01", "identity-02", "identity-03")]
    actions = set()
    for policy in original:
        for entry in policy["Statement"]:
            if entry["Effect"] != "Allow":
                continue
            actions.update(entry["Action"] if isinstance(entry["Action"], list) else [entry["Action"]])
    actions = {action for action in actions if not action.startswith("iam:")}
    actions.update(("iam:GetRole", "iam:PassRole", "lambda:ListEventSourceMappings", "lambda:GetFunctionConcurrency",
                    "lambda:PutFunctionConcurrency", "lambda:DeleteFunctionConcurrency", "lambda:GetRuntimeManagementConfig",
                    "dynamodb:DescribeContinuousBackups", "dynamodb:UpdateContinuousBackups"))
    mapping = ["lambda:CreateEventSourceMapping", "lambda:GetEventSourceMapping", "lambda:UpdateEventSourceMapping",
               "lambda:DeleteEventSourceMapping", "lambda:ListEventSourceMappings"]
    mapping_tags = ["lambda:TagResource", "lambda:UntagResource", "lambda:ListTags"]
    function_actions = sorted(action for action in actions if action.startswith("lambda:") and action not in mapping)
    api_resources = [API, API + "/cors", API + "/authorizers", API + "/authorizers/*",
                     API + "/integrations", API + "/integrations/*", API + "/routes", API + "/routes/*",
                     API + "/stages", STAGE, TAG_STAGE]
    base = [
        statement("Deny", not_actions=sorted(actions), sid="CeilingNoUnlistedActions"),
        statement("Deny", not_actions=["iam:*", "s3:*"],
                  condition={"StringNotEquals": {"aws:RequestedRegion": REGION}}, sid="CeilingOhio"),
        statement("Deny", "iam:*", not_resource=ROLES + ALIASES, sid="CeilingNoOtherIAM"),
        statement("Deny", "iam:PassRole", condition={"StringNotEquals": {"iam:PassedToService": "lambda.amazonaws.com"}},
                  sid="CeilingPassRuntimeOnlyToLambda"),
        statement("Deny", "iam:PassRole", not_resource=ROLES, sid="CeilingNoPassingAliasRoles"),
        statement("Deny", "apigateway:*", not_resource=api_resources, sid="CeilingNoOtherAPI"),
        statement("Deny", "apigateway:DELETE", API, sid="CeilingPreserveOriginalAPI"),
        statement("Deny", [action for action in function_actions if action not in mapping_tags], not_resource=FUNCTIONS,
                  sid="CeilingOnlyNamedFunctions"),
        statement("Deny", mapping_tags, not_resource=FUNCTIONS + [f"arn:aws:lambda:{REGION}:{ACCOUNT}:event-source-mapping:*"],
                  sid="CeilingOnlyFunctionsAndMappingTags"),
        statement("Deny", "lambda:AddPermission", condition={"StringNotEquals": {"lambda:Principal": "apigateway.amazonaws.com"}},
                  sid="CeilingOnlyGatewayInvokeGrants"),
    ]
    storage = [
        statement("Deny", "dynamodb:*", not_resource=[TABLE], sid="CeilingOnlyCasesTable"),
        statement("Deny", "sqs:*", not_resource=QUEUES, sid="CeilingOnlyStagingQueues"),
        statement("Deny", sorted(action for action in actions if action.startswith("logs:") and action != "logs:DescribeLogGroups"),
                  not_resource=LOGS + [arn + ":*" for arn in LOGS], sid="CeilingOnlyStagingLogs"),
        statement("Deny", "s3:*", not_resource=[UPLOADS, ARTIFACTS, ARTIFACTS + "/" + STACK + "/*"], sid="CeilingOnlyTwoBuckets"),
        statement("Deny", not_actions=["s3:GetObject", "s3:GetBucketLocation"],
                  resource=[ARTIFACTS, ARTIFACTS + "/*"], sid="CeilingArtifactsReadOnly"),
        statement("Deny", "s3:*", condition={"StringNotEquals": {"s3:ResourceAccount": ACCOUNT}},
                  resource=[UPLOADS, ARTIFACTS, ARTIFACTS + "/" + STACK + "/*"], sid="CeilingExpectedBucketAccount"),
        statement("Deny", "s3:CreateBucket", UPLOADS, condition={"StringNotEquals": {"s3:LocationConstraint": REGION}},
                  sid="CeilingUploadsOnlyOhio"),
        statement("Deny", ["lambda:CreateEventSourceMapping", "lambda:UpdateEventSourceMapping", "lambda:DeleteEventSourceMapping"],
                  condition={"ArnNotEquals": {"lambda:FunctionArn": FUNCTIONS[4]}}, sid="CeilingMappingOnlyWorker"),
        statement("Deny", ["lambda:UpdateEventSourceMapping", "lambda:DeleteEventSourceMapping"],
                  not_resource=f"arn:aws:lambda:{REGION}:{ACCOUNT}:event-source-mapping:*", sid="CeilingMappingAccount"),
        # Tag-on-create does not expose FunctionArn. The executor is usable only
        # through this stack's normal, type-filtered non-import change sets. ESM
        # has no customer-specified UUID at create, so it cannot adopt other ESMs.
        statement("Deny", ["lambda:TagResource", "lambda:UntagResource"],
                  f"arn:aws:lambda:{REGION}:{ACCOUNT}:event-source-mapping:*",
                  condition={"StringNotEquals": {"aws:RequestTag/ActionBridgeScope": STACK,
                                                   "aws:ResourceTag/ActionBridgeScope": STACK}}, sid="CeilingMappingTagOwnership"),
    ]
    # CreateBucket does not always have s3:ResourceAccount until the bucket exists.
    # Do not gate CreateBucket with that unavailable key: scope+LocationConstraint
    # check the prospective resource, while all subsequent bucket ops check owner.
    storage[5]["Action"] = sorted(action for action in actions if action.startswith("s3:") and action != "s3:CreateBucket")
    return [*split_policy(doc(base)), *split_policy(doc(storage))]


def deployer_policy():
    stack_read = ["cloudformation:DescribeStacks", "cloudformation:DescribeStackEvents", "cloudformation:ListStackResources",
                  "cloudformation:DescribeStackResource", "cloudformation:DescribeStackResources", "cloudformation:GetTemplate",
                  "cloudformation:GetStackPolicy", "cloudformation:ListChangeSets", "cloudformation:DescribeChangeSet",
                  "cloudformation:DeleteChangeSet"]
    role_read = ["iam:GetRole", "iam:ListAttachedRolePolicies", "iam:ListRolePolicies", "iam:GetRolePolicy", "iam:ListRoleTags"]
    allow = [
        statement("Allow", ["signin:AuthorizeOAuth2Access", "signin:CreateOAuth2Token"],
                  f"arn:aws:signin:{REGION}:{ACCOUNT}:oauth2/public-client/localhost"),
        statement("Allow", "sts:GetCallerIdentity"),
        statement("Allow", stack_read, STACK_ID, condition=OHIO),
        statement("Allow", "cloudformation:DescribeStacks", {"Ref": "AWS::StackId"}, condition=OHIO),
        statement("Allow", "cloudformation:CreateChangeSet", STACK_ID, condition={"StringEquals": {
            "aws:RequestedRegion": REGION, "cloudformation:RoleArn": EXECUTOR},
            "ForAllValues:StringEquals": {"cloudformation:ResourceTypes": RESOURCE_TYPES},
            "Null": {"cloudformation:ResourceTypes": "false"}}),
        statement("Allow", ["cloudformation:ExecuteChangeSet", "cloudformation:ContinueUpdateRollback", "cloudformation:CancelUpdateStack",
                            "cloudformation:TagResource", "cloudformation:UntagResource"], STACK_ID, condition=OHIO),
        statement("Allow", ["cloudformation:ValidateTemplate", "cloudformation:GetTemplateSummary", "cloudformation:DescribeType"],
                  condition=OHIO),
        statement("Allow", "iam:PassRole", EXECUTOR, condition={"StringEquals": {"iam:PassedToService": "cloudformation.amazonaws.com"}}),
        statement("Allow", role_read, [EXECUTOR, DEPLOYER] + ROLES + ALIASES),
        statement("Allow", ["iam:GetPolicy", "iam:GetPolicyVersion", "iam:ListPolicyVersions"], POLICIES + BOUNDARIES + OWNER_POLICIES),
        statement("Allow", ["iam:CreatePolicyVersion", "iam:SetDefaultPolicyVersion"], EDITABLE),
        statement("Allow", ["iam:SimulateCustomPolicy", "access-analyzer:ValidatePolicy"]),
        statement("Allow", "iam:SimulatePrincipalPolicy", [EXECUTOR] + ROLES),
        statement("Allow", "apigateway:GET", [API, API + "/*", TAG_STAGE], condition=OHIO),
        statement("Allow", ["lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:GetFunctionConcurrency",
                            "lambda:GetPolicy", "lambda:ListTags"], FUNCTIONS, condition=OHIO),
        statement("Allow", ["lambda:GetEventSourceMapping", "lambda:ListEventSourceMappings"], condition=OHIO),
        statement("Allow", ["dynamodb:DescribeTable", "dynamodb:DescribeTimeToLive", "dynamodb:DescribeContinuousBackups",
                            "dynamodb:ListTagsOfResource"], TABLE, condition=OHIO),
        statement("Allow", ["sqs:GetQueueUrl", "sqs:GetQueueAttributes", "sqs:ListQueueTags"], QUEUES, condition=OHIO),
        statement("Allow", ["cognito-idp:DescribeUserPool", "cognito-idp:DescribeUserPoolClient", "cognito-idp:ListTagsForResource"],
                  POOL, condition=OHIO),
        statement("Allow", ["s3:GetBucketLocation", "s3:GetBucketPublicAccessBlock", "s3:GetEncryptionConfiguration", "s3:GetBucketOwnershipControls"],
                  [ARTIFACTS, UPLOADS], condition={"StringEquals": {"s3:ResourceAccount": ACCOUNT}}),
        statement("Allow", "s3:ListBucket", ARTIFACTS, condition={"StringEquals": {"s3:ResourceAccount": ACCOUNT},
                  "StringLike": {"s3:prefix": [STACK + "/", STACK + "/*"]}}),
        statement("Allow", "s3:GetObject", ARTIFACTS + "/" + STACK + "/*", condition={"StringEquals": {"s3:ResourceAccount": ACCOUNT}}),
        statement("Allow", "s3:PutObject", ARTIFACTS + "/" + STACK + "/*", condition={"StringEquals": {
            "s3:ResourceAccount": ACCOUNT, "s3:x-amz-server-side-encryption": "AES256", "s3:if-none-match": "*"}}),
        statement("Allow", ["logs:DescribeLogStreams", "logs:GetLogEvents", "logs:FilterLogEvents", "logs:ListTagsForResource"],
                  LOGS + [arn + ":*" for arn in LOGS], condition=OHIO),
        statement("Allow", ["servicequotas:GetServiceQuota", "servicequotas:ListServiceQuotas"], condition=OHIO),
        statement("Allow", ["amplify:GetApp", "amplify:UpdateApp", "amplify:ListBranches", "amplify:ListTagsForResource",
                            "amplify:ListArtifacts"], APP, condition=OHIO),
        statement("Allow", ["amplify:CreateBranch", "amplify:GetBranch", "amplify:UpdateBranch", "amplify:DeleteBranch",
                            "amplify:CreateDeployment", "amplify:StartDeployment", "amplify:ListJobs", "amplify:TagResource",
                            "amplify:UntagResource", "amplify:ListTagsForResource"],
                  {"Fn::Sub": ["${AppArn}/branches/staging", {"AppArn": APP}]}, condition=OHIO),
        statement("Allow", ["amplify:GetJob", "amplify:StopJob"],
                  {"Fn::Sub": ["${AppArn}/branches/staging/jobs/*", {"AppArn": APP}]}, condition=OHIO),
    ]
    deny = [
        statement("Deny", ["sts:AssumeRole", "sts:AssumeRoleWithSAML", "sts:AssumeRoleWithWebIdentity", "sts:GetFederationToken",
                           "lambda:InvokeFunction", "lambda:InvokeAsync"], sid="NoRoleChainingOrForgedGatewayInvocations"),
        statement("Deny", ["cloudformation:CreateStack", "cloudformation:UpdateStack", "cloudformation:DeleteStack",
                           "cloudformation:SetStackPolicy", "cloudformation:RollbackStack", "cloudformation:UpdateTerminationProtection"]),
        statement("Deny", ["cloudformation:CreateChangeSet", "cloudformation:ExecuteChangeSet", "cloudformation:ContinueUpdateRollback",
                           "cloudformation:CancelUpdateStack", "cloudformation:TagResource", "cloudformation:UntagResource",
                           "cloudformation:DeleteChangeSet"],
                  not_resource=[STACK_ID], sid="NoOtherStackMutation"),
        statement("Deny", "cloudformation:CreateChangeSet", condition={"Null": {"cloudformation:ImportResourceTypes": "false"}},
                  sid="NeverImportExistingResources"),
        statement("Deny", ["cloudformation:CreateChangeSet", "cloudformation:ContinueUpdateRollback"], STACK_ID,
                  condition={"Null": {"cloudformation:RoleArn": "false"}, "ArnNotEquals": {"cloudformation:RoleArn": EXECUTOR}},
                  sid="NoWrongExecutionRoleWhenSupplied"),
        statement("Deny", ["iam:CreatePolicyVersion", "iam:SetDefaultPolicyVersion"], not_resource=EDITABLE),
        statement("Deny", ["iam:CreateRole", "iam:UpdateAssumeRolePolicy", "iam:AttachRolePolicy", "iam:DetachRolePolicy",
                           "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:PutRolePermissionsBoundary", "iam:DeleteRolePermissionsBoundary",
                           "iam:DeleteRole", "iam:CreatePolicy", "iam:DeletePolicy", "iam:DeletePolicyVersion",
                           "iam:CreateAccessKey", "iam:CreateLoginProfile", "iam:PutUserPolicy", "iam:AttachUserPolicy"]),
        statement("Deny", "iam:PassRole", not_resource=EXECUTOR),
        statement("Deny", "iam:PassRole", condition={"StringNotEquals": {"iam:PassedToService": "cloudformation.amazonaws.com"}}),
        statement("Deny", ["amplify:CreateApp", "amplify:DeleteApp", "amplify:StartJob", "amplify:CreateBackendEnvironment",
                           "amplify:CreateDomainAssociation", "amplify:CreateWebHook"]),
        statement("Deny", "amplify:*", not_resource=[APP, {"Fn::Sub": ["${AppArn}/branches/staging", {"AppArn": APP}]},
                                                     {"Fn::Sub": ["${AppArn}/branches/staging/jobs/*", {"AppArn": APP}]}]),
        statement("Deny", "s3:PutObject", not_resource=ARTIFACTS + "/" + STACK + "/*", sid="NoOtherArtifactDestinations"),
    ]
    for index, (key, value) in enumerate((("s3:ResourceAccount", ACCOUNT), ("s3:if-none-match", "*"),
                                         ("s3:x-amz-server-side-encryption", "AES256")), 1):
        deny.append(statement("Deny", "s3:PutObject", ARTIFACTS + "/" + STACK + "/*",
                              condition={"StringNotEquals": {key: value}}, sid=f"RequireArtifactWriteContext{index}"))
    # Explicit denials also constrain grants made directly to a role session by
    # resource policies. An implicit identity-policy denial would not do so.
    approved_actions = sorted({action for entry in allow for action in
                               (entry["Action"] if isinstance(entry["Action"], list) else [entry["Action"]])})
    deny.extend([
        statement("Deny", not_actions=approved_actions, sid="DeployerNoUnlistedActions"),
        statement("Deny", not_actions=["iam:*", "s3:*", "sts:*", "signin:*"],
                  condition={"StringNotEquals": {"aws:RequestedRegion": REGION}}, sid="DeployerOhio"),
        statement("Deny", "s3:*", not_resource=[ARTIFACTS, ARTIFACTS + "/" + STACK + "/*", UPLOADS], sid="DeployerOnlyStagingBuckets"),
        statement("Deny", "sqs:*", not_resource=QUEUES, sid="DeployerOnlyStagingQueues"),
        statement("Deny", "dynamodb:*", not_resource=TABLE, sid="DeployerOnlyCasesTable"),
        statement("Deny", ["lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:GetFunctionConcurrency",
                           "lambda:GetPolicy", "lambda:ListTags"], not_resource=FUNCTIONS, sid="DeployerOnlyNamedFunctionReads"),
    ])
    return doc(allow + deny)


def runtime_roles():
    resources = {}
    for logical, slug, boundary in zip(LOGICAL, SLUGS, BOUNDARIES):
        boundary_doc = json.loads((HERE / "generated" / (STACK + "-" + slug + "-boundary.json")).read_text())
        resources[logical + "Role"] = {
            "Type": "AWS::IAM::Role", "DeletionPolicy": "Retain", "UpdateReplacePolicy": "Retain",
            "Properties": {"RoleName": STACK + "-" + slug + "-role", "Path": f"/actionbridge/staging/{STACK}/",
                "AssumeRolePolicyDocument": doc([{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]),
                "PermissionsBoundary": boundary,
                "Policies": [{"PolicyName": "OwnerFixedRuntime", "PolicyDocument": doc([
                    entry for entry in boundary_doc["Statement"] if entry["Effect"] == "Allow"])}],
                "Tags": [{"Key": "ActionBridgeScope", "Value": STACK}]}}
    return resources


def candidate_template(source):
    template = copy.deepcopy(source)
    for logical, arn in zip(LOGICAL, ROLES):
        if logical not in template["Resources"]:
            continue
        role_id = logical + "Role"
        if template["Resources"][role_id]["Type"] != "AWS::IAM::Role":
            raise ValueError("Unexpected runtime role type")
        template["Resources"].pop(role_id)
        if template["Resources"][logical]["Properties"]["Role"] != {"Fn::GetAtt": [role_id, "Arn"]}:
            raise ValueError("Unexpected function Role dependency")
        template["Resources"][logical]["Properties"]["Role"] = arn
    for resource in template["Resources"].values():
        if resource["Type"] == "AWS::Lambda::EventSourceMapping":
            tags = resource["Properties"].setdefault("Tags", [])
            if tags:
                raise ValueError("Unreviewed mapping tags; do not silently merge")
            tags.append({"Key": "ActionBridgeScope", "Value": STACK})
    # Reject every unexpected dependency instead of silently dropping fields.
    for logical in LOGICAL:
        if logical + "Role" in json.dumps(template):
            raise ValueError("Unresolved role reference: " + logical)
    template["Description"] += " Runtime IAM is external and owner-managed by the dedicated access stack."
    return template


def validate_core_change_set_request(request, reviewed_template):
    """Local request guard; does not submit anything to CloudFormation.

    IAM's ImportResourceTypes condition covers explicit import requests. AWS
    documents no equivalent condition for the newer automatic-import switch, so
    reject it explicitly here and compare the complete reviewed template.
    """
    required = {"StackName": STACK_ID, "RoleARN": EXECUTOR, "ChangeSetType": "UPDATE",
                "ImportExistingResources": False, "IncludeNestedStacks": False}
    for key, expected in required.items():
        if request.get(key) != expected or (isinstance(expected, bool) and request.get(key) is not expected):
            raise ValueError("Unexpected change-set request field: " + key)
    if any(key in request for key in ("ResourcesToImport", "Capabilities", "TemplateURL", "UsePreviousTemplate")):
        raise ValueError("Imports, capabilities, alternate template URLs and previous templates are forbidden")
    if set(request.get("ResourceTypes", [])) != set(RESOURCE_TYPES):
        raise ValueError("The exact reviewed non-IAM resource-type filter is required")
    if json.loads(request.get("TemplateBody", "null")) != reviewed_template:
        raise ValueError("Template differs from the complete reviewed core candidate")
    if not reviewed_template["Resources"]["HttpApi"]["Properties"].get("DisableExecuteApiEndpoint"):
        raise ValueError("This core phase must keep public traffic disabled")
    if any(item["Type"] == "AWS::Lambda::EventSourceMapping" for item in reviewed_template["Resources"].values()):
        raise ValueError("Core phase must defer worker mappings")
    return True


def access_template():
    resources = runtime_roles()
    ceiling_ids = []
    for index, policy in enumerate(ceilings(), start=1):
        if compact_size(policy) > 6144:
            raise ValueError("Ceiling exceeds managed policy size quota")
        logical = f"ExecutionCeiling{index}"
        ceiling_ids.append(logical)
        resources[logical] = {"Type": "AWS::IAM::ManagedPolicy", "DeletionPolicy": "Retain", "UpdateReplacePolicy": "Retain",
            "Properties": {"ManagedPolicyName": f"{STACK}-owner-ceiling-{index}", "PolicyDocument": policy,
                           "Roles": [STACK + "-cfn"]}}
    resources["FrontendApp"] = {"Type": "AWS::Amplify::App", "DeletionPolicy": "Retain", "UpdateReplacePolicy": "Retain",
        "Properties": {"Name": STACK + "-web", "Platform": "WEB", "EnableBranchAutoDeletion": False,
                       "Description": "Independent static frontend. Empty app; branch/publication requires separate approval.",
                       "Tags": [{"Key": "ActionBridgeScope", "Value": STACK}],
                       "CustomRules": [{"Source": "/<*>", "Target": "/index.html", "Status": "404-200"}]}}
    resources["DeployerRole"] = {"Type": "AWS::IAM::Role", "DependsOn": ceiling_ids + [logical + "Role" for logical in LOGICAL],
        "Properties": {"RoleName": DEPLOYER_NAME, "MaxSessionDuration": 3600,
            "Description": "MFA staging deployer; owner access stack and ceilings are outside its authority.",
            "AssumeRolePolicyDocument": doc([{"Effect": "Allow", "Principal": {"AWS": DEVELOPER}, "Action": "sts:AssumeRole",
                                             "Condition": {"Bool": {"aws:MultiFactorAuthPresent": "true"}}}])}}
    for index, policy in enumerate(split_policy(deployer_policy()), 1):
        resources[f"DeployerPolicy{index}"] = {"Type": "AWS::IAM::ManagedPolicy", "Properties": {
            "ManagedPolicyName": f"{STACK}-deployer-{index}", "PolicyDocument": policy,
            "Roles": [{"Ref": "DeployerRole"}]}}
    return {"AWSTemplateFormatVersion": "2010-09-09", "Description": "ActionBridge owner-controlled staging delegation. No application deployment or website publication.",
            "Rules": {"CorrectAccount": {"Assertions": [{"Assert": {"Fn::Equals": [{"Ref": "AWS::AccountId"}, ACCOUNT]},
                 "AssertDescription": "Only AWS account 631367363628 is authorized."}]},
                 "CorrectRegion": {"Assertions": [{"Assert": {"Fn::Equals": [{"Ref": "AWS::Region"}, REGION]},
                 "AssertDescription": "Only Ohio us-east-2 is authorized."}]}},
            "Resources": resources,
            "Outputs": {"DeployerRoleArn": {"Value": {"Fn::GetAtt": ["DeployerRole", "Arn"]}},
                        "FrontendAppId": {"Value": {"Fn::GetAtt": ["FrontendApp", "AppId"]}},
                        "FrontendAppArn": {"Value": APP},
                        "SwitchRoleURL": {"Value": f"https://signin.aws.amazon.com/switchrole?account={ACCOUNT}&roleName={DEPLOYER_NAME}"}}}


def prepare(output):
    if output.exists():
        raise ValueError("Output already exists; refusing to overwrite the reviewed setup")
    for name, expected in {"identity-03.json": "bbe5d560e4a6d61d1e92323afa005cd7a5ebafbf7c5dd56b35deabe6e0bfc5f4",
                           "guardrails-02.json": "5ac45fcaaf967fe8cfdc5d42036af58b046d8de5d96ac9953d0db7edd36a8f2c"}.items():
        if hashlib.sha256((POLICY_SOURCE / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Reviewed HTTP tagging replacement changed: " + name)
    access = access_template()
    core = yaml.safe_load((HERE / "generated/core.yaml").read_text())
    backend = yaml.safe_load((HERE / "generated/backend.yaml").read_text())
    candidate_core, candidate_backend = candidate_template(core), candidate_template(backend)
    review = {"status": "LOCAL_PREPARATION_ONLY_AWAITING_OWNER_APPROVAL_AND_LIVE_PREFLIGHT", "aws_mutations": False,
              "account": ACCOUNT, "region": REGION, "existing_stack": STACK_ID, "existing_api": "l52iwors8c",
              "access_stack_name": ACCESS_STACK, "deployer_role": DEPLOYER,
              "access_resources": {key: item["Type"] for key, item in access["Resources"].items()},
              "ceiling_policy_compact_sizes": [compact_size(value) for value in ceilings()],
              "existing_executor_policy_attachments_last_recorded": 5,
              "attachments_after_setup_if_unchanged": 5 + len(ceilings()),
              "deployer_managed_policy_sizes_before_intrinsic_resolution": [compact_size(value) for value in split_policy(deployer_policy())],
              "new_core_resources": len(candidate_core["Resources"]), "expected_core_additions": 40,
              "expected_core_modifications": [{"logical_id": "HttpApi", "replacement": False}], "expected_core_removals": 0,
              "core_role_ownership_change": "Three absent runtime roles move to access stack; app candidate has 40 additions rather than 43.",
              "editable_policy_arns": EDITABLE, "previous_iam_versions": "Retained; DeletePolicyVersion explicitly denied. Stop at capacity.",
              "source_hashes": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                for path in [HERE / "generated/core.yaml", HERE / "generated/backend.yaml",
                                             *[HERE / "generated" / (STACK + "-" + slug + "-boundary.json") for slug in SLUGS],
                                             *[POLICY_SOURCE / (name + ".json") for name in ("identity-01", "identity-02", "identity-03", "guardrails-01", "guardrails-02")]]},
              "remaining_gates": ["Fresh AWS identity/role/stack/resource collision and quota checks; owner must verify policy versions where developer reads are denied",
                  "Owner approves and creates access stack, then developer MFA SwitchRole and aws login",
                  "Live original policy/version/boundary checks; apply exact two HTTP tag replacements only after approval",
                  "Separate consolidated runtime-cost, core execution, Amplify publication and traffic approval",
                  "Background AI remains disabled until mapping cleanup and synthetic end-to-end tests pass"],
              "mapping_limit": "Mapping reads after deletion need no FunctionArn. Mutations require exact worker FunctionArn; account/Ohio mapping tagging requires existing/requested staging marker. Deployer has no direct Lambda writes and cannot import/adopt mappings; only normal type-filtered staging change sets. Actual provider tag-on-create and read-after-delete behavior still require live preflight before AI execution.",
              "cost_scope": "IAM roles/policies plus an empty WEB Amplify app only; no branch, build, deployment, Lambda, table or queue created by access setup. Console template S3 upload can incur normal S3 costs."}
    output.mkdir(parents=True)
    for name, value in (("access-stack.json", access), ("core-delegated.json", candidate_core), ("backend-delegated.json", candidate_backend), ("review.json", review)):
        (output / name).write_text(json.dumps(value, indent=2) + "\n")
    for index, policy in enumerate(ceilings(), 1):
        (output / f"execution-ceiling-{index}.json").write_text(json.dumps(policy, indent=2) + "\n")
    (output / "deployer-policy.json").write_text(json.dumps(deployer_policy(), indent=2) + "\n")
    return review


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.output.resolve()), indent=2))
