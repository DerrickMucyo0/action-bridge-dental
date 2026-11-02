"""Independent configuration and dependency checks on the public staging output.

These checks validate service constraints and runtime prerequisites rather than
rebuilding the template or accepting its resource count as proof of correctness.
No private parameters, credentials, application data, or AWS APIs are accessed.
"""
from fnmatch import fnmatchcase
import json
from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
STAGING = ROOT / "infra/staging"
PSEUDO_PARAMETERS = {
    "AWS::AccountId", "AWS::NotificationARNs", "AWS::NoValue", "AWS::Partition",
    "AWS::Region", "AWS::StackId", "AWS::StackName", "AWS::URLSuffix",
}


def references(node, resources, parameters, local_names=frozenset()):
    """Validate intrinsic names and return the resources needed by this value."""
    found = set()
    if isinstance(node, list):
        for item in node:
            found |= references(item, resources, parameters, local_names)
        return found
    if not isinstance(node, dict):
        return found
    if "Ref" in node:
        name = node["Ref"]
        if name in resources:
            found.add(name)
        elif name not in parameters and name not in PSEUDO_PARAMETERS:
            raise AssertionError("Dangling Ref: " + str(name))
    if "Fn::GetAtt" in node:
        value = node["Fn::GetAtt"]
        name = value.split(".", 1)[0] if isinstance(value, str) else value[0]
        if name not in resources:
            raise AssertionError("Dangling GetAtt: " + str(name))
        found.add(name)
    if "Fn::Sub" in node:
        value = node["Fn::Sub"]
        expression, variables = (value, {}) if isinstance(value, str) else value
        if not isinstance(expression, str) or not isinstance(variables, dict):
            raise AssertionError("Unexpected Fn::Sub structure")
        for token in re.findall(r"\$\{([^}]+)\}", expression):
            if token.startswith("!") or token in variables or token in local_names:
                continue
            name = token.split(".", 1)[0]
            if name in resources:
                found.add(name)
            elif name not in parameters and name not in PSEUDO_PARAMETERS:
                raise AssertionError("Dangling Fn::Sub variable: " + token)
        found |= references(variables, resources, parameters, frozenset(variables))
    for key, value in node.items():
        if key not in ("Ref", "Fn::GetAtt", "Fn::Sub"):
            found |= references(value, resources, parameters, local_names)
    return found


def dependency_graph(template):
    resources = template["Resources"]
    parameters = template.get("Parameters", {})
    graph = {}
    for name, resource in resources.items():
        dependencies = resource.get("DependsOn", [])
        dependencies = [dependencies] if isinstance(dependencies, str) else dependencies
        if any(item not in resources for item in dependencies):
            raise AssertionError("Dangling DependsOn for " + name)
        graph[name] = references(resource, resources, parameters) | set(dependencies)
    references(template.get("Outputs", {}), resources, parameters)
    return graph


def reaches(graph, source, target):
    pending, visited = list(graph[source]), set()
    while pending:
        name = pending.pop()
        if name == target:
            return True
        if name not in visited:
            visited.add(name)
            pending.extend(graph[name])
    return False


def strings(node):
    if isinstance(node, str):
        return [node]
    if isinstance(node, list):
        return [text for item in node for text in strings(item)]
    if isinstance(node, dict):
        return [text for item in node.values() for text in strings(item)]
    return []


def unconditionally_denies_action(document, action):
    """Recognize a global unconditional deny without depending on statement IDs."""
    for statement in document["Statement"]:
        if statement["Effect"] != "Deny" or statement.get("Resource") != "*" or statement.get("Condition"):
            continue
        if "Action" in statement:
            patterns = statement["Action"]
            patterns = [patterns] if isinstance(patterns, str) else patterns
            if any(fnmatchcase(action.lower(), item.lower()) for item in patterns):
                return True
        if "NotAction" in statement:
            patterns = statement["NotAction"]
            patterns = [patterns] if isinstance(patterns, str) else patterns
            if not any(fnmatchcase(action.lower(), item.lower()) for item in patterns):
                return True
    return False


class StagingConfigurationReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = yaml.safe_load((STAGING / "generated/backend.yaml").read_text())
        cls.resources = cls.template["Resources"]
        cls.parameters = cls.template.get("Parameters", {})
        cls.graph = dependency_graph(cls.template)
        cls.manifest = json.loads((STAGING / "resources.json").read_text())

    def of_type(self, resource_type):
        return {name: item for name, item in self.resources.items() if item["Type"] == resource_type}

    def test_all_intrinsic_and_dependency_targets_exist_and_graph_is_acyclic(self):
        # Check the entire public template, including parameter-preserving
        # Metadata, so missing refs cannot hide outside resource Properties.
        references(self.template, self.resources, self.parameters)
        active, complete = [], set()

        def visit(name):
            if name in active:
                self.fail("CloudFormation dependency cycle: " + " -> ".join(active + [name]))
            if name in complete:
                return
            active.append(name)
            for dependency in sorted(self.graph[name]):
                visit(dependency)
            active.pop()
            complete.add(name)

        for name in sorted(self.resources):
            visit(name)

    def test_api_uses_explicit_http_resources_and_keeps_existing_identity_disabled(self):
        api = self.resources["HttpApi"]
        self.assertEqual(api["Type"], "AWS::ApiGatewayV2::Api")
        props = api["Properties"]
        self.assertEqual(props["Name"], self.manifest["api"]["name"])
        self.assertEqual(props["ProtocolType"], "HTTP")
        self.assertIs(props["DisableExecuteApiEndpoint"], True)
        # OpenAPI import cannot be mixed with explicit children. Quick-create
        # would introduce implicit routes/stages outside this reviewed inventory.
        for forbidden in (
            "Body", "BodyS3Location", "Target", "RouteKey", "CredentialsArn",
            "ApiKeySelectionExpression", "DisableSchemaValidation",
        ):
            self.assertNotIn(forbidden, props)
        self.assertEqual(len(self.resources), 69)
        self.assertEqual(len(self.of_type("AWS::ApiGatewayV2::Route")), 21)
        self.assertEqual(len(self.of_type("AWS::ApiGatewayV2::Integration")), 4)
        self.assertEqual(len(self.of_type("AWS::ApiGatewayV2::Authorizer")), 1)
        self.assertFalse(any(item["Type"].startswith(("AWS::Cognito::", "AWS::Serverless::")) for item in self.resources.values()))
        bootstrap = yaml.safe_load((STAGING / "generated/bootstrap.yaml").read_text())
        before = bootstrap["Resources"]["HttpApi"]
        self.assertEqual(before["Type"], api["Type"])
        for key in ("Name", "ProtocolType", "DisableExecuteApiEndpoint"):
            self.assertEqual(before["Properties"][key], props[key])

    def test_routes_have_http_valid_properties_and_only_health_is_public(self):
        routes = self.of_type("AWS::ApiGatewayV2::Route")
        authorizer_id = next(iter(self.of_type("AWS::ApiGatewayV2::Authorizer")))
        public = []
        route_keys = []
        for name, item in routes.items():
            props = item["Properties"]
            self.assertEqual(props["ApiId"], {"Ref": "HttpApi"})
            for websocket_only in (
                "ApiKeyRequired", "ModelSelectionExpression", "RequestModels",
                "RequestParameters", "RouteResponseSelectionExpression",
            ):
                self.assertNotIn(websocket_only, props, name)
            key = props["RouteKey"]
            self.assertRegex(key, r"^(GET|POST|PATCH) /(?:health|v1/[^ ]+)$")
            route_keys.append(key)
            if props["AuthorizationType"] == "NONE":
                public.append(key)
                self.assertNotIn("AuthorizerId", props)
            else:
                self.assertEqual(props["AuthorizationType"], "JWT", name)
                self.assertEqual(props["AuthorizerId"], {"Ref": authorizer_id}, name)
            targets = references(props["Target"], self.resources, self.parameters)
            self.assertEqual(len(targets), 1, name)
            target = next(iter(targets))
            self.assertEqual(self.resources[target]["Type"], "AWS::ApiGatewayV2::Integration", name)
            self.assertTrue(any("integrations" in value for value in strings(props["Target"])), name)
        self.assertEqual(public, ["GET /health"])
        self.assertEqual(len(set(route_keys)), 21)

    def test_jwt_uses_existing_identity_and_lambda_integrations_preserve_payload_v2(self):
        authorizer = next(iter(self.of_type("AWS::ApiGatewayV2::Authorizer").values()))["Properties"]
        self.assertEqual(authorizer["ApiId"], {"Ref": "HttpApi"})
        self.assertEqual(authorizer["AuthorizerType"], "JWT")
        self.assertEqual(authorizer["IdentitySource"], ["$request.header.Authorization"])
        self.assertEqual(authorizer["JwtConfiguration"], {
            "Audience": [{"Ref": "ExistingUserPoolClientId"}],
            "Issuer": {"Fn::Sub": "https://cognito-idp.${AWS::Region}.amazonaws.com/${ExistingUserPoolId}"},
        })
        for lambda_only in ("AuthorizerUri", "AuthorizerCredentialsArn", "AuthorizerResultTtlInSeconds", "AuthorizerPayloadFormatVersion", "EnableSimpleResponses"):
            self.assertNotIn(lambda_only, authorizer)
        integrated_functions = set()
        for name, item in self.of_type("AWS::ApiGatewayV2::Integration").items():
            props = item["Properties"]
            self.assertEqual(props["ApiId"], {"Ref": "HttpApi"})
            self.assertEqual(props["IntegrationType"], "AWS_PROXY")
            self.assertEqual(props["IntegrationMethod"], "POST")
            self.assertEqual(props["PayloadFormatVersion"], "2.0")
            self.assertNotIn("CredentialsArn", props)
            for websocket_only in ("ContentHandlingStrategy", "PassthroughBehavior", "RequestTemplates", "TemplateSelectionExpression"):
                self.assertNotIn(websocket_only, props, name)
            targets = references(props["IntegrationUri"], self.resources, self.parameters)
            self.assertEqual(len(targets), 1, name)
            function = next(iter(targets))
            self.assertEqual(self.resources[function]["Type"], "AWS::Lambda::Function")
            integrated_functions.add(function)
        self.assertEqual(integrated_functions, {"HealthFunction", "CasesFunction", "CalculationsFunction", "JobsFunction"})

    def test_stage_and_cors_are_bounded_without_deployment_or_wildcard_conflicts(self):
        stages = self.of_type("AWS::ApiGatewayV2::Stage")
        self.assertEqual(set(stages), {"HttpApiStage"})
        stage = stages["HttpApiStage"]["Properties"]
        self.assertEqual(stage["ApiId"], {"Ref": "HttpApi"})
        self.assertEqual(stage["StageName"], {"Ref": "AppEnv"})
        self.assertIs(stage["AutoDeploy"], True)
        self.assertNotIn("DeploymentId", stage)
        self.assertEqual(stage["DefaultRouteSettings"]["ThrottlingBurstLimit"], 20)
        self.assertEqual(stage["DefaultRouteSettings"]["ThrottlingRateLimit"], 10)
        for websocket_only in ("DataTraceEnabled", "LoggingLevel"):
            self.assertNotIn(websocket_only, stage["DefaultRouteSettings"])
        cors = self.resources["HttpApi"]["Properties"]["CorsConfiguration"]
        self.assertEqual(cors["AllowOrigins"], {"Ref": "StagingWebOrigins"})
        self.assertEqual(set(cors["AllowMethods"]), {"GET", "POST", "PATCH", "OPTIONS"})
        self.assertEqual(set(cors["AllowHeaders"]), {"authorization", "content-type", "idempotency-key"})
        self.assertEqual(cors["ExposeHeaders"], ["x-request-id"])
        self.assertEqual(cors["MaxAge"], 600)

    def test_runtime_roles_keep_paired_boundaries_and_log_groups_are_precreated(self):
        functions = self.of_type("AWS::Lambda::Function")
        logs = self.of_type("AWS::Logs::LogGroup")
        self.assertEqual(len(functions), 5)
        self.assertEqual(len(logs), 5)
        for name, function in functions.items():
            spec = self.manifest["functions"][name]
            props = function["Properties"]
            self.assertEqual(props["Runtime"], "nodejs22.x")
            self.assertEqual(props["Architectures"], ["arm64"])
            self.assertEqual(props["Role"], {"Fn::GetAtt": [name + "Role", "Arn"]})
            role = self.resources[name + "Role"]["Properties"]
            self.assertEqual(role["RoleName"], spec["role_name"])
            self.assertEqual(role["Path"], self.manifest["role_path"])
            self.assertEqual(role["PermissionsBoundary"], f"arn:aws:iam::{self.manifest['account']}:policy/{spec['boundary_policy_name']}")
            self.assertEqual(role["AssumeRolePolicyDocument"]["Statement"], [{
                "Action": ["sts:AssumeRole"], "Effect": "Allow", "Principal": {"Service": ["lambda.amazonaws.com"]},
            }])
            boundary = json.loads((STAGING / "generated" / (spec["boundary_policy_name"] + ".json")).read_text())
            self.assertTrue(unconditionally_denies_action(boundary, "logs:CreateLogGroup"), name)
            corresponding_logs = [key for key in logs if name in self.graph[key]]
            self.assertEqual(len(corresponding_logs), 1, name)
            self.assertEqual(logs[corresponding_logs[0]]["Properties"]["RetentionInDays"], 7)
        # A function reference alone does not order its group before the poller.
        # The mapping can invoke immediately, including while the HTTP API is disabled.
        self.assertTrue(reaches(self.graph, "JobWorkerFunctionJobs", "JobWorkerLogGroup"))

    def test_worker_queue_constraints_and_bounded_concurrency_are_compatible(self):
        worker = self.resources["JobWorkerFunction"]["Properties"]
        queue = self.resources["JobQueue"]["Properties"]
        dead_letter = self.resources["JobDeadLetterQueue"]["Properties"]
        mapping = self.resources["JobWorkerFunctionJobs"]["Properties"]
        # AWS validates this minimum. Six times the timeout is separate retry
        # guidance; it must not be confused with the provider acceptance rule.
        self.assertGreaterEqual(queue["VisibilityTimeout"], worker["Timeout"])
        self.assertEqual(mapping["FunctionName"], {"Ref": "JobWorkerFunction"})
        self.assertEqual(mapping["EventSourceArn"], {"Fn::GetAtt": ["JobQueue", "Arn"]})
        self.assertEqual(mapping["BatchSize"], 1)
        self.assertEqual(mapping["FunctionResponseTypes"], ["ReportBatchItemFailures"])
        self.assertEqual(mapping["ScalingConfig"], {"MaximumConcurrency": 2})
        self.assertNotIn("ProvisionedPollerConfig", mapping)
        if "ReservedConcurrentExecutions" in worker:
            self.assertGreaterEqual(worker["ReservedConcurrentExecutions"], 2)
        self.assertEqual(queue["RedrivePolicy"], {
            "deadLetterTargetArn": {"Fn::GetAtt": ["JobDeadLetterQueue", "Arn"]}, "maxReceiveCount": 2,
        })
        self.assertGreater(dead_letter["MessageRetentionPeriod"], queue["MessageRetentionPeriod"])
        for properties in (queue, dead_letter):
            self.assertIs(properties["SqsManagedSseEnabled"], True)
            self.assertNotIn("KmsMasterKeyId", properties)

    def test_storage_configuration_needs_no_ungranted_customer_kms_permissions(self):
        table = self.resources["CasesTable"]["Properties"]
        self.assertEqual(table["BillingMode"], "PAY_PER_REQUEST")
        self.assertEqual(table["TimeToLiveSpecification"], {"AttributeName": "expiresAt", "Enabled": True})
        self.assertEqual(table["SSESpecification"], {"SSEEnabled": True})
        upload = self.resources["UploadBucket"]["Properties"]
        self.assertEqual(upload["OwnershipControls"], {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]})
        self.assertTrue(all(upload["PublicAccessBlockConfiguration"].values()))
        self.assertEqual(set(upload["PublicAccessBlockConfiguration"]), {
            "BlockPublicAcls", "BlockPublicPolicy", "IgnorePublicAcls", "RestrictPublicBuckets",
        })
        self.assertEqual(upload["BucketEncryption"]["ServerSideEncryptionConfiguration"], [{
            "ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"},
        }])
        self.assertEqual(upload["CorsConfiguration"]["CorsRules"][0]["AllowedOrigins"], {"Ref": "StagingWebOrigins"})
        self.assertTrue(any(rule.get("Status") == "Enabled" and rule.get("Prefix") == "uploads/"
                            and rule.get("ExpirationInDays") == 1
                            for rule in upload["LifecycleConfiguration"]["Rules"]))


if __name__ == "__main__":
    unittest.main()
