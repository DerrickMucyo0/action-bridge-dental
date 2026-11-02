"""Offline deployment-boundary tests; no claim of live stage authorization."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

import boto3
from botocore.serialize import create_serializer
from botocore.validate import validate_parameters


ROOT = Path(__file__).resolve().parents[2]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'infra/staging' / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


S = module('stage_separation', 'prepare-stage-separated-core.py')
B = module('stage_separation_source', 'build-templates.py')
D = module('stage_separation_delegation', 'prepare-delegated-access.py')


class StageSeparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.core = D.candidate_template(B.core_template(B.manifest(), B.source_template()))
        cls.candidate = S.conditional_core(cls.core)

    def test_initial_stage_is_excluded_and_every_remaining_resource_is_unchanged(self):
        active = S.initial_resources(self.candidate)
        self.assertEqual(len(active), 40)
        self.assertNotIn('HttpApiStage', active)
        self.assertEqual(len(active) - 1, 39)
        for name, resource in active.items():
            self.assertEqual(resource, self.core['Resources'][name], name)
        self.assertEqual(len({r['Type'] for r in active.values()}), 8)
        self.assertEqual(len({r['Type'] for r in self.candidate['Resources'].values()}), 9)
        self.assertEqual(self.candidate['Parameters'][S.PARAMETER]['Default'], 'false')

    def test_future_managed_stage_does_not_auto_deploy_or_claim_tagging_fixed(self):
        active = S.initial_resources(self.candidate, 'true')
        self.assertEqual(len(active), 41)
        stage = active['HttpApiStage']
        self.assertIs(stage['Properties']['AutoDeploy'], False)
        self.assertEqual(stage['Properties']['Tags'], self.core['Resources']['HttpApiStage']['Properties']['Tags'])
        self.assertEqual(stage['DependsOn'], self.core['Resources']['HttpApiStage']['DependsOn'])
        self.assertEqual(self.candidate['Outputs']['ApiBaseUrl']['Condition'], S.CONDITION)

    def test_authentication_api_isolation_and_deferred_jobs_are_preserved(self):
        active = S.initial_resources(self.candidate)
        api = active['HttpApi']['Properties']
        self.assertIs(api['DisableExecuteApiEndpoint'], True)
        self.assertEqual(api['ProtocolType'], 'HTTP')
        routes = [r['Properties'] for r in active.values() if r['Type'] == 'AWS::ApiGatewayV2::Route']
        self.assertEqual(len(routes), 14)
        self.assertEqual(sum(r['AuthorizationType'] == 'JWT' for r in routes), 13)
        self.assertEqual(sum(r['Type'] == 'AWS::ApiGatewayV2::Integration' for r in active.values()), 3)
        self.assertEqual(sum(r['Type'] == 'AWS::Lambda::Permission' for r in active.values()), 14)
        for resource in active.values():
            self.assertNotIn(resource['Type'], {'AWS::Lambda::EventSourceMapping', 'AWS::SQS::Queue', 'AWS::S3::Bucket'})
            self.assertFalse(resource['Type'].startswith('AWS::IAM::'))
        for name in B.CORE_FUNCTIONS:
            self.assertEqual(active[name]['Properties']['Environment']['Variables']['AUTH_MODE'], 'jwt')

    def test_unexpected_inbound_stage_dependencies_fail_closed(self):
        for value in ({'Ref': 'HttpApiStage'}, {'Fn::GetAtt': ['HttpApiStage', 'Id']},
                      {'Fn::Sub': '${HttpApiStage}'}, {'DependsOn': 'HttpApiStage'}):
            bad = copy.deepcopy(self.core)
            bad['Metadata']['Unreviewed'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'depends on the excluded stage'):
                S.conditional_core(bad)

    def test_unknown_conditions_and_nonstring_selectors_are_not_silently_evaluated(self):
        bad = copy.deepcopy(self.candidate)
        bad['Resources']['CasesTable']['Condition'] = 'UnreviewedCondition'
        with self.assertRaisesRegex(ValueError, 'unfamiliar condition'):
            S.initial_resources(bad)
        with self.assertRaises(ValueError):
            S.initial_resources(self.candidate, False)

    def test_api_quick_create_or_import_cannot_create_an_implicit_stage(self):
        for key in ('Body', 'BodyS3Location', 'Target', 'RouteKey'):
            bad = copy.deepcopy(self.core)
            bad['Resources']['HttpApi']['Properties'][key] = 'unreviewed'
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'protections changed'):
                S.conditional_core(bad)

    def test_direct_stage_request_uses_real_sdk_shape_and_omits_all_tagging_and_deployment_fields(self):
        client = boto3.client('apigatewayv2', region_name='us-east-2', aws_access_key_id='offline', aws_secret_access_key='offline')
        operation = client.meta.service_model.operation_model('CreateStage')
        request = S.untagged_stage_request()
        validate_parameters(request, operation.input_shape)
        wire = create_serializer(client.meta.service_model.protocol).serialize_to_request(request, operation)
        body = json.loads(wire['body'])
        self.assertEqual(wire['method'], 'POST')
        self.assertEqual(wire['url_path'], '/v2/apis/l52iwors8c/stages')
        self.assertEqual(body, {'stageName': 'staging', 'autoDeploy': False,
                               'defaultRouteSettings': {'throttlingBurstLimit': 20, 'throttlingRateLimit': 10}})
        self.assertNotIn('tags', body)
        self.assertNotIn('deploymentId', body)

    def test_external_stage_readback_rejects_drift_and_traffic_enabling_changes(self):
        api = {'ApiId': S.API, 'ProtocolType': 'HTTP', 'DisableExecuteApiEndpoint': True}
        stage = {'StageName': 'staging', 'AutoDeploy': False,
                 'DefaultRouteSettings': {'ThrottlingBurstLimit': 20, 'ThrottlingRateLimit': 10}}
        self.assertTrue(S.check_external_stage(api, stage))
        defaults = {**stage, 'DefaultRouteSettings': {**stage['DefaultRouteSettings'],
                    'DetailedMetricsEnabled': False, 'DataTraceEnabled': False, 'LoggingLevel': 'OFF'}}
        self.assertTrue(S.check_external_stage(api, defaults))
        for key, value in (('AutoDeploy', True), ('Tags', {'unexpected': 'tag'}), ('DeploymentId', 'unapproved-deployment'),
                           ('StageName', 'production'), ('StageVariables', {'unexpected': 'value'})):
            bad = {**stage, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                S.check_external_stage(api, bad)
        for key, value in (('ApiId', 'another-api'), ('DisableExecuteApiEndpoint', False)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                S.check_external_stage({**api, key: value}, stage)
        for extra in ({'DetailedMetricsEnabled': True}, {'DataTraceEnabled': True}, {'LoggingLevel': 'INFO'}, {'UnknownSetting': False}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                S.check_external_stage(api, {**stage, 'DefaultRouteSettings': {**stage['DefaultRouteSettings'], **extra}})

    def test_local_change_set_request_always_explicitly_selects_false_and_preserves_artifacts(self):
        previous = {'StackName': S.STACK_ID, 'RoleARN': S.EXECUTOR, 'ChangeSetType': 'UPDATE',
                    'ChangeSetName': 'old-review', 'Description': 'old', 'ClientToken': 'old',
                    'ImportExistingResources': False, 'IncludeNestedStacks': False,
                    'ResourceTypes': sorted({r['Type'] for r in self.core['Resources'].values()}),
                    'TemplateBody': json.dumps(self.core), 'Parameters': [
                        {'ParameterKey': 'HealthArtifactKey', 'ParameterValue': 'existing/health.zip'},
                        {'ParameterKey': 'CasesArtifactKey', 'ParameterValue': 'existing/cases.zip'},
                        {'ParameterKey': 'CalculationsArtifactKey', 'ParameterValue': 'existing/calculations.zip'}]}
        request = S.initial_request(previous, self.candidate, 'local-review-only')
        self.assertEqual(request['Parameters'][:-1], previous['Parameters'])
        self.assertEqual(request['Parameters'][-1], {'ParameterKey': S.PARAMETER, 'ParameterValue': 'false'})
        self.assertEqual(request['RoleARN'], previous['RoleARN'])
        self.assertEqual(request['ResourceTypes'], previous['ResourceTypes'])
        self.assertFalse(request['ImportExistingResources'])
        self.assertFalse(request['IncludeNestedStacks'])


if __name__ == '__main__':
    unittest.main()
