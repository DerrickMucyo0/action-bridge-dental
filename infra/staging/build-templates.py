#!/usr/bin/env python3
"""Build public staging templates offline. Never reads private parameters or calls AWS.

The source SAM template remains the application source of truth. This compiler
fixes the staging resource selectors and expands SAM locally. The existing API
keeps its ProtocolType and disabled endpoint; routes use explicit CloudFormation
resources rather than an incompatible OpenAPI import into that API.
"""

import argparse
import copy
import json
from pathlib import Path
import re
import socket
from unittest.mock import patch

import boto3
from samtranslator.metrics.metrics import Metrics
from samtranslator.parser.parser import Parser
from samtranslator.translator.translator import Translator
import yaml


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GENERATED = HERE / "generated"
FUNCTION_SLUGS = {
    "HealthFunction": "health",
    "CasesFunction": "cases",
    "CalculationsFunction": "calculations",
    "JobsFunction": "jobs",
    "JobWorkerFunction": "job-worker",
}
CORE_FUNCTIONS = ("HealthFunction", "CasesFunction", "CalculationsFunction")
ARTIFACT_PARAMETERS = {
    "HealthFunction": "HealthArtifactKey",
    "CasesFunction": "CasesArtifactKey",
    "CalculationsFunction": "CalculationsArtifactKey",
    "JobsFunction": "JobsArtifactKey",
    "JobWorkerFunction": "JobWorkerArtifactKey",
}
EXPECTED_SOURCE_TYPES = {
    "CasesTable": "AWS::DynamoDB::Table",
    "UserPool": "AWS::Cognito::UserPool",
    "UserPoolClient": "AWS::Cognito::UserPoolClient",
    "UserPoolDomain": "AWS::Cognito::UserPoolDomain",
    "HttpApi": "AWS::Serverless::HttpApi",
    **{name: "AWS::Serverless::Function" for name in FUNCTION_SLUGS},
    "UploadBucket": "AWS::S3::Bucket",
    "JobDeadLetterQueue": "AWS::SQS::Queue",
    "JobQueue": "AWS::SQS::Queue",
    **{name: "AWS::Logs::LogGroup" for name in (
        "JobsLogGroup", "JobWorkerLogGroup", "HealthLogGroup", "CasesLogGroup",
        "CalculationsLogGroup",
    )},
}


class CloudFormationLoader(yaml.SafeLoader):
    pass


class PublicDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def tagged(loader, tag, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node)
    else:
        value = loader.construct_mapping(node)
    if tag == "GetAtt" and isinstance(value, str):
        value = value.split(".", 1)
    return {tag if tag in ("Ref", "Condition") else "Fn::" + tag: value}


CloudFormationLoader.add_multi_constructor("!", tagged)


def manifest():
    data = json.loads((HERE / "resources.json").read_text())
    if (data["account"], data["region"], data["stack_name"]) != (
        "631367363628", "us-east-2", "actionbridge-dental-staging"
    ):
        raise ValueError("This compiler is restricted to the reviewed staging target.")
    if set(data["functions"]) != set(FUNCTION_SLUGS):
        raise ValueError("The manifest must describe the five reviewed functions.")
    return data


def source_template():
    source = yaml.load((ROOT / "infra/template.yaml").read_text(), Loader=CloudFormationLoader)
    if {name: item["Type"] for name, item in source["Resources"].items()} != EXPECTED_SOURCE_TYPES:
        raise ValueError("Source resource inventory changed; review the staging compiler before regenerating.")
    if source["Transform"] != "AWS::Serverless-2016-10-31":
        raise ValueError("Only the reviewed AWS SAM transform is supported.")
    return source


def select_staging(node):
    """Select only the already fixed IsStaging branches, preserving parameter Refs."""
    if isinstance(node, list):
        return [select_staging(item) for item in node]
    if not isinstance(node, dict):
        return node
    if "Fn::If" in node:
        condition, yes, _ = node["Fn::If"]
        if condition != "IsStaging":
            raise ValueError("Unexpected source condition after external-identity selection.")
        return select_staging(yes)
    return {key: select_staging(value) for key, value in node.items()}


