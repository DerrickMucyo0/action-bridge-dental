"""Offline SAM/CloudFormation regression checks. No AWS connection or credentials are used."""
import copy
from fnmatch import fnmatchcase
import re
import socket
import unittest
from pathlib import Path
from unittest.mock import patch

import boto3
import yaml
from samtranslator.parser.parser import Parser
from samtranslator.translator.translator import Translator
from samtranslator.metrics.metrics import Metrics

ROOT = Path(__file__).resolve().parents[2]
SUBJECT = "00000000-0000-4000-8000-000000000001"
POOL = "us-east-2_Staging01"
CLIENT = "stagingclient0123456789abcd"
BOUNDARY = "arn:aws:iam::111122223333:policy/actionbridge/staging/runtime-boundary"
NO_VALUE = object()


class CloudFormationLoader(yaml.SafeLoader):
    pass


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
TEMPLATE = yaml.load((ROOT / "infra/template.yaml").read_text(), Loader=CloudFormationLoader)


class SelectedTemplate:
    """Evaluate the small set of documented intrinsics used by this template's conditions."""
    def __init__(self, template, overrides=None):
        self.template = template
        self.parameters = {}
        for name, spec in template.get("Parameters", {}).items():
            value = (overrides or {}).get(name, spec.get("Default"))
            if value is None:
                raise ValueError("Missing parameter: " + name)
            values = str(value).split(",") if spec["Type"] == "CommaDelimitedList" else [value]
            for item in values:
                if "AllowedPattern" in spec and not re.fullmatch(spec["AllowedPattern"], str(item)):
                    raise ValueError("Invalid parameter: " + name)
                if "AllowedValues" in spec and item not in spec["AllowedValues"]:
                    raise ValueError("Invalid parameter: " + name)
                if "MinValue" in spec and float(item) < spec["MinValue"]:
                    raise ValueError("Invalid parameter: " + name)
                if "MaxValue" in spec and float(item) > spec["MaxValue"]:
                    raise ValueError("Invalid parameter: " + name)
            self.parameters[name] = values if spec["Type"] == "CommaDelimitedList" else value
        self.parameters.update({"AWS::StackName": "actionbridge-dental-staging", "AWS::Region": "us-east-2", "AWS::AccountId": "111122223333", "AWS::Partition": "aws", "AWS::URLSuffix": "amazonaws.com", "AWS::NoValue": NO_VALUE})
        for rule in template.get("Rules", {}).values():
            if self.value(rule.get("RuleCondition", True)):
                for assertion in rule["Assertions"]:
                    if not self.value(assertion["Assert"]):
                        raise ValueError(assertion["AssertDescription"])

    def condition(self, name):
        return self.value(self.template["Conditions"][name])

    def ref(self, name):
        if name in self.parameters:
            return self.parameters[name]
        return {"UserPool": "us-east-2_Managed01", "UserPoolClient": "managedclient0123456789abcd", "HttpApi": "exampleapi"}.get(name, name + "-physical-id")

    def value(self, node):
        if isinstance(node, list):
            values = [self.value(item) for item in node]
            return [item for item in values if item is not NO_VALUE]
        if not isinstance(node, dict):
            return node
        if "Ref" in node:
            return self.ref(node["Ref"])
        if "Condition" in node and len(node) == 1:
            return self.condition(node["Condition"])
        if "Fn::Equals" in node:
            left, right = node["Fn::Equals"]
            return self.value(left) == self.value(right)
        if "Fn::Not" in node:
            return not self.value(node["Fn::Not"][0])
        if "Fn::And" in node:
            return all(self.value(item) for item in node["Fn::And"])
        if "Fn::Or" in node:
            return any(self.value(item) for item in node["Fn::Or"])
        if "Fn::If" in node:
            name, yes, no = node["Fn::If"]
            return self.value(yes if self.condition(name) else no)
        if "Fn::GetAtt" in node:
            name, attribute = node["Fn::GetAtt"]
            return f"arn:aws:offline:us-east-2:111122223333:{name}/{attribute}"
        if "Fn::Join" in node:
            separator, values = node["Fn::Join"]
            return separator.join(str(item) for item in self.value(values))
        if "Fn::Sub" in node:
            spec = node["Fn::Sub"]
            text, variables = (spec, {}) if isinstance(spec, str) else spec
            def replace(match):
                name = match.group(1)
                if name in variables:
                    return str(self.value(variables[name]))
                if "." in name:
                    return self.value({"Fn::GetAtt": name.split(".", 1)})
                return str(self.ref(name))
            return re.sub(r"\$\{([^}]+)\}", replace, text)
        result = {}
        for key, item in node.items():
            selected = self.value(item)
            if selected is not NO_VALUE:
                result[key] = selected
        return result

    def section(self, name):
        return {key: self.value({k: v for k, v in item.items() if k != "Condition"}) for key, item in self.template.get(name, {}).items() if "Condition" not in item or self.condition(item["Condition"])}


