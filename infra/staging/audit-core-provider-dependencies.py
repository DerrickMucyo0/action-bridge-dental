#!/usr/bin/env python3
"""Offline, fail-closed classification of the exact delegated core lifecycle.

A provider schema is a union of permissions for optional features. This audit
accounts for every schema action without granting that union. Missing metadata
getters are deliberately reported as unproven, even when their feature property
is absent: desired properties alone cannot prove what READ calls a provider uses.
No AWS operations, policy changes or deployment operations exist in this tool.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STACK, ACCOUNT, REGION = "actionbridge-dental-staging", "631367363628", "us-east-2"
API = f"arn:aws:apigateway:{REGION}::/apis/l52iwors8c"
TYPES = {"AWS::ApiGatewayV2::" + kind for kind in ("Api", "Authorizer", "Integration", "Route", "Stage")} | {
    "AWS::DynamoDB::Table", "AWS::Lambda::Function", "AWS::Lambda::Permission", "AWS::Logs::LogGroup"}

# These guards describe the reviewed feature set, rather than silently treating a
# newly added property as optional. Changes require revisiting classification.
PROPERTIES = {
    "AWS::ApiGatewayV2::Api": {"CorsConfiguration", "DisableExecuteApiEndpoint", "Name", "ProtocolType"},
    "AWS::ApiGatewayV2::Authorizer": {"ApiId", "AuthorizerType", "IdentitySource", "JwtConfiguration", "Name"},
    "AWS::ApiGatewayV2::Integration": {"ApiId", "IntegrationMethod", "IntegrationType", "IntegrationUri", "PayloadFormatVersion"},
    "AWS::ApiGatewayV2::Route": {"ApiId", "AuthorizationType", "AuthorizerId", "RouteKey", "Target"},
    "AWS::ApiGatewayV2::Stage": {"ApiId", "AutoDeploy", "DefaultRouteSettings", "StageName", "Tags"},
    "AWS::Lambda::Function": {"Architectures", "Code", "Description", "Environment", "FunctionName", "Handler", "MemorySize", "Role", "Runtime", "Tags", "Timeout"},
    "AWS::Lambda::Permission": {"Action", "FunctionName", "Principal", "SourceArn"},
    "AWS::DynamoDB::Table": {"AttributeDefinitions", "BillingMode", "KeySchema", "SSESpecification", "TableName", "TimeToLiveSpecification"},
    "AWS::Logs::LogGroup": {"LogGroupName", "RetentionInDays"},
}

LAMBDA_REQUIRED = {"lambda:CreateFunction", "lambda:GetFunction", "lambda:UpdateFunctionConfiguration", "lambda:UpdateFunctionCode",
                   "lambda:DeleteFunction", "lambda:TagResource", "lambda:UntagResource", "lambda:ListTags", "iam:PassRole", "s3:GetObject"}
LAMBDA_GETTERS = {"lambda:GetRuntimeManagementConfig", "lambda:GetFunctionCodeSigningConfig", "lambda:GetFunctionRecursionConfig", "lambda:GetFunctionScalingConfig"}
LAMBDA_CONDITIONAL = {
    **{a: "VpcConfig is absent; no VPC attachment or ENI cleanup is configured." for a in
       ("ec2:DescribeSecurityGroups", "ec2:DescribeSubnets", "ec2:DescribeVpcs", "ec2:DescribeNetworkInterfaces")},
    "elasticfilesystem:DescribeMountTargets": "FileSystemConfigs is absent; no EFS mount is configured.",
    "s3files:ListMountTargets": "FileSystemConfigs is absent; no S3 Files mount is configured.",
    "s3:GetObjectVersion": "Code.S3ObjectVersion is absent; the existing content-addressed ZIP key is used.",
    "lambda:GetLayerVersion": "Layers is absent.",
    **{a: "ReservedConcurrentExecutions is absent; this candidate does not change reserved concurrency." for a in
       ("lambda:PutFunctionConcurrency", "lambda:DeleteFunctionConcurrency")},
    **{a: "CodeSigningConfigArn is absent; no code-signing configuration is changed." for a in
       ("lambda:GetCodeSigningConfig", "lambda:PutFunctionCodeSigningConfig", "lambda:DeleteFunctionCodeSigningConfig")},
    "lambda:PutRuntimeManagementConfig": "RuntimeManagementConfig is absent; default automatic management is retained.",
    "lambda:PutFunctionRecursionConfig": "RecursiveLoop is absent; no recursion setting is changed.",
    "lambda:PutFunctionScalingConfig": "FunctionScalingConfig is absent.",
    "lambda:PublishVersion": "PublishToLatestPublished is absent; no version publication is configured.",
    "lambda:PassCapacityProvider": "CapacityProviderConfig is absent.",
    "lambda:AssociateRuntimeAlias": "CapacityProviderConfig, TenancyConfig and DurableConfig are absent.",
}
KMS_SCHEMA_ACTIONS = {"kms:CreateGrant", "kms:Decrypt", "kms:DescribeKey", "kms:Encrypt", "kms:GenerateDataKey", "kms:ListAliases", "kms:RevokeGrant"}
DDB_REQUIRED = {"dynamodb:CreateTable", "dynamodb:DescribeTable", "dynamodb:DeleteTable", "dynamodb:UpdateTable",
                "dynamodb:DescribeTimeToLive", "dynamodb:UpdateTimeToLive", "dynamodb:ListTagsOfResource", "dynamodb:TagResource", "dynamodb:UntagResource"}
DDB_GETTERS = {"dynamodb:DescribeContinuousBackups", "dynamodb:DescribeContributorInsights", "dynamodb:DescribeKinesisStreamingDestination", "dynamodb:GetResourcePolicy"}
DDB_CONDITIONAL = {
    "dynamodb:UpdateContinuousBackups": "PointInTimeRecoverySpecification is absent.",
    "dynamodb:UpdateContributorInsights": "ContributorInsightsSpecification is absent.",
    **{a: "KinesisStreamSpecification is absent; no Kinesis streaming destination is configured." for a in
       ("dynamodb:EnableKinesisStreamingDestination", "dynamodb:DisableKinesisStreamingDestination", "dynamodb:UpdateKinesisStreamingDestination", "kinesis:DescribeStream", "kinesis:PutRecords")},
    **{a: "ImportSourceSpecification is absent; no S3 import is configured." for a in
       ("dynamodb:ImportTable", "dynamodb:DescribeImport", "s3:GetObject", "s3:GetObjectMetadata", "s3:ListBucket")},
    **{a: "ResourcePolicy is absent; no table resource policy is changed." for a in
       ("dynamodb:PutResourcePolicy", "dynamodb:DeleteResourcePolicy")},
    **{a: "No replicas, imports, streaming integration or vector indexes are configured. The schema does not bind this union permission to a property; CREATE_COMPLETE and DELETE_COMPLETE show it was not required by this exact attempt. Do not grant table data access to the deployer." for a in
       ("dynamodb:CreateTableReplica", "dynamodb:AssociateTableReplica", "dynamodb:Scan", "dynamodb:Query", "dynamodb:UpdateItem", "dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:DeleteItem", "dynamodb:BatchWriteItem", "iam:CreateServiceLinkedRole", "logs:CreateLogGroup", "logs:CreateLogStream", "logs:DescribeLogGroups", "logs:DescribeLogStreams", "logs:PutLogEvents", "logs:PutRetentionPolicy")},
}
LOGS_REQUIRED = {"logs:CreateLogGroup", "logs:DescribeLogGroups", "logs:PutRetentionPolicy", "logs:DeleteRetentionPolicy",
                 "logs:TagResource", "logs:UntagResource", "logs:ListTagsForResource", "logs:DeleteLogGroup"}
LOGS_GETTERS = {"logs:GetDataProtectionPolicy", "logs:DescribeIndexPolicies", "logs:DescribeResourcePolicies"}
LOGS_CONDITIONAL = {
    **{a: "KmsKeyId is absent; no log-group KMS association is configured." for a in ("logs:AssociateKmsKey", "logs:DisassociateKmsKey")},
    **{a: "DataProtectionPolicy is absent; no data-protection policy is changed." for a in ("logs:PutDataProtectionPolicy", "logs:DeleteDataProtectionPolicy")},
    **{a: "FieldIndexPolicies is absent; no field-index policy is changed." for a in ("logs:PutIndexPolicy", "logs:DeleteIndexPolicy")},
    **{a: "ResourcePolicyDocument is absent; no log-group resource policy is changed." for a in ("logs:PutResourcePolicy", "logs:DeleteResourcePolicy")},
    "logs:PutLogGroupDeletionProtection": "DeletionProtectionEnabled is absent; normal rollback deletion is retained.",
    "logs:PutBearerTokenAuthentication": "BearerTokenAuthenticationEnabled is absent.",
    **{a: "No log delivery, S3 destination or Firehose delivery is configured for these basic seven-day Lambda log groups." for a in
       ("logs:CreateLogDelivery", "s3:REST.PUT.OBJECT", "firehose:TagDeliveryStream")},
}


def classify(kind, handler, action):
    """Account for each permission without interpreting an unknown as optional."""
    if handler == "list" and action in {"dynamodb:ListTables", "lambda:ListFunctions"}:
        return "not_used_by_named_stack_deployment", "Account-wide Cloud Control LIST enumeration is outside the exact named stack deployment."
    if kind.startswith("AWS::ApiGatewayV2::"):
        if action.startswith("apigateway:"):
            if action in {"apigateway:TagResource", "apigateway:UntagResource"}:
                return "observed_provider_tagging_blocker", "Literal provider permission label must be reconciled with documented HTTP IAM actions; do not discard it as an unsupported label."
            if kind == "AWS::ApiGatewayV2::Api" and handler in {"create", "delete"}:
                return "preserved_existing_api", "The existing API is modified in place; creation and deletion of the API root must remain denied. CORS rollback deletion is a separate child resource."
            return "required_current", "Required HTTP management lifecycle action for the configured existing API or its staging children."
        if action == "s3:getObject":
            return "conditional_absent", "BodyS3Location is absent; this template has no external OpenAPI body."
        if action == "iam:PassRole":
            return "conditional_absent", "JWT authorizer has no AuthorizerCredentialsArn and Lambda proxy integration has no CredentialsArn; invocation uses exact Lambda resource permissions."
    if kind == "AWS::Lambda::Permission" and action in {"lambda:AddPermission", "lambda:GetPolicy", "lambda:RemovePermission"}:
        return "required_current", "Exact API Gateway Lambda invocation grant create/read/rollback lifecycle."
    if kind == "AWS::Lambda::Function":
        if action in LAMBDA_REQUIRED:
            return "required_current", "Configured ZIP, external runtime role, environment, tags and function create/read/update/delete lifecycle."
        if action in LAMBDA_GETTERS:
            return "read_dependency_unproven", "The feature setter is absent, but the provider READ schema names this getter. Desired properties do not prove a READ handler skips it."
        if action in LAMBDA_CONDITIONAL:
            return "conditional_absent", LAMBDA_CONDITIONAL[action]
    if kind == "AWS::DynamoDB::Table":
        if action in DDB_REQUIRED:
            return "required_current", "Configured on-demand table, TTL, tags and ordinary table lifecycle."
        if action in DDB_GETTERS:
            return "read_dependency_unproven", "The optional feature setter is absent, but the provider READ schema names this metadata getter. CREATE_COMPLETE is not proof of all later refresh/drift reads."
        if action in DDB_CONDITIONAL:
            return "conditional_absent", DDB_CONDITIONAL[action]
    if kind in {"AWS::Lambda::Function", "AWS::DynamoDB::Table"} and action in KMS_SCHEMA_ACTIONS:
        return "kms_separate_verified_review", "Preserve the completed exact-two-key KMS review, service-principal/key-policy distinction and 66 applied-document permission decisions. The exact table and three functions reached CREATE_COMPLETE; no new KMS grant is proposed here."
    if kind == "AWS::Logs::LogGroup":
        if action in LOGS_REQUIRED:
            return "required_current", "Configured basic Lambda log group, seven-day retention, system tags, reads and rollback deletion."
        if action in LOGS_GETTERS:
            return "read_dependency_unproven", "No corresponding setter is configured, but the provider READ schema names this metadata getter. Do not silently classify it as unnecessary."
        if action in LOGS_CONDITIONAL:
            return "conditional_absent", LOGS_CONDITIONAL[action]
    raise ValueError(f"Unclassified schema permission: {kind} {handler} {action}")


def validate_template(template):
    resources = template["Resources"]
    if len(resources) != 41 or {r["Type"] for r in resources.values()} != TYPES:
        raise ValueError("The exact 41-resource / nine-type core is required")
    for name, resource in resources.items():
        kind, props = resource["Type"], resource.get("Properties", {})
        unknown = set(props) - PROPERTIES[kind]
        if unknown:
            raise ValueError(f"New property requires a dependency review: {name}: {sorted(unknown)}")
        if kind == "AWS::Lambda::Function" and set(props.get("Code", {})) != {"S3Bucket", "S3Key"}:
            raise ValueError("Lambda artifact mode changed")
    if resources["HttpApi"]["Properties"].get("DisableExecuteApiEndpoint") is not True:
        raise ValueError("Default endpoint must remain disabled")
    return resources


def audit(template, schemas, events):
    resources = validate_template(template)
    if set(schemas) != TYPES:
        raise ValueError("Exactly the nine complete provider schemas are required")
    rows = []
    for logical, resource in sorted(resources.items()):
        kind = resource["Type"]
        schema = schemas[kind]
        if schema["typeName"] != kind or not schema.get("handlers"):
            raise ValueError("Provider type or handler contract mismatch")
        matches = [e for e in events if e.get("LogicalResourceId") == logical and e.get("ResourceType") == kind]
        classified = []
        for handler, contract in sorted(schema["handlers"].items()):
            for action in contract.get("permissions", []):
                category, basis = classify(kind, handler, action)
                classified.append({"handler": handler, "action": action, "category": category, "basis": basis})
        # Schema tagging permissions can contain dependencies absent from the
        # handler union, so audit them as their own lifecycle as well.
        for action in schema.get("tagging", {}).get("permissions", []):
            category, basis = classify(kind, "tagging", action)
            classified.append({"handler": "tagging", "action": action, "category": category, "basis": basis})
        rows.append({"logical_id": logical, "type": kind, "configured_properties": sorted(resource["Properties"]),
                     "schema_permissions": classified,
                     "created_successfully_this_attempt": any(e["ResourceStatus"] == "CREATE_COMPLETE" for e in matches),
                     "latest_event_status": matches[-1]["ResourceStatus"] if matches else None,
                     "physical_id_at_latest_event": matches[-1].get("PhysicalResourceId") if matches else None})
    counts = Counter(item["category"] for row in rows for item in row["schema_permissions"])
    gaps = sorted({(row["type"], item["action"]) for row in rows for item in row["schema_permissions"]
                   if item["category"] == "read_dependency_unproven"})
    return {"status": "COMPLETE_CLASSIFICATION_WITH_EXPLICIT_VERIFICATION_GAPS", "resource_count": len(rows), "resource_type_count": len(TYPES),
            "permission_classification_counts": dict(counts), "resources": rows,
            "unproven_metadata_getters": [{"type": kind, "action": action} for kind, action in gaps],
            "scope": "Offline schema/property/event analysis only; no AWS reads, authorization proof, permission grants or deployment.",
            "deployment_readiness": False,
            "limitations": ["A schema permission list does not show provider control flow. Absent setter properties cannot establish that all metadata getters are skipped.",
                            "CREATE_COMPLETE and DELETE_COMPLETE prove this exact attempt's creation and cleanup, not all future updates, drift detection or feature additions.",
                            "This analysis deliberately preserves the prior completed KMS review instead of re-investigating keys or granting the schema's KMS union."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, default=ROOT / ".staging/delegated-access-final-review/core-delegated.json")
    parser.add_argument("--schemas", type=Path, default=ROOT / ".staging/core-forward-deployment-review/provider-schemas")
    parser.add_argument("--events", type=Path, default=ROOT / ".staging/kms-repair-review/core-execution-20261027-ab0e6f6c/monitor-latest.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    schema_docs = [json.loads(p.read_text()) for p in args.schemas.glob("aws-*.json")]
    schemas = {doc["typeName"]: doc for doc in schema_docs if doc["typeName"] in TYPES}
    report = audit(json.loads(args.template.read_text()), schemas, json.loads(args.events.read_text())["events"])
    report["input_sha256"] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (args.template, args.events)}
    report["schema_source"] = "https://schema.cloudformation.us-east-2.amazonaws.com/CloudformationSchema.zip"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("status", "resource_count", "resource_type_count", "permission_classification_counts", "unproven_metadata_getters")}, indent=2))


if __name__ == "__main__":
    main()