def reviewed_jwt(auth):
    """Reject source authentication settings that explicit resources cannot retain."""
    if (set(auth) != {"Authorizers", "DefaultAuthorizer"}
            or set(auth["Authorizers"]) != {"CognitoJwt"}):
        raise ValueError("Unreviewed source authentication configuration; explicit API translation must be extended.")
    jwt = auth["Authorizers"]["CognitoJwt"]
    if (set(jwt) != {"IdentitySource", "JwtConfiguration"}
            or set(jwt["JwtConfiguration"]) != {"audience", "issuer"}):
        raise ValueError("Unreviewed source authentication configuration; explicit API translation must be extended.")
    return jwt


def staging_source(data, source):
    source = copy.deepcopy(source)
    source["Description"] = (
        "ActionBridge Dental staging backend UPDATE after the reviewed empty-API bootstrap. "
        "Public generated template; requires CAPABILITY_NAMED_IAM. Synthetic data only."
    )
    source["Metadata"] = {
        "StagingTarget": {"Account": data["account"], "Region": data["region"], "StackName": data["stack_name"]},
        "DeploymentPhase": "backend-update-after-bootstrap",
        "TargetCheck": "The owner must verify caller account, Region, stack and bootstrap API ID before cloud operations; metadata is not an IAM restriction.",
        "LegacyParametersIgnored": {
            "Explanation": "Accepted for compatibility only; identity is external and each role uses its fixed administrator-owned boundary.",
            **{name: {"Ref": name} for name in (
                "StagingRuntimePermissionsBoundaryArn", "EnableSelfRegistration", "AuthCallbackUrls", "WebOrigins"
            )},
        },
    }
    parameters = source["Parameters"]
    parameters["AppEnv"].update(Default="staging", AllowedValues=["staging"], Description="Fixed staging environment in this generated template.")
    parameters["ExistingUserPoolId"]["Description"] = "Required approved existing Cognito pool; no identity resources are created, changed or deleted by this stack."
    parameters["ExistingUserPoolClientId"]["Description"] = "Required existing public client belonging to ExistingUserPoolId; verify account ownership, no secret and required authentication flows separately."
    parameters["StagingRuntimePermissionsBoundaryArn"]["Description"] = (
        "Legacy compatibility parameter, ignored by this generated staging template. "
        "Each role uses its own fixed administrator-owned boundary ARN."
    )
    for name in ("EnableSelfRegistration", "AuthCallbackUrls", "WebOrigins"):
        parameters[name]["Description"] = "Legacy compatibility parameter, ignored by this generated staging template. External identity and StagingWebOrigins are authoritative."
    for name in ("BedrockModelId", "BedrockFoundationModel"):
        parameters[name]["AllowedValues"] = [parameters[name]["Default"]]
    source["Rules"].pop("StagingRequiresRuntimePermissionsBoundary")
    source["Rules"]["StagingRequiresExternalIdentity"] = {
        "Assertions": [
            {"Assert": {"Fn::Not": [{"Fn::Equals": [{"Ref": name}, ""]}]},
             "AssertDescription": name + " must identify the approved existing external identity."}
            for name in ("ExistingUserPoolId", "ExistingUserPoolClientId")
        ]
    }
    # Removing managed resources rather than importing them keeps existing users
    # outside both deployment phases, including failed updates and rollback.
    for name in ("UserPool", "UserPoolClient", "UserPoolDomain"):
        del source["Resources"][name]
    for name in ("UseManagedCognito", "PublicRegistrationEnabled", "HasStagingRuntimePermissionsBoundary"):
        source["Conditions"].pop(name)
    source["Globals"]["Function"].pop("PermissionsBoundary")
    source["Globals"]["Function"]["RolePath"] = data["role_path"]
    resources = source["Resources"]
    resources["CasesTable"]["Properties"]["TableName"] = data["table"]["name"]
    resources["UploadBucket"]["Properties"]["BucketName"] = data["buckets"]["uploads"]
    resources["JobQueue"]["Properties"]["QueueName"] = data["queues"]["work"]
    resources["JobDeadLetterQueue"]["Properties"]["QueueName"] = data["queues"]["dead_letter"]
    api = resources["HttpApi"]["Properties"]
    api["Name"] = data["api"]["name"]
    # Enabling the endpoint requires a separate security review and approval.
    api["DisableExecuteApiEndpoint"] = True
    jwt = reviewed_jwt(api["Auth"])["JwtConfiguration"]
    jwt["issuer"] = {"Fn::Sub": "https://cognito-idp.${AWS::Region}.amazonaws.com/${ExistingUserPoolId}"}
    jwt["audience"] = [{"Ref": "ExistingUserPoolClientId"}]
    for name, slug in FUNCTION_SLUGS.items():
        function = resources[name]["Properties"]
        entry = data["functions"][name]
        function["FunctionName"] = entry["name"]
        function["PermissionsBoundary"] = f"arn:aws:iam::{data['account']}:policy/{entry['boundary_policy_name']}"
        artifact_parameter = ARTIFACT_PARAMETERS[name]
        parameters[artifact_parameter] = {
            "Type": "String",
            "AllowedPattern": "^" + data["artifact_prefix"].rstrip("/") + "/" + slug + "/[a-f0-9]{64}[.]zip$",
            "Description": "Required immutable packaged artifact key for " + name + "; generated locally from the ZIP SHA-256. No default artifact exists.",
        }
        function["CodeUri"] = {
            "Bucket": data["buckets"]["artifacts"], "Key": {"Ref": artifact_parameter}
        }
    outputs = source["Outputs"]
    outputs.pop("ManagedLoginDomain")
    outputs["UserPoolId"]["Value"] = {"Ref": "ExistingUserPoolId"}
    outputs["UserPoolId"]["Description"] = "Existing Cognito pool outside this stack's lifecycle."
    outputs["UserPoolClientId"]["Value"] = {"Ref": "ExistingUserPoolClientId"}
    outputs["CognitoIssuer"]["Value"] = {"Fn::Sub": "https://cognito-idp.${AWS::Region}.amazonaws.com/${ExistingUserPoolId}"}
    outputs["HttpApiId"] = {"Description": "Must match the reviewed bootstrap API ID.", "Value": {"Ref": "HttpApi"}}
    # AppEnv is constrained to staging, so no unreachable dev/demo branches need
    # to enter the public deployable artifact or trigger pinned-linter warnings.
    source = select_staging(source)
    del source["Conditions"]
    return source