def parameters(environment="dev", external=False):
    values = {"AppEnv": environment}
    if external:
        values.update(ExistingUserPoolId=POOL, ExistingUserPoolClientId=CLIENT)
    if environment == "staging":
        values["StagingAllowedUserSubs"] = SUBJECT
        values["StagingRuntimePermissionsBoundaryArn"] = BOUNDARY
    return values


def translated(overrides):
    template = copy.deepcopy(TEMPLATE)
    # SAM deploy packages local CodeUri folders; substitute equivalent offline S3 references.
    for name, resource in template["Resources"].items():
        if resource["Type"] == "AWS::Serverless::Function":
            resource["Properties"]["CodeUri"] = {"Bucket": "offline-artifacts", "Key": name + ".zip"}
    policy_map = {name: "arn:aws:iam::aws:policy/service-role/" + name for name in ("AWSLambdaBasicExecutionRole", "AWSLambdaSQSQueueExecutionRole")}
    # Explicit fictional credentials avoid local credential discovery; networking is prohibited.
    session = boto3.Session(region_name="us-east-2", aws_access_key_id="offline", aws_secret_access_key="offline")
    normalized = SelectedTemplate(template, overrides).parameters
    values = {name: normalized[name] for name in template["Parameters"]}
    metrics = Metrics()  # Its default publisher is explicitly a no-op, not CloudWatch.
    with patch.object(socket.socket, "connect", side_effect=AssertionError("AWS/network access is prohibited in offline checks")):
        output = Translator(policy_map, Parser(), boto_session=session, metrics=metrics).translate(template, values)
        metrics.publish()
    return SelectedTemplate(output, overrides)


def statements(role):
    for policy in role["Properties"].get("Policies", []):
        yield from policy["PolicyDocument"]["Statement"]


def actions(statement):
    value = statement["Action"]
    return value if isinstance(value, list) else [value]


