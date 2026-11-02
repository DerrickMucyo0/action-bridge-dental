#!/usr/bin/env python3
"""Build the temporary fixed-request owner access stack OFFLINE. Never deploys."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HANDLER = Path(__file__).with_name('stage-helper-handler.py')
spec = importlib.util.spec_from_file_location('fixed_stage_handler', HANDLER)
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)
STACK = 'actionbridge-dental-staging-stage-test-access'
USER = f'arn:aws:iam::{H.ACCOUNT}:user/actionbridge-developer'
API = f'arn:aws:apigateway:{H.REGION}::/apis/{H.API}'
LATCH_ARN = f'arn:aws:ssm:{H.REGION}:{H.ACCOUNT}:parameter' + H.LATCH


def doc(rows):
    return {'Version': '2012-10-17', 'Statement': rows}


def runtime_policy():
    common = {'StringEquals': {'aws:RequestedRegion': H.REGION},
              'Bool': {'aws:SecureTransport': 'true'}, 'DateLessThan': {'aws:CurrentTime': H.EXPIRES_AT}}
    creation = json.loads(json.dumps(common)); creation['Null'] = {'aws:TagKeys': 'true'}
    latch = json.loads(json.dumps(common)); latch['StringEquals']['ssm:Overwrite'] = 'false'
    return doc([
        {'Sid': 'InspectOnlyPreservedApiAndFixedStage', 'Effect': 'Allow', 'Action': 'apigateway:GET',
         'Resource': [API, API + '/stages/staging'], 'Condition': common},
        {'Sid': 'FixedCodeOnlyUntaggedStageCreation', 'Effect': 'Allow', 'Action': 'apigateway:POST',
         'Resource': API + '/stages', 'Condition': creation},
        {'Sid': 'ConsumeOnlyCreateOnceStandardLatch', 'Effect': 'Allow', 'Action': 'ssm:PutParameter',
         'Resource': LATCH_ARN, 'Condition': latch},
        {'Sid': 'NoParameterPoliciesOnLatch', 'Effect': 'Deny', 'Action': 'ssm:PutParameter',
         'Resource': LATCH_ARN, 'Condition': {'StringEquals': {'ssm:Policies': 'true'}}},
    ])


def user_policy():
    common = {'ArnEquals': {'aws:PrincipalArn': USER}, 'Bool': {'aws:SecureTransport': 'true'},
              'DateLessThan': {'aws:CurrentTime': H.EXPIRES_AT}}
    regional = json.loads(json.dumps(common)); regional['StringEquals'] = {'aws:RequestedRegion': H.REGION}
    return doc([
        {'Sid': 'InvokeOrInspectOnlyFixedHelper', 'Effect': 'Allow',
         'Action': ['lambda:InvokeFunction', 'lambda:GetFunction', 'lambda:GetFunctionConfiguration'],
         'Resource': {'Fn::GetAtt': ['StageCreationHelper', 'Arn']}, 'Condition': regional},
        {'Sid': 'ReadOnlyThisHelperStack', 'Effect': 'Allow',
         'Action': ['cloudformation:DescribeStacks', 'cloudformation:GetTemplate', 'cloudformation:ListStackResources'],
         'Resource': {'Ref': 'AWS::StackId'}, 'Condition': regional},
        # IAM uses a global endpoint. Do not add an Ohio RequestedRegion
        # condition that would break these exact-ARN, read-only IAM checks.
        {'Sid': 'ReadOnlyNewHelperRole', 'Effect': 'Allow',
         'Action': ['iam:GetRole', 'iam:GetRolePolicy', 'iam:ListRolePolicies', 'iam:ListAttachedRolePolicies'],
         'Resource': {'Fn::GetAtt': ['HelperExecutionRole', 'Arn']}, 'Condition': common},
        {'Sid': 'ReadOnlyNewHelperBoundary', 'Effect': 'Allow', 'Action': ['iam:GetPolicy', 'iam:GetPolicyVersion'],
         'Resource': {'Ref': 'HelperBoundary'}, 'Condition': common},
    ])


def template():
    policy = runtime_policy()
    return {
        'AWSTemplateFormatVersion': '2010-09-09',
        'Description': 'OWNER ONLY: temporary fixed-request, one-attempt staging stage test. Creates no API, deployment, website or live AI.',
        'Rules': {name: {'Assertions': [{'Assert': {'Fn::Equals': [{'Ref': key}, expected]},
                                      'AssertDescription': message}]} for name, key, expected, message in (
            ('ExactAccount', 'AWS::AccountId', H.ACCOUNT, 'Only account 631367363628 is allowed.'),
            ('ExactRegion', 'AWS::Region', H.REGION, 'Only Ohio us-east-2 is allowed.'))},
        'Metadata': {'ApprovalScope': 'SETUP ONLY; invocation/stage test requires a separate approval.',
                     'OwnerMustConfirmUnusedBeforeCreation': [H.FUNCTION, H.LATCH, STACK],
                     'OwnerMustConfirmOneFreeManagedPolicyAttachmentSlotAndExistingUserBoundaryAndDenies': True,
                     'ExistingAccessAndCoreStacksUnchanged': True,
                     'NoApplicationTrafficOrDeployment': True, 'NoRootCLICredentials': True,
                     'StandardStringLatchCreatedByInvocationOutsideStackAndIntentionallyRetained': H.LATCH},
        'Resources': {
            'HelperBoundary': {'Type': 'AWS::IAM::ManagedPolicy', 'Properties': {'PolicyDocument': policy}},
            'HelperExecutionRole': {'Type': 'AWS::IAM::Role', 'Properties': {
                'AssumeRolePolicyDocument': doc([{'Effect': 'Allow', 'Principal': {'Service': 'lambda.amazonaws.com'}, 'Action': 'sts:AssumeRole'}]),
                'PermissionsBoundary': {'Ref': 'HelperBoundary'},
                'Policies': [{'PolicyName': 'FixedStageRequestOnly', 'PolicyDocument': policy}]}},
            'StageCreationHelper': {'Type': 'AWS::Lambda::Function', 'Properties': {
                'FunctionName': H.FUNCTION, 'Description': 'Temporary single fixed untagged inactive staging-stage request; not publicly exposed.',
                'Handler': 'index.handler', 'Runtime': 'python3.13', 'Architectures': ['arm64'],
                'MemorySize': 128, 'Timeout': 90,
                'Role': {'Fn::GetAtt': ['HelperExecutionRole', 'Arn']}, 'Code': {'ZipFile': HANDLER.read_text()}}},
            'DisableAsyncRetries': {'Type': 'AWS::Lambda::EventInvokeConfig', 'Properties': {
                'FunctionName': {'Ref': 'StageCreationHelper'}, 'Qualifier': '$LATEST',
                'MaximumRetryAttempts': 0, 'MaximumEventAgeInSeconds': 60}},
            # A newly generated managed-policy name prevents overwriting an
            # existing inline policy and avoids the user's 2,048-character
            # aggregate inline-policy quota. Existing attachments stay intact.
            'DeveloperTemporaryPermission': {'Type': 'AWS::IAM::ManagedPolicy', 'Properties': {
                'Users': ['actionbridge-developer'], 'PolicyDocument': user_policy()}},
        },
        'Outputs': {
            'HelperFunctionArn': {'Value': {'Fn::GetAtt': ['StageCreationHelper', 'Arn']}},
            'HelperExecutionRoleArn': {'Value': {'Fn::GetAtt': ['HelperExecutionRole', 'Arn']}},
            'HelperBoundaryArn': {'Value': {'Ref': 'HelperBoundary'}},
            'TemporaryPolicyArn': {'Value': {'Ref': 'DeveloperTemporaryPermission'}}, 'PermissionExpiresAtUtc': {'Value': H.EXPIRES_AT},
            'RetainedAttemptLatch': {'Value': H.LATCH},
            'SetupDoesNotAuthorizeInvocation': {'Value': 'Stage invocation requires separate explicit approval and live helper verification.'},
        },
    }


def prepare(output):
    if datetime.now(timezone.utc) >= datetime.fromisoformat(H.EXPIRES_AT.replace('Z', '+00:00')):
        raise ValueError('Permission window expired; prepare and review a new window rather than attach an expired or edited proposal')
    output.mkdir(parents=True, exist_ok=True)
    value = template(); path = output / 'owner-stage-helper-stack.NOT-DEPLOYED.json'
    with path.open('x') as f:
        json.dump(value, f, indent=2); f.write('\n')
    with (output / 'fixed-helper-source.reviewed.py').open('x') as f:
        f.write(HANDLER.read_text())
    with (output / 'developer-temporary-policy.reference.json').open('x') as f:
        json.dump(user_policy(), f, indent=2); f.write('\n')
    review = {
        'status': 'PREPARED_FIXED_REQUEST_HELPER_SETUP_ONLY_NOT_AUTHORIZED', 'account': H.ACCOUNT, 'region': H.REGION,
        'stack_name': STACK, 'resources': {k: v['Type'] for k, v in value['Resources'].items()},
        'new_resources': 5, 'additional_standard_string_parameter_created_only_on_invocation': H.LATCH,
        'template_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'handler_sha256': hashlib.sha256(HANDLER.read_bytes()).hexdigest(),
        'request': H.REQUEST, 'expiration_UTC': H.EXPIRES_AT, 'expiration_New_York': '2026-10-28 02:30 EDT',
        'developer_gets_direct_apigateway_writes': False, 'developer_can_change_helper_code_role_boundary_or_latch': False,
        'runtime_boundary_matches_runtime_identity_policy': True, 'stage_POST_attempt_limit': 1, 'SDK_total_max_attempts': 1,
        'existing_core_access_stack_policies_boundaries_and_versions_changed': False,
        'no_new_KMS_S3_logs_database_or_public_endpoint_permissions': True,
        'logging_note': 'No CloudWatch Logs/data permissions are granted. The fixed result and AWS management events are evidence; no caller payload or credentials are logged.',
        'root_note': 'Root is not intrinsically required for IAM. If no authorized administrator exists, MFA root Console is a last-resort owner setup/revocation identity, never a root CLI identity or the stage-creation caller.',
        'owner_preflight': 'Confirm one free managed-policy attachment slot on the user; stop rather than detach anything existing. Confirm existing user boundary/denies permit the reviewed helper scope without changing them. Confirm stack/function/latch unused. Do not use the existing staging CFN role to provision this owner helper stack.',
        'temporary_grant_type': 'New stack-generated customer-managed policy attached only to the existing developer user; no inline-policy overwrite or 2,048-character inline quota dependency.',
        'revocation': 'Detach only the TemporaryPolicyArn to stop new invocations, then delete only the helper stack (which removes only its new function, role, boundary, async config and temporary policy). Never delete the external stage. Retain the SSM spent-attempt latch; never reset it while any helper access/function exists.',
        'remaining_gates': ['Owner explicit helper setup and temporary-resource cost approval', 'Fresh developer policy inventory/capacity and source/boundary/live helper verification',
                            'Separate explicit isolated stage-test approval', 'Stop on any error; do not rearm latch or broaden API permissions'],
        'AWS_calls': 0, 'AWS_changes': 0, 'setup_approved': False, 'stage_creation_approved': False}
    with (output / 'setup-review.json').open('x') as f:
        json.dump(review, f, indent=2); f.write('\n')
    return review


if __name__ == '__main__':
    print(json.dumps(prepare(ROOT / '.staging/stage-separated-core-review/fixed-stage-helper-review'), indent=2))