def bootstrap_template(data):
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "ActionBridge Dental staging bootstrap CREATE: one empty HTTP API, endpoint disabled, no routes or identity resources.",
        "Metadata": {
            "StagingTarget": {"Account": data["account"], "Region": data["region"], "StackName": data["stack_name"]},
            "DeploymentPhase": "empty-api-bootstrap-create",
            "TargetCheck": "The owner must verify caller account, Region and new stack name before cloud operations; metadata is not an IAM restriction.",
        },
        "Resources": {
            "HttpApi": {
                "Type": "AWS::ApiGatewayV2::Api",
                "Properties": {"Name": data["api"]["name"], "ProtocolType": "HTTP", "DisableExecuteApiEndpoint": True},
            },
        },
        "Outputs": {"HttpApiId": {"Description": "Record this exact physical ID before reviewing any backend UPDATE.", "Value": {"Ref": "HttpApi"}}},
    }


def explicit_http_api(result, source, data, cors, translation_values):
    """Preserve the bootstrap API and translate only our reviewed SAM HTTP shape.

    API Gateway supports OpenAPI import OR explicit child resources, not both.
    Importing Body alongside ProtocolType/Name/DisableExecuteApiEndpoint failed
    in AWS; dropping ProtocolType would risk replacing the existing API. Keep
    the API's bootstrap properties and materialize its children instead. Verify
    semantic parity with SAM's output, failing closed on unhandled new features.
    """
    resources = result["Resources"]
    api = resources["HttpApi"]
    if api["Type"] != "AWS::ApiGatewayV2::Api":
        raise ValueError("SAM's API resource shape changed; review the bootstrap transition.")
    if set(api["Properties"]) != {"Body"}:
        raise ValueError("Unreviewed translated API properties; explicit API translation must be extended.")
    body = api["Properties"]["Body"]
    if set(body) != {"components", "info", "openapi", "paths", "servers", "tags", "x-amazon-apigateway-cors"}:
        raise ValueError("Unreviewed OpenAPI features; explicit API translation must be extended.")
    auth = body["components"]["securitySchemes"]
    expected_auth = source["Resources"]["HttpApi"]["Properties"]["Auth"]
    # SAM accepts arbitrary nested dictionaries here. Comparing its emitted
    # authorizer with the same source dictionary would accept new JWT fields,
    # then discard them when selecting only Audience/Issuer below. Review each
    # new source setting before compiling it into explicit API resources.
    jwt = reviewed_jwt(expected_auth)
    if auth != {"CognitoJwt": {
        "type": "oauth2", "x-amazon-apigateway-authorizer": {
            "identitySource": jwt["IdentitySource"], "jwtConfiguration": jwt["JwtConfiguration"], "type": "jwt",
        },
    }} or expected_auth["DefaultAuthorizer"] != "CognitoJwt":
        raise ValueError("Unreviewed authorizer; explicit API translation must be extended.")

    def resolved_for_translation(node):
        if isinstance(node, list):
            return [resolved_for_translation(value) for value in node]
        if isinstance(node, dict):
            if set(node) == {"Ref"} and node["Ref"] in translation_values:
                return translation_values[node["Ref"]]
            return {key: resolved_for_translation(value) for key, value in node.items()}
        return node

    expected_metadata = {
        "components": {"securitySchemes": auth},
        "info": {"title": data["api"]["name"], "version": "1.0"},
        "openapi": "3.0.1",
        "servers": [{"x-amazon-apigateway-endpoint-configuration": {"disableExecuteApiEndpoint": True}}],
        "tags": [{"name": "httpapi:createdBy", "x-amazon-apigateway-tag-value": "SAM"}],
        "x-amazon-apigateway-cors": {
            key[0].lower() + key[1:]: resolved_for_translation(value) for key, value in cors.items()
        },
    }
    if {key: value for key, value in body.items() if key != "paths"} != expected_metadata:
        raise ValueError("Unreviewed nested OpenAPI configuration; explicit API translation must be extended.")
    resources["HttpApiCognitoJwtAuthorizer"] = {
        "Type": "AWS::ApiGatewayV2::Authorizer",
        "Properties": {
            "ApiId": {"Ref": "HttpApi"}, "AuthorizerType": "JWT", "Name": "CognitoJwt",
            "IdentitySource": [jwt["IdentitySource"]],
            "JwtConfiguration": {"Audience": jwt["JwtConfiguration"]["audience"], "Issuer": jwt["JwtConfiguration"]["issuer"]},
        },
    }
    expected_paths = {}
    route_ids = []
    for name in FUNCTION_SLUGS:
        events = source["Resources"][name]["Properties"].get("Events", {})
        for event_name, event in events.items():
            if event["Type"] != "HttpApi":
                continue
            props = event["Properties"]
            method, path = props["Method"].lower(), props["Path"]
            public = (method, path) == ("get", "/health")
            if set(props) != ({"ApiId", "Method", "Path", "Auth"} if public else {"ApiId", "Method", "Path"}):
                raise ValueError("Unreviewed HTTP event properties; explicit API translation must be extended.")
            if props["ApiId"] != {"Ref": "HttpApi"} or (public and props["Auth"] != {"Authorizer": "NONE"}):
                raise ValueError("Unexpected API or health authentication configuration.")
            uri = {"Fn::Sub": "arn:${AWS::Partition}:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${" + name + ".Arn}/invocations"}
            integration = {"httpMethod": "POST", "payloadFormatVersion": "2.0", "type": "aws_proxy", "uri": uri}
            operation = {"responses": {}, "security": [{"NONE" if public else "CognitoJwt": []}], "x-amazon-apigateway-integration": integration}
            path_parameters = re.findall(r"\{([^}]+)\}", path)
            if path_parameters:
                operation["parameters"] = [{"in": "path", "name": key, "required": True} for key in path_parameters]
            if method in expected_paths.setdefault(path, {}):
                raise ValueError("Duplicate HTTP route.")
            expected_paths[path][method] = operation
            integration_id = "HttpApi" + name + "Integration"
            resources[integration_id] = {
                "Type": "AWS::ApiGatewayV2::Integration",
                "Properties": {"ApiId": {"Ref": "HttpApi"}, "IntegrationType": "AWS_PROXY",
                               "IntegrationMethod": "POST", "IntegrationUri": uri, "PayloadFormatVersion": "2.0"},
            }
            route_id = "HttpApi" + name + event_name + "Route"
            route_ids.append(route_id)
            route = {"ApiId": {"Ref": "HttpApi"}, "RouteKey": method.upper() + " " + path,
                     "AuthorizationType": "NONE" if public else "JWT",
                     "Target": {"Fn::Join": ["/", ["integrations", {"Ref": integration_id}]]}}
            if not public:
                route["AuthorizerId"] = {"Ref": "HttpApiCognitoJwtAuthorizer"}
            resources[route_id] = {"Type": "AWS::ApiGatewayV2::Route", "Properties": route}
    if body["paths"] != expected_paths:
        raise ValueError("SAM route/auth/integration semantics changed; explicit API translation must be extended.")
    # No Body/BodyS3Location or quick-create Target/RouteKey remains on the API.
    api["Properties"] = {"Name": data["api"]["name"], "ProtocolType": "HTTP",
                         "DisableExecuteApiEndpoint": True, "CorsConfiguration": cors}
    resources["HttpApiStage"]["DependsOn"] = sorted(route_ids)