class InfrastructureRegressionTests(unittest.TestCase):
    def test_real_sam_transform_in_all_environment_and_identity_modes(self):
        for env in ("dev", "demo", "staging"):
            for external in (False, True):
                with self.subTest(environment=env, external=external):
                    selected = translated(parameters(env, external))
                    resources = selected.section("Resources")
                    self.assertEqual(sum(resource["Type"] == "AWS::Lambda::Function" for resource in resources.values()), 5)
                    identities = [resource for resource in resources.values() if resource["Type"].startswith("AWS::Cognito::")]
                    self.assertEqual(len(identities), 0 if external else 3)
                    outputs = selected.section("Outputs")
                    self.assertEqual("ManagedLoginDomain" in outputs, not external)
                    self.assertEqual(outputs["UserPoolId"]["Value"], POOL if external else "us-east-2_Managed01")
                    self.assertEqual(outputs["UserPoolClientId"]["Value"], CLIENT if external else "managedclient0123456789abcd")
                    self.assertEqual(outputs["CognitoIssuer"]["Value"], "https://cognito-idp.us-east-2.amazonaws.com/" + (POOL if external else "us-east-2_Managed01"))
                    api = resources["HttpApi"]["Properties"]["Body"]
                    jwt = api["components"]["securitySchemes"]["CognitoJwt"]["x-amazon-apigateway-authorizer"]["jwtConfiguration"]
                    self.assertEqual(jwt["issuer"], outputs["CognitoIssuer"]["Value"])
                    self.assertEqual(jwt["audience"], [outputs["UserPoolClientId"]["Value"]])
                    self.assertNotIn(SUBJECT, str(outputs))

    def test_unpaired_external_parameters_are_rejected(self):
        for partial in ({"ExistingUserPoolId": POOL}, {"ExistingUserPoolClientId": CLIENT}):
            with self.subTest(partial=partial), self.assertRaises(ValueError):
                SelectedTemplate(TEMPLATE, partial)

    def test_empty_staging_approval_list_is_rejected(self):
        with self.assertRaises(ValueError):
            SelectedTemplate(TEMPLATE, {**parameters("staging"), "StagingAllowedUserSubs": ""})

    def test_staging_requires_a_runtime_permissions_boundary(self):
        for value in (None, ""):
            values = parameters("staging")
            if value is None:
                del values["StagingRuntimePermissionsBoundaryArn"]
            else:
                values["StagingRuntimePermissionsBoundaryArn"] = value
            with self.subTest(boundary=value), self.assertRaisesRegex(ValueError, "runtime permissions boundary"):
                SelectedTemplate(TEMPLATE, values)

    def test_runtime_boundary_arn_validates_syntax_without_claiming_policy_existence(self):
        # Parameter validation checks ARN syntax only. IAM checks the policy's
        # actual existence and same-account requirement when a boundary is set.
        for value in (BOUNDARY, "arn:aws-us-gov:iam::444455556666:policy/runtime_boundary+=,.@-"):
            with self.subTest(boundary=value):
                selected = SelectedTemplate(TEMPLATE, {**parameters("staging"), "StagingRuntimePermissionsBoundaryArn": value})
                self.assertEqual(selected.parameters["StagingRuntimePermissionsBoundaryArn"], value)
        invalid = (
            "arn:aws:iam::111122223333:role/runtime-boundary",
            "arn:aws:iam::11112222333:policy/runtime-boundary",
            "arn:aws:iam::111122223333:policy/",
            "arn:aws:iam::111122223333:policy/path/",
            "arn:aws:iam::111122223333:policy/path//runtime-boundary",
            "arn:aws:iam::111122223333:policy/runtime-*",
            "arn:aws:iam::111122223333:policy/runtime boundary",
            "arn:aws:iam::111122223333:policy/" + "x" * 129,
        )
        for value in invalid:
            with self.subTest(boundary=value), self.assertRaisesRegex(ValueError, "StagingRuntimePermissionsBoundaryArn"):
                SelectedTemplate(TEMPLATE, {**parameters("staging"), "StagingRuntimePermissionsBoundaryArn": value})

    def test_generated_runtime_roles_have_staging_boundary_path_and_lambda_only_trust(self):
        expected_names = {name + "Role" for name, item in TEMPLATE["Resources"].items() if item["Type"] == "AWS::Serverless::Function"}
        self.assertEqual(len(expected_names), 5)
        for external in (False, True):
            with self.subTest(external_identity=external):
                resources = translated(parameters("staging", external)).section("Resources")
                roles = {name: item for name, item in resources.items() if item["Type"] == "AWS::IAM::Role"}
                self.assertEqual(set(roles), expected_names)
                for name, role in roles.items():
                    with self.subTest(role=name):
                        props = role["Properties"]
                        self.assertEqual(props["PermissionsBoundary"], BOUNDARY)
                        self.assertEqual(props["Path"], "/actionbridge/staging/actionbridge-dental-staging/")
                        self.assertNotIn("RoleName", props)
                        self.assertEqual(props["AssumeRolePolicyDocument"], {
                            "Version": "2012-10-17",
                            "Statement": [{"Action": ["sts:AssumeRole"], "Effect": "Allow", "Principal": {"Service": ["lambda.amazonaws.com"]}}],
                        })

    def test_runtime_boundary_and_role_path_do_not_change_dev_or_demo(self):
        for env in ("dev", "demo"):
            for supplied_boundary in (False, True):
                values = parameters(env)
                if supplied_boundary:
                    values["StagingRuntimePermissionsBoundaryArn"] = BOUNDARY
                with self.subTest(environment=env, supplied_boundary=supplied_boundary):
                    resources = translated(values).section("Resources")
                    roles = [item["Properties"] for item in resources.values() if item["Type"] == "AWS::IAM::Role"]
                    self.assertEqual(len(roles), 5)
                    for role in roles:
                        self.assertNotIn("PermissionsBoundary", role)
                        self.assertEqual(role.get("Path", "/"), "/")
                        self.assertNotIn("RoleName", role)

    def test_staging_origins_reject_wildcards_paths_and_insecure_remote_hosts(self):
        for origin in ("*", "https://*.vercel.app", "https://preview.example.test/path", "http://remote.example.test", "https://preview.example.test/"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                SelectedTemplate(TEMPLATE, {**parameters("staging", True), "StagingWebOrigins": origin})

    def test_staging_api_and_upload_cors_share_only_approved_origins(self):
        for origin in (None, "http://127.0.0.1:5173,https://approved-preview.example.test"):
            values = parameters("staging", True)
            if origin:
                values["StagingWebOrigins"] = origin
            selected = translated(values)
            resources = selected.section("Resources")
            expected = origin.split(",") if origin else ["http://localhost:5173", "http://127.0.0.1:5173"]
            cors = resources["HttpApi"]["Properties"]["Body"]["x-amazon-apigateway-cors"]
            self.assertEqual(cors["allowOrigins"], expected)
            self.assertEqual(cors["allowMethods"], ["GET", "POST", "PATCH", "OPTIONS"])
            self.assertEqual(cors["allowHeaders"], ["authorization", "content-type", "idempotency-key"])
            self.assertEqual(cors["exposeHeaders"], ["x-request-id"])
            self.assertEqual(resources["UploadBucket"]["Properties"]["CorsConfiguration"]["CorsRules"][0]["AllowedOrigins"], expected)
            self.assertNotIn("https://action-bridge-dental-web.vercel.app", expected)

    def test_default_managed_identity_and_data_configuration_are_preserved(self):
        selected = SelectedTemplate(TEMPLATE)
        resources = selected.section("Resources")
        pool = resources["UserPool"]
        self.assertEqual(pool["DeletionPolicy"], "Delete")
        self.assertEqual(pool["Properties"]["AdminCreateUserConfig"], {"AllowAdminCreateUserOnly": True})
        self.assertEqual(pool["Properties"]["Policies"]["PasswordPolicy"], {"MinimumLength": 12, "RequireLowercase": True, "RequireUppercase": True, "RequireNumbers": True, "RequireSymbols": False})
        self.assertNotIn("VerificationMessageTemplate", pool["Properties"])
        self.assertFalse(resources["UserPoolClient"]["Properties"]["GenerateSecret"])
        self.assertEqual(resources["HttpApi"]["Properties"]["DefaultRouteSettings"], {"ThrottlingBurstLimit": 20, "ThrottlingRateLimit": 10})
        self.assertEqual(resources["CasesTable"]["Properties"]["BillingMode"], "PAY_PER_REQUEST")
        self.assertEqual(resources["CasesTable"]["Properties"]["TimeToLiveSpecification"], {"AttributeName": "expiresAt", "Enabled": True})
        self.assertEqual(resources["UploadBucket"]["Properties"]["PublicAccessBlockConfiguration"], {"BlockPublicAcls": True, "BlockPublicPolicy": True, "IgnorePublicAcls": True, "RestrictPublicBuckets": True})

    def test_self_registration_opt_in_still_only_changes_managed_identity(self):
        managed = SelectedTemplate(TEMPLATE, {"EnableSelfRegistration": "true"}).section("Resources")["UserPool"]["Properties"]
        self.assertEqual(managed["AdminCreateUserConfig"], {"AllowAdminCreateUserOnly": False})
        self.assertEqual(managed["VerificationMessageTemplate"], {"DefaultEmailOption": "CONFIRM_WITH_CODE"})
        external = SelectedTemplate(TEMPLATE, {**parameters("staging", True), "EnableSelfRegistration": "true"}).section("Resources")
        self.assertFalse(any(item["Type"].startswith("AWS::Cognito::") for item in external.values()))

    def test_staging_variables_and_counter_permissions_never_apply_to_dev_or_demo(self):
        for env in ("dev", "demo", "staging"):
            selected = translated(parameters(env))
            resources = selected.section("Resources")
            for resource in resources.values():
                if resource["Type"] == "AWS::Lambda::Function":
                    variables = resource["Properties"]["Environment"]["Variables"]
                    self.assertEqual(variables["APP_ENV"], env)
                    self.assertEqual(variables["AUTH_MODE"], "jwt")
                    self.assertEqual("STAGING_ALLOWED_USER_SUBS" in variables, env == "staging")
            counter_statements = [item for item in statements(resources["JobsFunctionRole"]) if "dynamodb:UpdateItem" in actions(item)]
            self.assertEqual(len(counter_statements), 1 if env == "staging" else 0)
            if counter_statements:
                self.assertEqual(counter_statements[0]["Condition"], {"ForAllValues:StringLike": {"dynamodb:LeadingKeys": ["STAGING_QUOTA#*"]}})

    def test_runtime_marketplace_subscription_permissions_are_removed(self):
        resources = translated(parameters("staging", True)).section("Resources")
        all_actions = [action for resource in resources.values() if resource["Type"] == "AWS::IAM::Role" for item in statements(resource) for action in actions(item)]
        self.assertFalse(any(action.startswith("aws-marketplace:") for action in all_actions))

    def test_transcribe_existing_jobs_are_scoped_without_breaking_start(self):
        for env in ("dev", "demo", "staging"):
            with self.subTest(environment=env):
                resources = translated(parameters(env, True)).section("Resources")
                worker = resources["JobWorkerFunctionRole"]
                variables = resources["JobWorkerFunction"]["Properties"]["Environment"]["Variables"]
                prefix = "actionbridge-actionbridge-dental-staging_" if env == "staging" else "actionbridge-"
                self.assertEqual("TRANSCRIPTION_JOB_PREFIX" in variables, env == "staging")
                if env == "staging":
                    self.assertEqual(variables["TRANSCRIPTION_JOB_PREFIX"], prefix)
                for action in ("transcribe:GetTranscriptionJob", "transcribe:DeleteTranscriptionJob"):
                    resource = next(item["Resource"] for item in statements(worker) if action in actions(item))
                    self.assertEqual(resource, "arn:aws:transcribe:us-east-2:111122223333:transcription-job/" + prefix + "*")
                start = next(item for item in statements(worker) if "transcribe:StartTranscriptionJob" in actions(item))
                self.assertEqual(start["Resource"], "*")

    def test_staging_transcribe_namespace_cannot_overlap_prefix_related_stack_names(self):
        selected = translated(parameters("staging", True))
        selected.parameters["AWS::StackName"] = "foo"
        worker = selected.section("Resources")["JobWorkerFunctionRole"]
        resource = next(item["Resource"] for item in statements(worker) if "transcribe:GetTranscriptionJob" in actions(item))
        base = "arn:aws:transcribe:us-east-2:111122223333:transcription-job/"
        self.assertTrue(fnmatchcase(base + "actionbridge-foo_synthetic-job", resource))
        self.assertFalse(fnmatchcase(base + "actionbridge-foo-bar_synthetic-job", resource))


if __name__ == "__main__":
    unittest.main()
