"""Independent checks for the bounded manual-entry staging deployment.

The core reuses the three existing calculator/case/health artifacts. Background
jobs have no API route or infrastructure capable of accepting work. These tests
read only public local templates; they do not infer live AWS replacement status.
"""
import copy
import importlib.util
from pathlib import Path
import re
import unittest

import yaml

from test_staging_configuration_review import dependency_graph, reaches, references


ROOT = Path(__file__).resolve().parents[2]
STAGING = ROOT / "infra/staging"
SPEC = importlib.util.spec_from_file_location("staging_core_builder", STAGING / "build-templates.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)
CORE_FUNCTIONS = {"HealthFunction", "CasesFunction", "CalculationsFunction"}
BACKGROUND_FUNCTIONS = {"JobsFunction", "JobWorkerFunction"}


def parameter_uses(node, parameters):
    """Find parameters referenced outside their own declarations."""
    found = set()
    if isinstance(node, list):
        for value in node:
            found |= parameter_uses(value, parameters)
    elif isinstance(node, dict):
        if node.get("Ref") in parameters:
            found.add(node["Ref"])
        if "Fn::Sub" in node:
            value = node["Fn::Sub"]
            expression, variables = (value, {}) if isinstance(value, str) else value
            for token in re.findall(r"\$\{([^}]+)\}", expression):
                if token in parameters and token not in variables:
                    found.add(token)
        for value in node.values():
            found |= parameter_uses(value, parameters)
    return found


class StagingCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = builder.manifest()
        cls.core = yaml.safe_load((STAGING / "generated/core.yaml").read_text())
        cls.full = yaml.safe_load((STAGING / "generated/backend.yaml").read_text())
        cls.bootstrap = yaml.safe_load((STAGING / "generated/bootstrap.yaml").read_text())
        cls.resources = cls.core["Resources"]
        cls.graph = dependency_graph(cls.core)

    def of_type(self, resource_type):
        return {name: item for name, item in self.resources.items() if item["Type"] == resource_type}

    def test_generated_core_matches_compiler_without_mutating_application_source(self):
        source = builder.source_template()
        before = copy.deepcopy(source)
        compiled = builder.core_template(self.manifest, source)
        self.assertEqual(source, before)
        self.assertEqual(compiled, self.core)
        self.assertEqual((STAGING / "generated/core.yaml").read_text(), builder.rendered_text(compiled))
        # The full worker-capable follow-up stays a separate, unchanged output.
        self.assertEqual(builder.backend_template(self.manifest, source), self.full)

    def test_no_background_resource_or_route_can_accept_or_poll_work(self):
        self.assertEqual(len(self.resources), 44)
        self.assertEqual(set(self.of_type("AWS::Lambda::Function")), CORE_FUNCTIONS)
        for forbidden in ("AWS::Lambda::EventSourceMapping", "AWS::SQS::Queue", "AWS::S3::Bucket"):
            self.assertFalse(self.of_type(forbidden), forbidden)
        self.assertFalse(any(item["Type"].startswith(("AWS::Cognito::", "AWS::Serverless::")) for item in self.resources.values()))
        for name in BACKGROUND_FUNCTIONS:
            self.assertNotIn(name, self.resources)
            self.assertNotIn(name + "Role", self.resources)
        routes = [item["Properties"]["RouteKey"] for item in self.of_type("AWS::ApiGatewayV2::Route").values()]
        self.assertEqual(len(routes), 14)
        self.assertTrue(all("/jobs" not in key and "/uploads" not in key and key != "POST /v1/speech" for key in routes))
        self.assertEqual(self.core["Outputs"]["BackgroundJobsEnabled"]["Value"], "false")

    def test_core_routes_match_the_retained_application_contract_and_authentication(self):
        source = builder.source_template()["Resources"]
        expected = {}
        for function in CORE_FUNCTIONS:
            for event in source[function]["Properties"]["Events"].values():
                if event["Type"] == "HttpApi":
                    props = event["Properties"]
                    expected[props["Method"] + " " + props["Path"]] = function
        actual, public = {}, []
        integrations = self.of_type("AWS::ApiGatewayV2::Integration")
        self.assertEqual(len(integrations), 3)
        self.assertEqual(len(self.of_type("AWS::ApiGatewayV2::Authorizer")), 1)
        for route in self.of_type("AWS::ApiGatewayV2::Route").values():
            props = route["Properties"]
            self.assertEqual(props["ApiId"], {"Ref": "HttpApi"})
            joiner, target = props["Target"]["Fn::Join"]
            self.assertEqual((joiner, target[0]), ("/", "integrations"))
            integration = integrations[target[1]["Ref"]]["Properties"]
            self.assertEqual(integration["ApiId"], {"Ref": "HttpApi"})
            self.assertEqual(integration["IntegrationType"], "AWS_PROXY")
            self.assertEqual(integration["IntegrationMethod"], "POST")
            self.assertEqual(integration["PayloadFormatVersion"], "2.0")
            uri = integration["IntegrationUri"]["Fn::Sub"]
            actual[props["RouteKey"]] = next(name for name in CORE_FUNCTIONS if "${" + name + ".Arn}" in uri)
            if props["AuthorizationType"] == "NONE":
                public.append(props["RouteKey"])
                self.assertNotIn("AuthorizerId", props)
            else:
                self.assertEqual(props["AuthorizationType"], "JWT")
                self.assertEqual(props["AuthorizerId"], {"Ref": "HttpApiCognitoJwtAuthorizer"})
        self.assertEqual(actual, expected)
        self.assertEqual(public, ["GET /health"])
        self.assertEqual(len(self.of_type("AWS::Lambda::Permission")), 14)

    def test_bootstrap_api_identity_protocol_and_disabled_endpoint_are_retained(self):
        before = self.bootstrap["Resources"]["HttpApi"]
        after = self.resources["HttpApi"]
        self.assertEqual(before["Type"], after["Type"])
        for key in ("Name", "ProtocolType", "DisableExecuteApiEndpoint"):
            self.assertEqual(before["Properties"][key], after["Properties"][key])
        self.assertEqual(after, self.full["Resources"]["HttpApi"])
        self.assertIs(after["Properties"]["DisableExecuteApiEndpoint"], True)
        for forbidden in ("Body", "BodyS3Location", "Target", "RouteKey"):
            self.assertNotIn(forbidden, after["Properties"])
        self.assertEqual(self.core["Outputs"]["HttpApiId"]["Value"], {"Ref": "HttpApi"})
        self.assertEqual(after["Properties"]["CorsConfiguration"]["AllowOrigins"], {"Ref": "StagingWebOrigins"})
        self.assertEqual(self.resources["HttpApiCognitoJwtAuthorizer"], self.full["Resources"]["HttpApiCognitoJwtAuthorizer"])

    def test_existing_artifacts_roles_boundaries_and_log_retention_are_unchanged(self):
        self.assertEqual(len(self.of_type("AWS::IAM::Role")), 3)
        self.assertEqual(len(self.of_type("AWS::Logs::LogGroup")), 3)
        logs = self.of_type("AWS::Logs::LogGroup")
        for function in CORE_FUNCTIONS:
            self.assertEqual(self.resources[function], self.full["Resources"][function])
            self.assertEqual(self.resources[function + "Role"], self.full["Resources"][function + "Role"])
            entry = self.manifest["functions"][function]
            role = self.resources[function + "Role"]["Properties"]
            self.assertEqual(role["RoleName"], entry["role_name"])
            self.assertEqual(role["Path"], self.manifest["role_path"])
            self.assertEqual(role["PermissionsBoundary"], f"arn:aws:iam::{self.manifest['account']}:policy/{entry['boundary_policy_name']}")
            self.assertEqual(role["ManagedPolicyArns"], ["arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"])
            for policy in role.get("Policies", []):
                for statement in policy["PolicyDocument"]["Statement"]:
                    actions = statement["Action"]
                    actions = [actions] if isinstance(actions, str) else actions
                    self.assertTrue(all(action.startswith("dynamodb:") for action in actions))
                    self.assertEqual(statement["Resource"], {"Fn::GetAtt": ["CasesTable", "Arn"]})
            matching_logs = [item for item in logs.values() if item["Properties"]["LogGroupName"] == {"Fn::Sub": "/aws/lambda/${" + function + "}"}]
            self.assertEqual(len(matching_logs), 1)
            self.assertEqual(matching_logs[0]["Properties"]["RetentionInDays"], 7)
            environment = self.resources[function]["Properties"]["Environment"]["Variables"]
            self.assertEqual(environment["AUTH_MODE"], "jwt")
            self.assertEqual(environment["STAGING_ALLOWED_USER_SUBS"], {"Ref": "StagingAllowedUserSubs"})
            self.assertTrue(set(environment).isdisjoint({"JOB_QUEUE_URL", "UPLOAD_BUCKET", "BEDROCK_MODEL_ID"}))

    def test_references_parameters_outputs_and_dependency_graph_are_complete(self):
        parameters = self.core["Parameters"]
        references(self.core, self.resources, parameters)
        self.assertEqual(parameter_uses({key: value for key, value in self.core.items() if key != "Parameters"}, parameters), set(parameters))
        artifact_parameters = {name for name in parameters if name.endswith("ArtifactKey")}
        self.assertEqual(artifact_parameters, {builder.ARTIFACT_PARAMETERS[name] for name in CORE_FUNCTIONS})
        for name in self.graph:
            self.assertFalse(reaches(self.graph, name, name), name)
        stage = self.resources["HttpApiStage"]
        self.assertEqual(set(stage["DependsOn"]), set(self.of_type("AWS::ApiGatewayV2::Route")))
        self.assertNotIn("JobDeadLetterQueueUrl", self.core["Outputs"])
        self.assertEqual(self.resources["CasesTable"], self.full["Resources"]["CasesTable"])
        self.assertTrue(self.core["Parameters"]["StagingAllowedUserSubs"]["NoEcho"])


if __name__ == "__main__":
    unittest.main()