def backend_template(data, source):
    source = staging_source(data, source)
    declared_cors = copy.deepcopy(source["Resources"]["HttpApi"]["Properties"]["CorsConfiguration"])
    # Dummy parameter values are used only by the local translator's resolver.
    # The generated template must preserve Refs; it contains no deploy-time values.
    values = {
        name: (str(spec["Default"]).split(",") if spec["Type"] == "CommaDelimitedList" else spec.get("Default", ""))
        for name, spec in source["Parameters"].items()
    }
    for name, slug in FUNCTION_SLUGS.items():
        values[ARTIFACT_PARAMETERS[name]] = data["artifact_prefix"].rstrip("/") + "/" + slug + "/" + "0" * 64 + ".zip"
    session = boto3.Session(region_name=data["region"], aws_access_key_id="offline", aws_secret_access_key="offline")
    policies = {name: "arn:aws:iam::aws:policy/service-role/" + name for name in (
        "AWSLambdaBasicExecutionRole", "AWSLambdaSQSQueueExecutionRole"
    )}
    metrics = Metrics()
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Network access is prohibited during staging template compilation")):
        result = Translator(policies, Parser(), boto_session=session, metrics=metrics).translate(source, values)
        metrics.publish()
    # The translator uses compatibility mapping/string subclasses internally.
    # Normalize these to plain JSON data before deterministic safe YAML output.
    result = json.loads(json.dumps(result))
    explicit_http_api(result, source, data, declared_cors, values)
    # Runtime boundaries intentionally forbid log-group creation. Ensure the
    # worker's group exists before an enabled SQS trigger can invoke it.
    result["Resources"]["JobWorkerFunctionJobs"]["DependsOn"] = ["JobWorkerLogGroup"]
    for name, entry in data["functions"].items():
        role = result["Resources"][name + "Role"]
        if role["Type"] != "AWS::IAM::Role":
            raise ValueError("SAM's role resource shape changed; review the staging role selectors.")
        role["Properties"]["RoleName"] = entry["role_name"]
    if len(result["Resources"]) != 69 or any(item["Type"].startswith("AWS::Cognito::") for item in result["Resources"].values()):
        raise ValueError("Expanded staging inventory changed; review before regenerating.")
    return result


