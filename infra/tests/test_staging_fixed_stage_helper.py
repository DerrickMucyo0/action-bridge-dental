"""Offline security/lifecycle tests for the fixed-request, one-attempt helper."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import copy
import fnmatch
import importlib.util
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from botocore.exceptions import ClientError, ReadTimeoutError


ROOT = Path(__file__).resolve().parents[2]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'infra/staging' / file)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


H = load('fixed_helper_security', 'stage-helper-handler.py')
B = load('fixed_helper_builder', 'prepare-stage-test-helper.py')
BEFORE = datetime(2026, 10, 28, 5, 0, tzinfo=timezone.utc)
AFTER = datetime(2026, 10, 28, 7, 0, tzinfo=timezone.utc)
CONTEXT = SimpleNamespace(invoked_function_arn=f'arn:aws:lambda:{H.REGION}:{H.ACCOUNT}:function:{H.FUNCTION}', aws_request_id='synthetic-test-request')


def error(code, operation, message='synthetic AWS error'):
    return ClientError({'Error': {'Code': code, 'Message': message}, 'ResponseMetadata': {'RequestId': 'synthetic-service-request'}}, operation)


class FakeGateway:
    def __init__(self):
        self.api = {'ApiId': H.API, 'ProtocolType': 'HTTP', 'DisableExecuteApiEndpoint': True}
        self.stage = None
        self.posts = []
        self.create_error = None
        self.calls = []

    def get_api(self, **args):
        self.calls.append(('get_api', args)); return copy.deepcopy(self.api)

    def get_stage(self, **args):
        self.calls.append(('get_stage', args))
        if self.stage is None: raise error('NotFoundException', 'GetStage')
        return copy.deepcopy(self.stage)

    def create_stage(self, **args):
        self.calls.append(('create_stage', args)); self.posts.append(copy.deepcopy(args))
        if self.create_error: raise self.create_error
        self.stage = {'StageName': 'staging', 'AutoDeploy': False, 'Tags': {},
                      'DefaultRouteSettings': {'ThrottlingBurstLimit': 20, 'ThrottlingRateLimit': 10, 'DetailedMetricsEnabled': False}}
        return copy.deepcopy(self.stage)


class FakeLatch:
    def __init__(self, barrier=None):
        self.used = False; self.requests = []; self.lock = threading.Lock(); self.barrier = barrier; self.fail_after_write = False

    def put_parameter(self, **args):
        if self.barrier: self.barrier.wait(timeout=5)
        with self.lock:
            self.requests.append(copy.deepcopy(args))
            if self.used: raise error('ParameterAlreadyExists', 'PutParameter')
            self.used = True
            if self.fail_after_write: raise ReadTimeoutError(endpoint_url='https://ssm.us-east-2.amazonaws.com')
            return {'Version': 1, 'Tier': 'Standard'}


def resolve(node):
    if isinstance(node, list): return [resolve(v) for v in node]
    if not isinstance(node, dict): return node
    if set(node) == {'Ref'}:
        return {'HelperBoundary': f'arn:aws:iam::{H.ACCOUNT}:policy/SyntheticHelperBoundary',
                'AWS::StackId': f'arn:aws:cloudformation:{H.REGION}:{H.ACCOUNT}:stack/{B.STACK}/synthetic'}[node['Ref']]
    if set(node) == {'Fn::GetAtt'}:
        return {'StageCreationHelper': CONTEXT.invoked_function_arn,
                'HelperExecutionRole': f'arn:aws:iam::{H.ACCOUNT}:role/SyntheticHelperRole'}[node['Fn::GetAtt'][0]]
    return {k: resolve(v) for k, v in node.items()}


def decision(policy, action, resource, context):
    matches = []
    for statement in policy['Statement']:
        actions = statement['Action']; actions = [actions] if isinstance(actions, str) else actions
        resources = statement['Resource']; resources = [resources] if isinstance(resources, str) else resources
        if not any(fnmatch.fnmatchcase(action, a) for a in actions) or not any(fnmatch.fnmatchcase(resource, r) for r in resources): continue
        valid = True
        for operator, values in statement.get('Condition', {}).items():
            for key, want in values.items():
                got = context.get(key)
                if operator in ('StringEquals', 'ArnEquals'): good = got == want
                elif operator == 'Bool': good = got is (want == 'true')
                elif operator == 'Null': good = (got is None) == (want == 'true')
                elif operator == 'DateLessThan': good = got is not None and datetime.fromisoformat(got.replace('Z', '+00:00')) < datetime.fromisoformat(want.replace('Z', '+00:00'))
                else: raise AssertionError(operator)
                valid = valid and good
        if valid: matches.append(statement['Effect'])
    return 'explicitDeny' if 'Deny' in matches else 'allowed' if 'Allow' in matches else 'implicitDeny'


class FixedStageHelperTests(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway(); self.latch = FakeLatch(); self.services = []

    def client(self, service):
        self.services.append(service)
        return {'apigatewayv2': self.gateway, 'ssm': self.latch}[service]

    def invoke(self, event=None, context=CONTEXT):
        with patch.object(H, 'client', self.client), patch.object(H, 'utcnow', return_value=BEFORE):
            return H.handler({} if event is None else event, context)

    def test_success_is_exact_fixed_request_and_second_invocation_never_posts_again(self):
        result = self.invoke()
        self.assertEqual(result['status'], 'PASS_STAGE_CREATED_VERIFIED')
        self.assertEqual(self.gateway.posts, [H.REQUEST])
        self.assertNotIn('Tags', self.gateway.posts[0]); self.assertNotIn('DeploymentId', self.gateway.posts[0])
        self.assertIs(self.gateway.posts[0]['AutoDeploy'], False)
        request = self.latch.requests[0]
        self.assertEqual((request['Name'], request['Type'], request['Tier'], request['DataType'], request['Overwrite']),
                         (H.LATCH, 'String', 'Standard', 'text', False))
        self.assertEqual(self.invoke()['status'], 'STOP_EXISTING_STAGE')
        self.assertEqual(len(self.gateway.posts), 1)

    def test_nonempty_or_nonobject_input_has_no_AWS_calls(self):
        for event in (None, [], False, 0, '', {'ApiId': 'other'}, {'AutoDeploy': True}, {'DeploymentId': 'id'}, {'Tags': {}}):
            self.services.clear()
            with self.subTest(event=event), patch.object(H, 'client', self.client), patch.object(H, 'utcnow', return_value=BEFORE):
                result = H.handler(event, CONTEXT)
                self.assertEqual(result['status'], 'STOP_VERIFICATION_OR_RUNTIME_ERROR_NO_RETRY'); self.assertFalse(self.services)

    def test_wrong_account_region_function_or_qualifier_has_no_AWS_calls(self):
        for arn in (CONTEXT.invoked_function_arn.replace(H.ACCOUNT, '111122223333'), CONTEXT.invoked_function_arn.replace(H.REGION, 'us-east-1'),
                    CONTEXT.invoked_function_arn + ':1', CONTEXT.invoked_function_arn + '-other'):
            with self.subTest(arn=arn):
                result = self.invoke(context=SimpleNamespace(invoked_function_arn=arn, aws_request_id='synthetic'))
                self.assertFalse(result['stageCallAttempted']); self.assertFalse(self.services)

    def test_expired_invocation_never_uses_AWS(self):
        with patch.object(H, 'client', self.client), patch.object(H, 'utcnow', return_value=AFTER):
            result = H.handler({}, CONTEXT)
        self.assertFalse(result['stageCallAttempted']); self.assertFalse(self.services)

    def test_expiry_after_latch_stops_before_stage_POST(self):
        with patch.object(H, 'client', self.client), patch.object(H, 'utcnow', side_effect=[BEFORE, BEFORE, BEFORE, AFTER]):
            result = H.handler({}, CONTEXT)
        self.assertTrue(self.latch.used); self.assertTrue(result['latchConsumedOrUncertain']); self.assertFalse(self.gateway.posts)

    def test_existing_stage_or_enabled_api_never_consumes_latch_or_mutates_stage(self):
        self.gateway.stage = {'StageName': 'staging', 'AutoDeploy': True, 'Tags': {'secret': 'must-not-be-returned'}}
        result = self.invoke(); self.assertEqual(result['status'], 'STOP_EXISTING_STAGE')
        self.assertNotIn('must-not-be-returned', json.dumps(result)); self.assertFalse(self.latch.requests); self.assertFalse(self.gateway.posts)
        self.gateway.stage = None; self.gateway.api['DisableExecuteApiEndpoint'] = False
        result = self.invoke(); self.assertFalse(result['stageCallAttempted']); self.assertFalse(self.latch.requests)

    def test_stage_authorization_failure_is_returned_exactly_and_cannot_be_retried(self):
        self.gateway.create_error = error('AccessDeniedException', 'CreateStage', 'synthetic missing TagResource Allow')
        result = self.invoke()
        self.assertEqual((result['phase'], result['code'], result['message'], result['awsRequestId']),
                         ('create-stage', 'AccessDeniedException', 'synthetic missing TagResource Allow', 'synthetic-service-request'))
        self.assertEqual(self.invoke()['status'], 'STOP_ATTEMPT_ALREADY_CONSUMED')
        self.assertEqual(len(self.gateway.posts), 1)

    def test_ambiguous_latch_timeout_never_posts_or_resets_latch(self):
        self.latch.fail_after_write = True
        result = self.invoke(); self.assertEqual(result['phase'], 'consume-one-attempt-latch')
        self.assertTrue(result['latchConsumedOrUncertain']); self.assertFalse(self.gateway.posts)
        self.assertEqual(self.invoke()['status'], 'STOP_ATTEMPT_ALREADY_CONSUMED'); self.assertFalse(self.gateway.posts)

    def test_malformed_latch_confirmation_never_posts(self):
        for response in ({'Version': 2}, {'Version': True}, {}, {'Version': 1, 'Tier': 'Advanced'}):
            with self.subTest(response=response), patch.object(self.latch, 'put_parameter', return_value=response):
                result = self.invoke(); self.assertFalse(result['stageCallAttempted']); self.assertTrue(result['latchConsumedOrUncertain'])
        self.assertFalse(self.gateway.posts)

    def test_ambiguous_stage_timeout_is_not_retried(self):
        self.gateway.create_error = ReadTimeoutError(endpoint_url='https://apigateway.us-east-2.amazonaws.com')
        result = self.invoke(); self.assertTrue(result['stageCallAttempted']); self.assertFalse(result['cleanupAttempted'])
        self.assertEqual(self.invoke()['status'], 'STOP_ATTEMPT_ALREADY_CONSUMED'); self.assertEqual(len(self.gateway.posts), 1)

    def test_simultaneous_invocations_can_make_only_one_stage_POST(self):
        self.latch.barrier = threading.Barrier(2)
        with patch.object(H, 'client', self.client), patch.object(H, 'utcnow', return_value=BEFORE), ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: H.handler({}, CONTEXT), range(2)))
        self.assertEqual(len(self.gateway.posts), 1)
        self.assertEqual({r['status'] for r in results}, {'PASS_STAGE_CREATED_VERIFIED', 'STOP_ATTEMPT_ALREADY_CONSUMED'})

    def test_unsafe_stage_response_stops_without_patch_delete_or_retry(self):
        create = self.gateway.create_stage
        def changed(**kwargs):
            value = create(**kwargs); self.gateway.stage['DeploymentId'] = 'unexpected'; return value
        self.gateway.create_stage = changed
        result = self.invoke(); self.assertTrue(result['stageCallReturned']); self.assertEqual(result['phase'], 'verify-stage')
        self.assertEqual(len(self.gateway.posts), 1); self.assertFalse(result['cleanupAttempted'])

    def test_sdk_retries_are_one_total_attempt(self):
        self.assertEqual(H.SDK_CONFIG.retries['total_max_attempts'], 1)
        self.assertNotIn('max_attempts', H.SDK_CONFIG.retries)


class HelperPolicyTests(unittest.TestCase):
    def setUp(self):
        self.runtime = B.runtime_policy(); self.user = resolve(B.user_policy())
        self.context = {'aws:CurrentTime': '2026-10-28T05:00:00Z', 'aws:RequestedRegion': H.REGION,
                        'aws:SecureTransport': True, 'aws:PrincipalArn': B.USER, 'ssm:Overwrite': 'false'}

    def test_developer_only_invokes_fixed_helper_and_cannot_call_gateway_or_mutate_safeguards(self):
        self.assertEqual(decision(self.user, 'lambda:InvokeFunction', CONTEXT.invoked_function_arn, self.context), 'allowed')
        denied = [('lambda:InvokeFunction', CONTEXT.invoked_function_arn + ':1'), ('lambda:UpdateFunctionCode', CONTEXT.invoked_function_arn),
                  ('lambda:UpdateFunctionConfiguration', CONTEXT.invoked_function_arn), ('apigateway:POST', B.API + '/stages'),
                  ('apigateway:DELETE', B.API), ('apigateway:PATCH', B.API), ('iam:PassRole', resolve({'Fn::GetAtt': ['HelperExecutionRole', 'Arn']})),
                  ('iam:PutUserPolicy', B.USER), ('ssm:DeleteParameter', B.LATCH_ARN), ('ssm:PutParameter', B.LATCH_ARN)]
        for action, resource in denied:
            with self.subTest(action=action): self.assertEqual(decision(self.user, action, resource, self.context), 'implicitDeny')

    def test_runtime_only_creates_in_exact_api_and_cannot_deploy_delete_update_tag_or_use_KMS(self):
        self.assertEqual(decision(self.runtime, 'apigateway:POST', B.API + '/stages', self.context), 'allowed')
        for action, resource in [('apigateway:POST', B.API + '/deployments'), ('apigateway:PATCH', B.API + '/stages/staging'),
                                 ('apigateway:DELETE', B.API), ('apigateway:DELETE', B.API + '/stages/staging'),
                                 ('apigateway:POST', B.API.replace(H.API, 'production') + '/stages'), ('apigateway:TagResource', B.API + '/stages'),
                                 ('kms:Decrypt', '*'), ('ssm:DeleteParameter', B.LATCH_ARN)]:
            with self.subTest(action=action, resource=resource): self.assertEqual(decision(self.runtime, action, resource, self.context), 'implicitDeny')

    def test_latch_is_create_only_and_policies_are_denied(self):
        self.assertEqual(decision(self.runtime, 'ssm:PutParameter', B.LATCH_ARN, self.context), 'allowed')
        self.assertEqual(decision(self.runtime, 'ssm:PutParameter', B.LATCH_ARN, {**self.context, 'ssm:Overwrite': 'true'}), 'implicitDeny')
        self.assertEqual(decision(self.runtime, 'ssm:PutParameter', B.LATCH_ARN, {**self.context, 'ssm:Policies': 'true'}), 'explicitDeny')

    def test_region_tags_transport_principal_and_expiry_fail_closed(self):
        for key, value in [('aws:RequestedRegion', 'us-east-1'), ('aws:SecureTransport', False), ('aws:CurrentTime', H.EXPIRES_AT),
                           ('aws:TagKeys', ['unexpected'])]:
            with self.subTest(key=key): self.assertEqual(decision(self.runtime, 'apigateway:POST', B.API + '/stages', {**self.context, key: value}), 'implicitDeny')
        for key, value in [('aws:PrincipalArn', 'arn:aws:iam::111122223333:user/actionbridge-developer'), ('aws:CurrentTime', H.EXPIRES_AT)]:
            with self.subTest(key=key): self.assertEqual(decision(self.user, 'lambda:InvokeFunction', CONTEXT.invoked_function_arn, {**self.context, key: value}), 'implicitDeny')

    def test_owner_template_contains_only_new_helper_resources_no_application_stage_or_trigger(self):
        t = B.template(); resources = t['Resources']
        self.assertEqual(len(resources), 5)
        self.assertEqual(resources['HelperBoundary']['Properties']['PolicyDocument'], resources['HelperExecutionRole']['Properties']['Policies'][0]['PolicyDocument'])
        self.assertEqual(resources['HelperExecutionRole']['Properties']['PermissionsBoundary'], {'Ref': 'HelperBoundary'})
        self.assertEqual(resources['StageCreationHelper']['Properties']['Code']['ZipFile'], B.HANDLER.read_text())
        self.assertNotIn('Environment', resources['StageCreationHelper']['Properties'])
        self.assertNotIn('ReservedConcurrentExecutions', resources['StageCreationHelper']['Properties'])
        self.assertEqual(resources['DisableAsyncRetries']['Properties']['MaximumRetryAttempts'], 0)
        self.assertEqual(resources['DeveloperTemporaryPermission']['Type'], 'AWS::IAM::ManagedPolicy')
        self.assertEqual(resources['DeveloperTemporaryPermission']['Properties']['Users'], ['actionbridge-developer'])
        self.assertNotIn('ManagedPolicyName', resources['DeveloperTemporaryPermission']['Properties'])
        types = {r['Type'] for r in resources.values()}
        self.assertFalse(any(v.startswith(('AWS::ApiGateway', 'AWS::DynamoDB', 'AWS::S3')) for v in types))
        self.assertNotIn('AWS::Lambda::Permission', types); self.assertNotIn('AWS::Lambda::Url', types)


if __name__ == '__main__': unittest.main()
