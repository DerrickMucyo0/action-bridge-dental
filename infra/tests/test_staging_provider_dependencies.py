"""Property/schema audit coverage; no owner exports or AWS calls are test inputs."""
import ast
import copy
import importlib.util
from pathlib import Path
import unittest

import yaml


HERE = Path(__file__).resolve().parents[1] / "staging"
SPEC = importlib.util.spec_from_file_location("core_provider_dependency_audit", HERE / "audit-core-provider-dependencies.py")
A = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)
SPEC_D = importlib.util.spec_from_file_location("core_delegation_builder", HERE / "prepare-delegated-access.py")
D = importlib.util.module_from_spec(SPEC_D)
SPEC_D.loader.exec_module(D)


def template():
    return D.candidate_template(yaml.safe_load((HERE / "generated/core.yaml").read_text()))


def schemas():
    """Public minimal contracts exercise every classification family.

    The operational audit separately loads every full pinned AWS schema and
    rejects every action outside these explicitly handled classifications.
    """
    result = {kind: {"typeName": kind, "handlers": {"create": {"permissions": ["apigateway:POST"]}}}
              for kind in A.TYPES if kind.startswith("AWS::ApiGatewayV2::")}
    result["AWS::ApiGatewayV2::Stage"]["tagging"] = {"permissions": ["apigateway:TagResource", "apigateway:UntagResource"]}
    result["AWS::ApiGatewayV2::Api"]["handlers"]["delete"] = {"permissions": ["apigateway:DELETE"]}
    result["AWS::ApiGatewayV2::Authorizer"]["handlers"]["create"]["permissions"].append("iam:PassRole")
    result["AWS::Lambda::Permission"] = {"typeName": "AWS::Lambda::Permission", "handlers": {
        phase: {"permissions": [action]} for phase, action in
        (("create", "lambda:AddPermission"), ("read", "lambda:GetPolicy"), ("delete", "lambda:RemovePermission"))}}
    for kind, required, getters, conditional in (
            ("AWS::Lambda::Function", A.LAMBDA_REQUIRED, A.LAMBDA_GETTERS, A.LAMBDA_CONDITIONAL),
            ("AWS::DynamoDB::Table", A.DDB_REQUIRED, A.DDB_GETTERS, A.DDB_CONDITIONAL),
            ("AWS::Logs::LogGroup", A.LOGS_REQUIRED, A.LOGS_GETTERS, A.LOGS_CONDITIONAL)):
        result[kind] = {"typeName": kind, "handlers": {
            "create": {"permissions": sorted(required | set(conditional))},
            "read": {"permissions": sorted(getters)}}}
        if kind in {"AWS::Lambda::Function", "AWS::DynamoDB::Table"}:
            result[kind]["handlers"]["create"]["permissions"].extend(sorted(A.KMS_SCHEMA_ACTIONS))
    return result


