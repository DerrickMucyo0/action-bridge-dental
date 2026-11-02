"""Offline regression checks for the staged API and fixed staging selectors."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import yaml

from test_template import CLIENT, POOL, SUBJECT, SelectedTemplate


ROOT = Path(__file__).resolve().parents[2]
BUILDER_PATH = ROOT / "infra/staging/build-templates.py"
SPEC = importlib.util.spec_from_file_location("staging_template_builder", BUILDER_PATH)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def deployment_values(data):
    values = {
        "AppEnv": "staging", "ExistingUserPoolId": POOL,
        "ExistingUserPoolClientId": CLIENT, "StagingAllowedUserSubs": SUBJECT,
    }
    for logical_id, slug in builder.FUNCTION_SLUGS.items():
        values[builder.ARTIFACT_PARAMETERS[logical_id]] = (
            data["artifact_prefix"].rstrip("/") + "/" + slug + "/" + "a" * 64 + ".zip"
        )
    return values


class StagedTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = builder.manifest()
        # This runs the actual pinned SAM translator under its network-denial
        # guard with explicit fictional credentials, not an AWS service call.
        cls.templates = builder.rendered_templates()
        cls.bootstrap = cls.templates["bootstrap.yaml"]
        cls.backend = cls.templates["backend.yaml"]

    def test_generated_public_files_match_offline_compiler(self):
        for name, template in self.templates.items():
            with self.subTest(template=name):
                self.assertEqual((builder.GENERATED / name).read_text(), builder.rendered_text(template))
                self.assertEqual(yaml.safe_load(builder.rendered_text(template)), template)

    def test_compilation_preserves_generic_source_and_rejects_inventory_drift(self):
        source = builder.source_template()
        baseline = copy.deepcopy(source)
        builder.backend_template(self.data, source)
        self.assertEqual(source, baseline)
        bad = copy.deepcopy(source)
        bad["Resources"]["UnexpectedTable"] = copy.deepcopy(source["Resources"]["CasesTable"])
        with self.assertRaisesRegex(ValueError, "Expanded staging inventory changed"):
            builder.backend_template(self.data, bad)
        # Manifest target is fixed rather than a runtime option that could point
        # the compiler at an unrelated account.
        self.assertEqual(self.data["account"], "631367363628")
        self.assertEqual(self.data["region"], "us-east-2")
        self.assertEqual(self.backend["Metadata"]["StagingTarget"]["Account"], self.data["account"])

    def test_bootstrap_is_only_empty_http_api_with_endpoint_disabled(self):
        self.assertEqual(set(self.bootstrap["Resources"]), {"HttpApi"})
        api = self.bootstrap["Resources"]["HttpApi"]
        self.assertEqual(api["Type"], "AWS::ApiGatewayV2::Api")
        self.assertEqual(api["Properties"], {
            "Name": self.data["api"]["name"], "ProtocolType": "HTTP",
            "DisableExecuteApiEndpoint": True,
        })
        self.assertNotIn("Transform", self.bootstrap)
        self.assertNotIn("Parameters", self.bootstrap)
        self.assertEqual(self.bootstrap["Outputs"]["HttpApiId"]["Value"], {"Ref": "HttpApi"})

    def test_backend_preserves_bootstrap_api_identity_and_protocol(self):
        before = self.bootstrap["Resources"]["HttpApi"]
        after = self.backend["Resources"]["HttpApi"]
        self.assertEqual(before["Type"], after["Type"])
        for key in ("Name", "ProtocolType"):
            self.assertEqual(before["Properties"][key], after["Properties"][key])
        # ProtocolType is a replacement-sensitive property. The compiler keeps
        # HTTP explicitly instead of relying on SAM's normally omitted value.
        self.assertEqual(after["Properties"]["ProtocolType"], "HTTP")
        self.assertTrue(after["Properties"]["DisableExecuteApiEndpoint"])
        for conflicting in ("Body", "BodyS3Location", "Target", "RouteKey"):
            self.assertNotIn(conflicting, after["Properties"])
        self.assertEqual(self.backend["Outputs"]["HttpApiId"]["Value"], {"Ref": "HttpApi"})

    def test_backend_is_expanded_cloudformation_with_no_cognito_resources(self):
        self.assertNotIn("Transform", self.backend)
        self.assertNotIn("Globals", self.backend)
        resources = self.backend["Resources"]
        self.assertEqual(len(resources), 69)
        self.assertFalse(any(item["Type"].startswith(("AWS::Cognito::", "AWS::Serverless::")) for item in resources.values()))
        self.assertEqual(sum(item["Type"] == "AWS::Lambda::Function" for item in resources.values()), 5)
        self.assertEqual(sum(item["Type"] == "AWS::IAM::Role" for item in resources.values()), 5)

    def test_staging_only_parameters_require_existing_identity_and_approved_subjects(self):
        values = deployment_values(self.data)
        SelectedTemplate(self.backend, values)
        for name, value in (("AppEnv", "dev"), ("AppEnv", "demo"),
                            ("ExistingUserPoolId", ""), ("ExistingUserPoolClientId", ""),
                            ("StagingAllowedUserSubs", "")):
            with self.subTest(parameter=name, value=value), self.assertRaises(ValueError):
                SelectedTemplate(self.backend, {**values, name: value})
        # The old common ARN is accepted but does not select any runtime role's
        # boundary; all five fixed per-function policies are required instead.
        self.assertEqual(self.backend["Parameters"]["StagingRuntimePermissionsBoundaryArn"]["Default"], "")

    def test_every_function_and_role_has_exact_staging_name_path_and_boundary(self):
        resources = self.backend["Resources"]
        for logical_id, entry in self.data["functions"].items():
            with self.subTest(function=logical_id):
                self.assertEqual(resources[logical_id]["Properties"]["FunctionName"], entry["name"])
                props = resources[logical_id + "Role"]["Properties"]
                self.assertEqual(props["RoleName"], entry["role_name"])
                self.assertEqual(props["Path"], self.data["role_path"])
                self.assertEqual(props["PermissionsBoundary"],
                                 f"arn:aws:iam::{self.data['account']}:policy/{entry['boundary_policy_name']}")
                self.assertEqual(props["AssumeRolePolicyDocument"]["Statement"], [{
                    "Action": ["sts:AssumeRole"], "Effect": "Allow",
                    "Principal": {"Service": ["lambda.amazonaws.com"]},
                }])

    def test_data_resources_use_exact_manifest_names(self):
        resources = self.backend["Resources"]
        for logical_id, key, expected in (
            ("CasesTable", "TableName", self.data["table"]["name"]),
            ("UploadBucket", "BucketName", self.data["buckets"]["uploads"]),
            ("JobQueue", "QueueName", self.data["queues"]["work"]),
            ("JobDeadLetterQueue", "QueueName", self.data["queues"]["dead_letter"]),
        ):
            with self.subTest(resource=logical_id):
                self.assertEqual(resources[logical_id]["Properties"][key], expected)

    def test_artifacts_are_required_hash_keys_and_preserve_parameter_refs(self):
        values = deployment_values(self.data)
        for logical_id, parameter in builder.ARTIFACT_PARAMETERS.items():
            with self.subTest(function=logical_id):
                spec = self.backend["Parameters"][parameter]
                self.assertNotIn("Default", spec)
                code = self.backend["Resources"][logical_id]["Properties"]["Code"]
                self.assertEqual(code, {"S3Bucket": self.data["buckets"]["artifacts"], "S3Key": {"Ref": parameter}})
                for value in ("other-stack/health.zip", "actionbridge-dental-staging/health/latest.zip"):
                    with self.assertRaises(ValueError):
                        SelectedTemplate(self.backend, {**values, parameter: value})
                missing = dict(values)
                del missing[parameter]
                with self.assertRaisesRegex(ValueError, "Missing parameter"):
                    SelectedTemplate(self.backend, missing)

    def test_identity_cors_and_approval_values_remain_deployment_parameter_refs(self):
        text = json.dumps(self.backend)
        for fictional in (POOL, CLIENT, SUBJECT, "0" * 64 + ".zip"):
            self.assertNotIn(fictional, text)
        resources = self.backend["Resources"]
        jwt = resources["HttpApiCognitoJwtAuthorizer"]["Properties"]["JwtConfiguration"]
        self.assertEqual(jwt["Audience"], [{"Ref": "ExistingUserPoolClientId"}])
        self.assertEqual(jwt["Issuer"], {"Fn::Sub": "https://cognito-idp.${AWS::Region}.amazonaws.com/${ExistingUserPoolId}"})
        self.assertEqual(resources["HttpApi"]["Properties"]["CorsConfiguration"]["AllowOrigins"], {"Ref": "StagingWebOrigins"})
        self.assertTrue(self.backend["Parameters"]["StagingAllowedUserSubs"]["NoEcho"])
        for item in self.backend["Resources"].values():
            if item["Type"] == "AWS::Lambda::Function":
                variables = item["Properties"]["Environment"]["Variables"]
                self.assertEqual(variables["STAGING_ALLOWED_USER_SUBS"], {"Ref": "StagingAllowedUserSubs"})
                self.assertEqual(variables["AUTH_MODE"], "jwt")

    def test_explicit_routes_preserve_every_sam_endpoint_and_function(self):
        resources = self.backend["Resources"]
        source = builder.staging_source(self.data, builder.source_template())["Resources"]
        routes = {name: item for name, item in resources.items() if item["Type"] == "AWS::ApiGatewayV2::Route"}
        integrations = {name: item for name, item in resources.items() if item["Type"] == "AWS::ApiGatewayV2::Integration"}
        self.assertEqual(len(routes), 21)
        self.assertEqual(len(integrations), 4)
        self.assertEqual(sum(item["Type"] == "AWS::Lambda::Permission" for item in resources.values()), 21)
        expected = {}
        for function in builder.FUNCTION_SLUGS:
            for event in source[function]["Properties"].get("Events", {}).values():
                if event["Type"] == "HttpApi":
                    props = event["Properties"]
                    expected[props["Method"] + " " + props["Path"]] = function
        actual = {}
        for item in routes.values():
            props = item["Properties"]
            self.assertEqual(props["ApiId"], {"Ref": "HttpApi"})
            joiner, target = props["Target"]["Fn::Join"]
            self.assertEqual((joiner, target[0]), ("/", "integrations"))
            integration = integrations[target[1]["Ref"]]["Properties"]
            function = next(name for name in builder.FUNCTION_SLUGS if "${" + name + ".Arn}" in integration["IntegrationUri"]["Fn::Sub"])
            actual[props["RouteKey"]] = function
            self.assertEqual(integration["ApiId"], {"Ref": "HttpApi"})
            self.assertEqual(integration["IntegrationType"], "AWS_PROXY")
            self.assertEqual(integration["IntegrationMethod"], "POST")
            self.assertEqual(integration["PayloadFormatVersion"], "2.0")
            if props["RouteKey"] == "GET /health":
                self.assertEqual(props["AuthorizationType"], "NONE")
                self.assertNotIn("AuthorizerId", props)
            else:
                self.assertEqual(props["AuthorizationType"], "JWT")
                self.assertEqual(props["AuthorizerId"], {"Ref": "HttpApiCognitoJwtAuthorizer"})
            # These are WebSocket-only properties and must not be copied from
            # OpenAPI path parameter definitions into an HTTP Route resource.
            self.assertTrue(set(props).isdisjoint({"RequestParameters", "RequestModels", "ApiKeyRequired"}))
        self.assertEqual(actual, expected)
        self.assertEqual(set(resources["HttpApiStage"]["DependsOn"]), set(routes))

    def test_unhandled_sam_route_features_fail_closed_instead_of_disappearing(self):
        source = builder.source_template()
        source["Resources"]["HealthFunction"]["Properties"]["Events"]["Health"]["Properties"]["TimeoutInMillis"] = 12345
        with self.assertRaisesRegex(ValueError, "Unreviewed HTTP event properties"):
            builder.backend_template(self.data, source)

    def test_unhandled_nested_openapi_configuration_is_rejected(self):
        translate = builder.Translator.translate

        def add_schema(body):
            body["components"]["schemas"] = {"Unreviewed": {"type": "object"}}

        def change_server(body):
            body["servers"][0]["x-unreviewed-extension"] = True

        def change_cors(body):
            body["x-amazon-apigateway-cors"]["allowCredentials"] = True

        for mutate in (add_schema, change_server, change_cors):
            with self.subTest(feature=mutate.__name__):
                def changed_translation(translator, *args, **kwargs):
                    result = translate(translator, *args, **kwargs)
                    mutate(result["Resources"]["HttpApi"]["Properties"]["Body"])
                    return result

                with patch.object(builder.Translator, "translate", new=changed_translation):
                    with self.assertRaisesRegex(ValueError, "Unreviewed nested OpenAPI configuration"):
                        builder.backend_template(self.data, builder.source_template())

    def test_unhandled_source_authorizer_fields_are_not_silently_discarded(self):
        for level in ("auth", "authorizer", "jwt_configuration"):
            with self.subTest(level=level):
                source = builder.source_template()
                auth = source["Resources"]["HttpApi"]["Properties"]["Auth"]
                authorizer = auth["Authorizers"]["CognitoJwt"]
                target = {"auth": auth, "authorizer": authorizer,
                          "jwt_configuration": authorizer["JwtConfiguration"]}[level]
                target["x-unreviewed-field"] = True
                with self.assertRaisesRegex(ValueError, "Unreviewed source authentication configuration"):
                    builder.backend_template(self.data, source)


if __name__ == "__main__":
    unittest.main()