def referenced_names(node):
    """Find CloudFormation references without resolving deploy-time values."""
    if isinstance(node, list):
        return set().union(*(referenced_names(value) for value in node))
    if not isinstance(node, dict):
        return set()
    names = set()
    if "Ref" in node:
        names.add(node["Ref"])
    if "Fn::GetAtt" in node:
        value = node["Fn::GetAtt"]
        names.add(value.split(".", 1)[0] if isinstance(value, str) else value[0])
    if "Fn::Sub" in node:
        value = node["Fn::Sub"]
        expression, variables = (value, {}) if isinstance(value, str) else value
        names.update(token.split(".", 1)[0] for token in re.findall(r"\$\{([^}]+)\}", expression)
                     if token not in variables and not token.startswith("!"))
        names.update(referenced_names(variables))
    for key, value in node.items():
        if key not in ("Ref", "Fn::GetAtt", "Fn::Sub"):
            names.update(referenced_names(value))
    return names


def core_template(data, source, expanded=None):
    """Deploy the manual case/engine path with no background-job acceptance.

    No jobs route, function, queue, upload bucket, worker or mapping exists in
    this phase. This server-side boundary remains safe even if an older client
    attempts a job request. The three retained Lambda ZIPs/configurations are
    unchanged; the full backend template remains available for a later review.
    """
    result = copy.deepcopy(expanded if expanded is not None else backend_template(data, source))
    resources = result["Resources"]
    deferred = {"JobsFunction", "JobsFunctionRole", "JobsLogGroup",
                "JobWorkerFunction", "JobWorkerFunctionRole", "JobWorkerLogGroup",
                "JobWorkerFunctionJobs", "JobQueue", "JobDeadLetterQueue", "UploadBucket",
                "HttpApiJobsFunctionIntegration"}
    for name, resource in resources.items():
        if resource["Type"] == "AWS::Lambda::Permission" and resource["Properties"]["FunctionName"] == {"Ref": "JobsFunction"}:
            deferred.add(name)
        if resource["Type"] == "AWS::ApiGatewayV2::Route" and "HttpApiJobsFunctionIntegration" in referenced_names(resource):
            deferred.add(name)
    if len(resources) != 69 or len(deferred) != 25 or not deferred <= resources.keys():
        raise ValueError("Core/deferred inventory changed; review the phase boundary.")
    for name in deferred:
        del resources[name]
    resources["HttpApiStage"]["DependsOn"] = [name for name in resources["HttpApiStage"]["DependsOn"] if name not in deferred]
    result["Outputs"].pop("JobDeadLetterQueueUrl")
    result["Outputs"]["BackgroundJobsEnabled"] = {
        "Description": "Set VITE_BACKGROUND_JOBS_ENABLED=false for the core frontend. Background routes/resources are intentionally absent.",
        "Value": "false",
    }
    result["Description"] = "ActionBridge Dental staging core UPDATE: manual cases/calculations only; background jobs and worker deferred; endpoint disabled."
    result["Metadata"]["DeploymentPhase"] = "core-backend-update-worker-deferred"
    result["Metadata"]["BackgroundFeatures"] = {"Enabled": False, "DeferredResourceCount": len(deferred)}
    used = referenced_names({key: value for key, value in result.items() if key != "Parameters"})
    result["Parameters"] = {name: spec for name, spec in result["Parameters"].items() if name in used}
    if referenced_names(resources) & deferred or len(resources) != 44:
        raise ValueError("Core template retains a deferred dependency.")
    for resource in resources.values():
        dependencies = resource.get("DependsOn", [])
        dependencies = [dependencies] if isinstance(dependencies, str) else dependencies
        if set(dependencies) & deferred:
            raise ValueError("Core template retains a deferred dependency.")
    return result


def rendered_templates():
    data = manifest()
    source = source_template()
    backend = backend_template(data, source)
    return {
        "bootstrap.yaml": bootstrap_template(data),
        "backend.yaml": backend,
        "core.yaml": core_template(data, source, expanded=backend),
    }


def rendered_text(template):
    return "# Generated offline by infra/staging/build-templates.py; review before any cloud write.\n" + yaml.dump(template, Dumper=PublicDumper, sort_keys=True, width=110)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare public generated templates without writing")
    options = parser.parse_args()
    failures = []
    for name, template in rendered_templates().items():
        path = GENERATED / name
        text = rendered_text(template)
        if options.check:
            if not path.is_file() or path.read_text() != text:
                failures.append(name)
        else:
            GENERATED.mkdir(exist_ok=True)
            if not path.is_file() or path.read_text() != text:
                path.write_text(text)
    if failures:
        raise SystemExit("Generated templates are stale: " + ", ".join(failures))
    print("Public staging templates " + ("match their sources." if options.check else "generated locally. No AWS calls made."))


if __name__ == "__main__":
    main()