class CoreProviderDependencyTests(unittest.TestCase):
    def test_all_41_resources_and_nine_types_receive_schema_classification(self):
        result = A.audit(template(), schemas(), [])
        self.assertEqual(result["resource_count"], 41)
        self.assertEqual(result["resource_type_count"], 9)
        self.assertEqual({r["logical_id"] for r in result["resources"]}, set(template()["Resources"]))
        self.assertTrue(all(r["schema_permissions"] for r in result["resources"]))
        self.assertFalse(result["deployment_readiness"])

    def test_unlisted_provider_dependency_fails_instead_of_being_dropped(self):
        contract = schemas()
        contract["AWS::Lambda::Function"]["handlers"]["read"]["permissions"].append("lambda:NewProviderGetter")
        with self.assertRaisesRegex(ValueError, "Unclassified schema permission"):
            A.audit(template(), contract, [])

    def test_missing_type_or_wrong_type_contract_fails(self):
        contract = schemas()
        contract.pop("AWS::Logs::LogGroup")
        with self.assertRaisesRegex(ValueError, "nine complete provider schemas"):
            A.audit(template(), contract, [])
        contract = schemas()
        contract["AWS::Logs::LogGroup"]["typeName"] = "AWS::Lambda::Function"
        with self.assertRaisesRegex(ValueError, "Provider type"):
            A.audit(template(), contract, [])

    def test_optional_feature_activation_requires_new_audit(self):
        for logical, key, value in (("HealthFunction", "VpcConfig", {}), ("CasesFunction", "Layers", ["new-layer"]),
                                    ("CalculationsFunction", "FunctionScalingConfig", {}), ("CasesTable", "ResourcePolicy", {}),
                                    ("CasesTable", "KinesisStreamSpecification", {}), ("HealthLogGroup", "KmsKeyId", "new-key"),
                                    ("CasesLogGroup", "DataProtectionPolicy", {}), ("HttpApi", "Body", {})):
            source = template()
            source["Resources"][logical]["Properties"][key] = value
            with self.subTest(logical=logical, key=key):
                with self.assertRaisesRegex(ValueError, "New property requires"):
                    A.audit(source, schemas(), [])

    def test_lambda_artifact_mode_and_disabled_endpoint_are_guarded(self):
        source = template()
        source["Resources"]["HealthFunction"]["Properties"]["Code"]["S3ObjectVersion"] = "version"
        with self.assertRaisesRegex(ValueError, "artifact mode"):
            A.audit(source, schemas(), [])
        source = template()
        source["Resources"]["HttpApi"]["Properties"]["DisableExecuteApiEndpoint"] = False
        with self.assertRaisesRegex(ValueError, "endpoint must remain disabled"):
            A.audit(source, schemas(), [])

    def test_absent_feature_setters_do_not_silently_excuse_metadata_getters(self):
        result = A.audit(template(), schemas(), [])
        actual = {(r["type"], r["action"]) for r in result["unproven_metadata_getters"]}
        expected = ({("AWS::Lambda::Function", a) for a in A.LAMBDA_GETTERS}
                    | {("AWS::DynamoDB::Table", a) for a in A.DDB_GETTERS}
                    | {("AWS::Logs::LogGroup", a) for a in A.LOGS_GETTERS})
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 11)
        self.assertIn(("AWS::Lambda::Function", "lambda:GetRuntimeManagementConfig"), actual)

    def test_observed_create_and_cleanup_are_recorded_without_claiming_runtime_success(self):
        source = template()
        events = []
        for logical, row in source["Resources"].items():
            if logical != "HttpApi":
                if logical in {"CasesTable", "HealthFunction", "CasesFunction", "CalculationsFunction"}:
                    events.append({"LogicalResourceId": logical, "ResourceType": row["Type"], "ResourceStatus": "CREATE_COMPLETE"})
                events.append({"LogicalResourceId": logical, "ResourceType": row["Type"], "ResourceStatus": "DELETE_COMPLETE", "PhysicalResourceId": logical + "-synthetic"})
        result = A.audit(source, schemas(), events)
        self.assertEqual(sum(r["created_successfully_this_attempt"] for r in result["resources"]), 4)
        self.assertEqual(sum(r["latest_event_status"] == "DELETE_COMPLETE" for r in result["resources"]), 40)
        self.assertFalse(result["deployment_readiness"])

    def test_provider_tagging_labels_are_exposed_as_blockers(self):
        result = A.audit(template(), schemas(), [])
        stage = next(r for r in result["resources"] if r["logical_id"] == "HttpApiStage")
        tags = [r for r in stage["schema_permissions"] if r["action"] in {"apigateway:TagResource", "apigateway:UntagResource"}]
        self.assertEqual({r["action"] for r in tags}, {"apigateway:TagResource", "apigateway:UntagResource"})
        self.assertTrue(all(r["category"] == "observed_provider_tagging_blocker" for r in tags))

    def test_tool_contains_no_aws_or_process_execution(self):
        tree = ast.parse((HERE / "audit-core-provider-dependencies.py").read_text())
        imported = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imported += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        self.assertFalse(any(name and name.split(".")[0] in {"boto3", "botocore", "subprocess", "socket", "requests", "urllib"} for name in imported))


if __name__ == "__main__":
    unittest.main()
