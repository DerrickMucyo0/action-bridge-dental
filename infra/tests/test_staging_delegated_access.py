"""Security and preservation checks for the owner-controlled delegation proposal."""
import copy
import fnmatch
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import yaml

import test_staging_core_iam as CORE
from test_staging_role_lifecycle import decision

HERE = Path(__file__).resolve().parents[1] / "staging"
SPEC = importlib.util.spec_from_file_location("delegated", HERE / "prepare-delegated-access.py")
D = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D)
BROAD = D.doc([D.statement("Allow", "*", "*")])


def resolved(value):
    """Resolve only the intrinsics deliberately used in the access policies."""
    app = f"arn:aws:amplify:{D.REGION}:{D.ACCOUNT}:apps/d1exampleonly"
    if isinstance(value, list):
        return [resolved(item) for item in value]
    if not isinstance(value, dict):
        return value
    if "Fn::GetAtt" in value:
        if value["Fn::GetAtt"] != ["FrontendApp", "Arn"]:
            raise ValueError("Unknown intrinsic")
        return app
    if "Ref" in value:
        if value["Ref"] != "AWS::StackId":
            raise ValueError("Unknown intrinsic")
        return f"arn:aws:cloudformation:{D.REGION}:{D.ACCOUNT}:stack/{D.ACCESS_STACK}/owner-controlled"
    if "Fn::Sub" in value:
        template, mapping = value["Fn::Sub"]
        for key, item in mapping.items():
            template = template.replace("${" + key + "}", resolved(item))
        if "${" in template:
            raise ValueError("Unknown substitution")
        return template
    return {key: resolved(item) for key, item in value.items()}


def deployer_decision(action, resource, context=None, extra=None):
    """Extend the existing tested evaluator for CFN's set-valued filter only."""
    document = resolved(D.deployer_policy())
    for entry in document["Statement"]:
        clauses = entry.get("Condition", {}).pop("ForAllValues:StringEquals", {})
        for key, allowed in clauses.items():
            actual = (context or {}).get(key, [])
            if any(item not in allowed for item in actual):
                # Make this statement inapplicable without changing other rules.
                entry["Condition"]["StringEquals"] = {"test:unsupportedResourceType": "never"}
        for key, patterns in entry.get("Condition", {}).pop("StringLike", {}).items():
            actual = (context or {}).get(key)
            if actual is None or not any(fnmatch.fnmatchcase(actual, pattern) for pattern in patterns):
                entry["Condition"]["StringEquals"] = {"test:missingPrefix": "never"}
    return decision([document] + (extra or []), action, resource, context)


class DelegatedAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import shutil
        import test_staging_http_stage_tagging as TAGGING
        staging_root = D.ROOT / ".staging"
        created_staging = not staging_root.exists()
        created_source = not D.POLICY_SOURCE.exists()
        if created_source:
            D.POLICY_SOURCE.mkdir(parents=True, exist_ok=True)
            proposed = TAGGING.PROPOSAL.proposal_documents(TAGGING.PREVIOUS.recovery_a_baseline())
            for name, policy in proposed.items():
                (D.POLICY_SOURCE / name).write_text(json.dumps(policy, indent=2) + "\n")
            if created_staging:
                cls.addClassCleanup(shutil.rmtree, staging_root, True)
            else:
                cls.addClassCleanup(shutil.rmtree, D.POLICY_SOURCE, True)

    def test_quotas_dependencies_and_mfa_trust(self):
        template = D.access_template()
        resources = template["Resources"]
        self.assertEqual(len(D.ceilings()), 3)
        self.assertEqual(5 + len(D.ceilings()), 8)
        for entry in resources.values():
            if entry["Type"] == "AWS::IAM::ManagedPolicy":
                self.assertLessEqual(D.compact_size(resolved(entry["Properties"]["PolicyDocument"])), 6144)
        role = resources["DeployerRole"]
        trust = role["Properties"]["AssumeRolePolicyDocument"]["Statement"]
        self.assertEqual(trust, [{"Effect": "Allow", "Principal": {"AWS": D.DEVELOPER}, "Action": "sts:AssumeRole",
                                 "Condition": {"Bool": {"aws:MultiFactorAuthPresent": "true"}}}])
        self.assertEqual(role["Properties"]["MaxSessionDuration"], 3600)
        self.assertTrue(set(f"ExecutionCeiling{i}" for i in (1, 2, 3)) <= set(role["DependsOn"]))
        for i in (1, 2, 3):
            self.assertEqual(resources[f"ExecutionCeiling{i}"]["Properties"]["Roles"], [D.STACK + "-cfn"])
        # No per-action MFA condition that breaks the role's aws-login session.
        self.assertNotIn("MultiFactorAuthPresent", json.dumps(D.deployer_policy()))

    def test_runtime_roles_have_owner_fixed_lambda_trust_and_original_boundaries(self):
        for (name, entry), boundary in zip(D.runtime_roles().items(), D.BOUNDARIES):
            props = entry["Properties"]
            self.assertEqual(props["PermissionsBoundary"], boundary)
            self.assertEqual(props["AssumeRolePolicyDocument"]["Statement"][0]["Principal"], {"Service": "lambda.amazonaws.com"})
            self.assertEqual(entry["DeletionPolicy"], "Retain")
            self.assertNotIn("ManagedPolicyArns", props)
            self.assertTrue(all(s["Effect"] == "Allow" for s in props["Policies"][0]["PolicyDocument"]["Statement"]))

    def test_mutable_execution_policies_cannot_change_any_iam_role_trust_or_boundary(self):
        for role in [D.EXECUTOR, D.DEPLOYER, *D.ROLES, *D.ALIASES, "arn:aws:iam::195469705669:role/production"]:
            for action in ("iam:CreateRole", "iam:UpdateAssumeRolePolicy", "iam:PutRolePolicy", "iam:AttachRolePolicy",
                           "iam:PutRolePermissionsBoundary", "iam:DeleteRolePermissionsBoundary", "iam:DeleteRole",
                           "iam:CreatePolicyVersion", "iam:SetDefaultPolicyVersion"):
                self.assertEqual(decision(D.ceilings() + [BROAD], action, role, D.OHIO["StringEquals"]), "explicitDeny")
        for role in D.ROLES:
            self.assertEqual(decision(D.ceilings() + [BROAD], "iam:PassRole", role, {"iam:PassedToService": "lambda.amazonaws.com"}), "allowed")
            self.assertEqual(decision(D.ceilings() + [BROAD], "iam:PassRole", role, {"iam:PassedToService": "ec2.amazonaws.com"}), "explicitDeny")

    def test_new_ceiling_preserves_non_iam_core_lifecycle_and_exact_tagging(self):
        policies = [json.loads(path.read_text()) for path in D.POLICY_SOURCE.glob("*.json") if path.name in
                    ("identity-01.json", "identity-02.json", "identity-03.json", "guardrails-01.json", "guardrails-02.json")]
        count = 0
        for case in CORE.core_request_cases():
            if case["action"].startswith("iam:"):
                continue  # Roles no longer belong to the application stack.
            count += 1
            expected = decision(policies, case["action"], case["resource"], case["context"])
            self.assertEqual(decision(policies + D.ceilings(), case["action"], case["resource"], case["context"]), expected, case)
        self.assertGreater(count, 50)
        for action in ("apigateway:GET", "apigateway:POST", "apigateway:PUT", "apigateway:PATCH", "apigateway:DELETE"):
            self.assertEqual(decision(policies + D.ceilings(), action, D.TAG_STAGE, {"aws:RequestedRegion": D.REGION}), "allowed")

    def test_broad_allow_never_overrides_original_api_or_production_protection(self):
        tests = [("apigateway:DELETE", D.API), ("apigateway:PATCH", D.API.replace("l52iwors8c", "otherapi")),
                 ("apigateway:POST", D.API + "/stages/production"),
                 ("lambda:DeleteFunction", D.FUNCTIONS[0].replace("health", "production")),
                 ("lambda:CreateFunctionUrlConfig", D.FUNCTIONS[0]),
                 ("dynamodb:DeleteTable", D.TABLE.replace("-cases", "-production")),
                 ("sqs:DeleteQueue", D.QUEUES[0] + "-production"),
                 ("s3:DeleteBucket", D.ARTIFACTS), ("s3:PutObject", D.ARTIFACTS + "/replacement.zip"),
                 ("ec2:RunInstances", "*"), ("bedrock:InvokeModel", "*"), ("cognito-idp:DeleteUserPool", D.POOL)]
        for action, arn in tests:
            self.assertEqual(decision(D.ceilings() + [BROAD], action, arn, {"aws:RequestedRegion": D.REGION, "s3:ResourceAccount": D.ACCOUNT}),
                             "explicitDeny", (action, arn))

    def test_only_three_execution_policies_can_be_versioned_and_no_versions_deleted(self):
        for policy in D.POLICIES + D.BOUNDARIES + D.OWNER_POLICIES:
            expected = "allowed" if policy in D.EDITABLE else "explicitDeny"
            self.assertEqual(deployer_decision("iam:CreatePolicyVersion", policy), expected)
            self.assertEqual(deployer_decision("iam:SetDefaultPolicyVersion", policy), expected)
            self.assertEqual(deployer_decision("iam:DeletePolicyVersion", policy), "explicitDeny")

    def test_exact_stack_only_role_requirement_types_and_import_ban(self):
        ctx = {"aws:RequestedRegion": D.REGION, "cloudformation:RoleArn": D.EXECUTOR,
               "cloudformation:ResourceTypes": D.RESOURCE_TYPES}
        self.assertEqual(deployer_decision("cloudformation:CreateChangeSet", D.STACK_ID, ctx), "allowed")
        for changed in ({**ctx, "cloudformation:RoleArn": D.DEPLOYER},
                        {**ctx, "cloudformation:ResourceTypes": D.RESOURCE_TYPES + ["AWS::IAM::Role"]},
                        {**ctx, "cloudformation:ImportResourceTypes": ["AWS::Lambda::EventSourceMapping"]},
                        {"aws:RequestedRegion": D.REGION, "cloudformation:RoleArn": D.EXECUTOR}):
            self.assertNotEqual(deployer_decision("cloudformation:CreateChangeSet", D.STACK_ID, changed), "allowed")
        for action in ("cloudformation:ExecuteChangeSet", "cloudformation:ContinueUpdateRollback", "cloudformation:CreateChangeSet"):
            for other in (D.STACK_ID.replace(D.STACK + "/", "production/"), D.STACK_ID + "-other"):
                self.assertEqual(deployer_decision(action, other, ctx), "explicitDeny")
        # RoleArn is optional on normal rollback: omission must reuse the existing role.
        self.assertEqual(deployer_decision("cloudformation:ContinueUpdateRollback", D.STACK_ID, {"aws:RequestedRegion": D.REGION}), "allowed")

    def test_no_direct_runtime_mutations_or_unrelated_amplify_authority(self):
        for action, arn in (("lambda:TagResource", "*"),
                            ("dynamodb:PutItem", D.TABLE), ("apigateway:PATCH", D.API),
                            ("cognito-idp:AdminCreateUser", D.POOL)):
            self.assertEqual(deployer_decision(action, arn, {"aws:RequestedRegion": D.REGION}), "explicitDeny")
        self.assertEqual(deployer_decision("lambda:InvokeFunction", D.FUNCTIONS[0]), "explicitDeny")
        self.assertEqual(deployer_decision("sts:AssumeRole", "arn:aws:iam::195469705669:role/production"), "explicitDeny")
        app = resolved(D.APP)
        self.assertEqual(deployer_decision("amplify:StartDeployment", app + "/branches/staging", {"aws:RequestedRegion": D.REGION}), "allowed")
        self.assertEqual(deployer_decision("amplify:ListArtifacts", app, {"aws:RequestedRegion": D.REGION}), "allowed")
        for action, arn in (("amplify:CreateApp", "*"), ("amplify:DeleteApp", app),
                            ("amplify:StartDeployment", app + "/branches/production"),
                            ("amplify:UpdateApp", app.replace("d1exampleonly", "otherprodapp"))):
            self.assertEqual(deployer_decision(action, arn, {"aws:RequestedRegion": D.REGION}), "explicitDeny")

    def test_role_session_resource_grants_cannot_bypass_deployer_denies(self):
        for action, arn in (("s3:DeleteObject", D.ARTIFACTS + "/" + D.STACK + "/health/object.zip"),
                            ("s3:GetObject", "arn:aws:s3:::unrelated-production/private.json"),
                            ("sqs:GetQueueAttributes", D.QUEUES[0] + "-production"),
                            ("dynamodb:PutItem", D.TABLE), ("lambda:InvokeFunction", D.FUNCTIONS[0]),
                            ("iam:PutRolePolicy", D.DEPLOYER), ("ec2:RunInstances", "*")):
            self.assertEqual(deployer_decision(action, arn, {"aws:RequestedRegion": D.REGION}, [BROAD]), "explicitDeny")
        self.assertEqual(deployer_decision("amplify:GetApp", resolved(D.APP), {"aws:RequestedRegion": "us-east-1"}, [BROAD]), "explicitDeny")

    def test_upload_context_cannot_be_bypassed_by_other_resource_policy_allows(self):
        arn = D.ARTIFACTS + "/" + D.STACK + "/health/new-hash.zip"
        ctx = {"s3:ResourceAccount": D.ACCOUNT, "s3:if-none-match": "*", "s3:x-amz-server-side-encryption": "AES256"}
        self.assertEqual(deployer_decision("s3:PutObject", arn, ctx), "allowed")
        for key in ctx:
            missing = {k: v for k, v in ctx.items() if k != key}
            self.assertEqual(deployer_decision("s3:PutObject", arn, missing), "explicitDeny")
        self.assertEqual(deployer_decision("s3:PutObject", arn.replace(D.STACK + "/health", "unrelated"), ctx), "explicitDeny")

    def test_mapping_forward_delete_and_read_after_delete_without_function_context(self):
        arn = f"arn:aws:lambda:{D.REGION}:{D.ACCOUNT}:event-source-mapping:example"
        ctx = {"aws:RequestedRegion": D.REGION, "lambda:FunctionArn": D.FUNCTIONS[4]}
        for action, resource in (("lambda:CreateEventSourceMapping", "*"), ("lambda:DeleteEventSourceMapping", arn),
                                 ("lambda:UpdateEventSourceMapping", arn)):
            self.assertEqual(decision(D.ceilings() + [BROAD], action, resource, ctx), "allowed")
            self.assertEqual(decision(D.ceilings() + [BROAD], action, resource, {"aws:RequestedRegion": D.REGION}), "explicitDeny")
        for resource in (arn, "*"):
            self.assertEqual(decision(D.ceilings() + [BROAD], "lambda:GetEventSourceMapping", resource,
                                      {"aws:RequestedRegion": D.REGION}), "allowed")
        for key in ("aws:RequestTag/ActionBridgeScope", "aws:ResourceTag/ActionBridgeScope"):
            self.assertEqual(decision(D.ceilings() + [BROAD], "lambda:TagResource", arn, {"aws:RequestedRegion": D.REGION, key: D.STACK}), "allowed")
        self.assertEqual(decision(D.ceilings() + [BROAD], "lambda:TagResource", arn, {"aws:RequestedRegion": D.REGION}), "explicitDeny")
        # A separate immutable deployer policy forbids importing existing UUIDs;
        # the CFN provider cannot specify a preexisting UUID on create.
        self.assertEqual(deployer_decision("lambda:TagResource", arn, ctx), "explicitDeny")

    def test_candidate_preserves_every_nonrole_property_and_only_adds_owned_mapping_tag(self):
        for name, count, roles_removed in (("core", 41, 3), ("backend", 64, 5)):
            source = yaml.safe_load((HERE / f"generated/{name}.yaml").read_text())
            result = D.candidate_template(source)
            self.assertEqual(len(result["Resources"]), count)
            self.assertEqual(len(source["Resources"]) - count, roles_removed)
            self.assertEqual(result["Resources"]["HttpApi"], source["Resources"]["HttpApi"])
            self.assertTrue(result["Resources"]["HttpApi"]["Properties"]["DisableExecuteApiEndpoint"])
            for key, entry in result["Resources"].items():
                before = copy.deepcopy(source["Resources"][key])
                if key in D.LOGICAL:
                    before["Properties"]["Role"] = D.ROLES[D.LOGICAL.index(key)]
                if entry["Type"] == "AWS::Lambda::EventSourceMapping":
                    before["Properties"]["Tags"] = [{"Key": "ActionBridgeScope", "Value": D.STACK}]
                self.assertEqual(entry, before, key)
            self.assertTrue(all(entry["Type"] in D.RESOURCE_TYPES for entry in result["Resources"].values()))

    def test_auto_import_or_stale_template_cannot_pass_the_local_core_request_guard(self):
        candidate = D.candidate_template(yaml.safe_load((HERE / "generated/core.yaml").read_text()))
        request = {"StackName": D.STACK_ID, "RoleARN": D.EXECUTOR, "ChangeSetType": "UPDATE", "ImportExistingResources": False,
                   "IncludeNestedStacks": False, "ResourceTypes": D.RESOURCE_TYPES, "TemplateBody": json.dumps(candidate)}
        self.assertTrue(D.validate_core_change_set_request(request, candidate))
        for change in ({"ImportExistingResources": True}, {"ImportExistingResources": 0}, {"ResourcesToImport": []},
                       {"Capabilities": ["CAPABILITY_IAM"]}, {"TemplateURL": "https://unreviewed.invalid/template"},
                       {"UsePreviousTemplate": True}, {"ResourceTypes": D.RESOURCE_TYPES + ["AWS::IAM::Role"]},
                       {"TemplateBody": "{}"}, {"StackName": D.STACK_ID.replace(D.STACK, "production")}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                D.validate_core_change_set_request({**request, **change}, candidate)

    def test_empty_app_has_no_git_credentials_build_or_live_branch(self):
        app = D.access_template()["Resources"]["FrontendApp"]["Properties"]
        for forbidden in ("AccessToken", "OauthToken", "Repository", "ComputeRoleArn", "IAMServiceRole", "EnvironmentVariables"):
            self.assertNotIn(forbidden, app)
        self.assertEqual(app["Platform"], "WEB")
        self.assertFalse(any(entry["Type"] == "AWS::Amplify::Branch" for entry in D.access_template()["Resources"].values()))

    def test_generator_is_local_exclusive_and_preserves_existing_templates(self):
        before = {name: (HERE / f"generated/{name}.yaml").read_bytes() for name in ("core", "backend")}
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "proposal"
            review = D.prepare(target)
            self.assertFalse(review["aws_mutations"])
            self.assertEqual(review["expected_core_additions"], 40)
            with self.assertRaises(ValueError):
                D.prepare(target)
        self.assertEqual(before, {name: (HERE / f"generated/{name}.yaml").read_bytes() for name in before})


if __name__ == "__main__":
    unittest.main()
