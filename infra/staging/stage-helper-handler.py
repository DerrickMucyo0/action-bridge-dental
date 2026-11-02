"""Owner-controlled, fixed-request Lambda for ONE isolated staging-stage test.

No caller input is forwarded to AWS. No tags, deployment, API update, deletion,
retry or cleanup operation exists. The standard String SSM latch is retained
outside the helper stack and is never overwritten or reset by this code.
"""
from datetime import datetime, timezone
import json

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

ACCOUNT = '631367363628'
REGION = 'us-east-2'
API = 'l52iwors8c'
FUNCTION = 'actionbridge-dental-staging-stage-create-once'
EXPIRES_AT = '2026-10-28T06:30:00Z'
LATCH = '/actionbridge/dental/staging/stage-create-once'
REQUEST = {'ApiId': API, 'StageName': 'staging', 'AutoDeploy': False,
           'DefaultRouteSettings': {'ThrottlingBurstLimit': 20, 'ThrottlingRateLimit': 10}}
SDK_CONFIG = Config(retries={'total_max_attempts': 1, 'mode': 'standard'}, connect_timeout=5, read_timeout=10)


def utcnow():
    return datetime.now(timezone.utc)


def client(service):
    return boto3.client(service, region_name=REGION, config=SDK_CONFIG)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def within_window():
    require(utcnow() < datetime.fromisoformat(EXPIRES_AT.replace('Z', '+00:00')), 'Permission window expired')


def api_disabled(api):
    require(api.get('ApiId') == API and api.get('ProtocolType') == 'HTTP' and
            api.get('DisableExecuteApiEndpoint') is True, 'Expected preserved HTTP API with disabled endpoint')


def safe_stage(stage):
    result = {k: stage.get(k) for k in ('StageName', 'AutoDeploy', 'DeploymentId', 'DefaultRouteSettings')}
    result['Tags'] = {} if not stage.get('Tags') else '[NONEMPTY_TAG_VALUES_REDACTED]'
    return result


def stage_is_safe(stage):
    require(stage.get('StageName') == 'staging' and stage.get('AutoDeploy') is False and
            not stage.get('DeploymentId') and not stage.get('Tags'), 'Created stage configuration requires review')
    settings = stage.get('DefaultRouteSettings', {})
    require(settings.get('ThrottlingBurstLimit') == 20 and settings.get('ThrottlingRateLimit') == 10 and
            set(settings) <= {'ThrottlingBurstLimit', 'ThrottlingRateLimit', 'DetailedMetricsEnabled', 'DataTraceEnabled', 'LoggingLevel'} and
            settings.get('DetailedMetricsEnabled', False) is False and settings.get('DataTraceEnabled', False) is False and
            settings.get('LoggingLevel', 'OFF') == 'OFF' and not stage.get('StageVariables') and
            not stage.get('RouteSettings') and not stage.get('AccessLogSettings'), 'Unexpected stage settings require review')


def handler(event, context):
    latch_consumed = False
    stage_call_attempted = False
    stage_call_returned = False
    phase = 'input'
    try:
        require(type(event) is dict and event == {}, 'Only an empty JSON object is accepted')
        require(context.invoked_function_arn == f'arn:aws:lambda:{REGION}:{ACCOUNT}:function:{FUNCTION}', 'Wrong helper identity or qualifier')
        within_window()
        gateway = client('apigatewayv2')
        phase = 'api-preflight'
        api_disabled(gateway.get_api(ApiId=API))
        phase = 'stage-preflight'
        try:
            existing = gateway.get_stage(ApiId=API, StageName='staging')
        except ClientError as error:
            if error.response.get('Error', {}).get('Code') != 'NotFoundException':
                raise
        else:
            # Never adopt, update, delete or overwrite an existing stage.
            return {'status': 'STOP_EXISTING_STAGE', 'stage': safe_stage(existing), 'stageCallAttempted': False}
        within_window()
        phase = 'consume-one-attempt-latch'
        try:
            stored = client('ssm').put_parameter(
                Name=LATCH, Type='String', Tier='Standard', DataType='text', Overwrite=False,
                Value=json.dumps({'apiId': API, 'stageName': 'staging', 'requestId': context.aws_request_id,
                                  'attemptRecordedAtUtc': utcnow().isoformat()}, separators=(',', ':')))
        except ClientError as error:
            if error.response.get('Error', {}).get('Code') == 'ParameterAlreadyExists':
                return {'status': 'STOP_ATTEMPT_ALREADY_CONSUMED', 'stageCallAttempted': False}
            raise
        # A timeout here is ambiguous and MUST NOT lead to a POST. Even if this
        # response is malformed, an existing latch blocks all future attempts.
        require(type(stored.get('Version')) is int and stored['Version'] == 1 and
                stored.get('Tier', 'Standard') == 'Standard', 'Latch creation was not confirmed')
        latch_consumed = True
        within_window()  # Recheck immediately before the sole stage mutation.
        phase = 'create-stage'
        stage_call_attempted = True
        gateway.create_stage(
            ApiId=API, StageName='staging', AutoDeploy=False,
            DefaultRouteSettings={'ThrottlingBurstLimit': 20, 'ThrottlingRateLimit': 10})
        stage_call_returned = True
        phase = 'verify-stage'
        actual = gateway.get_stage(ApiId=API, StageName='staging')
        stage_is_safe(actual)
        phase = 'verify-disabled-api'
        api_disabled(gateway.get_api(ApiId=API))
        return {'status': 'PASS_STAGE_CREATED_VERIFIED', 'apiId': API, 'region': REGION,
                'stage': safe_stage(actual), 'executeApiEndpointDisabled': True,
                'latchConsumed': True, 'stageCallAttempted': True, 'automaticRetries': 0}
    except ClientError as error:
        # Only fixed-request AWS diagnostics are returned. Never log event,
        # credentials, environment variables or SDK signed download URLs.
        detail = error.response.get('Error', {})
        return {'status': 'STOP_AWS_ERROR_NO_RETRY', 'phase': phase, 'code': detail.get('Code'),
                'message': detail.get('Message'), 'awsRequestId': error.response.get('ResponseMetadata', {}).get('RequestId'),
                'latchConsumedOrUncertain': latch_consumed or phase == 'consume-one-attempt-latch',
                'stageCallAttempted': stage_call_attempted, 'stageCallReturned': stage_call_returned,
                'automaticRetries': 0, 'cleanupAttempted': False}
    except Exception as error:
        return {'status': 'STOP_VERIFICATION_OR_RUNTIME_ERROR_NO_RETRY', 'phase': phase,
                'errorType': type(error).__name__, 'message': str(error) if type(error) is ValueError else 'Unexpected runtime error; owner review required',
                'latchConsumedOrUncertain': latch_consumed or phase == 'consume-one-attempt-latch',
                'stageCallAttempted': stage_call_attempted, 'stageCallReturned': stage_call_returned,
                'automaticRetries': 0, 'cleanupAttempted': False}
