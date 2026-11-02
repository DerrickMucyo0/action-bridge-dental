#!/usr/bin/env python3
"""Prepare the stage-separated core locally; never calls AWS or changes IAM.

This post-processes the reviewed, already expanded delegated core. Injecting the
condition before SAM expansion would lose it in the staging branch selector.
Historical approved templates and Lambda ZIPs remain unchanged.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT / '.staging/delegated-access-final-review/core-delegated.json'
FROZEN_SHA = '0dd71fd938e8da07d80d136d501118bf91278289aca6866b5f6393eaabbf7cf9'
PREVIOUS_REQUEST = ROOT / '.staging/api-stage-ceiling-repair/post-legacy-core-preflight/fresh-core-update-change-set-request.json'
PREVIOUS_REQUEST_SHA = '31ada8670dfc87a2baaf7589689cf851e9939d63b6354f2556341297164f6d05'
PARAMETER = 'CreateHttpApiStage'
CONDITION = 'ManageHttpApiStage'
API = 'l52iwors8c'
STACK_ID = 'arn:aws:cloudformation:us-east-2:631367363628:stack/actionbridge-dental-staging/474e7340-d02f-11f1-9274-02b90931d9ff'
EXECUTOR = 'arn:aws:iam::631367363628:role/actionbridge-dental-staging-cfn'


def require(value, message):
    if not value:
        raise ValueError(message)


def resource_references(node):
    if isinstance(node, list):
        return set().union(*(resource_references(v) for v in node))
    if not isinstance(node, dict):
        return set()
    result = set()
    if 'Ref' in node:
        result.add(node['Ref'])
    if 'Fn::GetAtt' in node:
        value = node['Fn::GetAtt']
        result.add(value.split('.', 1)[0] if isinstance(value, str) else value[0])
    if 'DependsOn' in node:
        value = node['DependsOn']
        result.update([value] if isinstance(value, str) else value)
    if 'Fn::Sub' in node:
        value = node['Fn::Sub']
        expression, variables = (value, {}) if isinstance(value, str) else value
        result.update(token.split('.', 1)[0] for token in re.findall(r'\$\{([^}]+)\}', expression)
                      if token not in variables and not token.startswith('!'))
    for key, value in node.items():
        if key not in {'Ref', 'Fn::GetAtt', 'Fn::Sub', 'DependsOn'}:
            result.update(resource_references(value))
    if isinstance(node.get('Fn::Sub'), list):
        result.update(resource_references(node['Fn::Sub'][1]))
    return result


def conditional_core(core):
    require(len(core['Resources']) == 41 and not core.get('Transform'), 'Use the reviewed expanded delegated core')
    require(PARAMETER not in core['Parameters'] and CONDITION not in core.get('Conditions', {}), 'Stage selector already exists')
    resources = core['Resources']
    require(not any(r['Type'].startswith('AWS::IAM::') or r['Type'] in {
        'AWS::Lambda::EventSourceMapping', 'AWS::SQS::Queue', 'AWS::S3::Bucket'} for r in resources.values()), 'Deferred or IAM resource found')
    api = resources['HttpApi']['Properties']
    require(api['ProtocolType'] == 'HTTP' and api['DisableExecuteApiEndpoint'] is True and
            not {'Body', 'BodyS3Location', 'Target', 'RouteKey'} & api.keys(),
            'Existing HTTP API protections changed')
    stage = resources['HttpApiStage']
    require(stage['Type'] == 'AWS::ApiGatewayV2::Stage' and stage['Properties']['ApiId'] == {'Ref': 'HttpApi'} and
            stage['Properties']['StageName'] == {'Ref': 'AppEnv'} and stage['Properties']['AutoDeploy'] is True and
            'Condition' not in stage, 'Unexpected reviewed stage shape')
    rest = copy.deepcopy(core)
    del rest['Resources']['HttpApiStage']
    require('HttpApiStage' not in resource_references(rest), 'A retained resource/output depends on the excluded stage')
    routes = {k for k, r in resources.items() if r['Type'] == 'AWS::ApiGatewayV2::Route'}
    require(len(routes) == 14 and set(stage['DependsOn']) == routes, 'Stage route ordering differs')
    result = copy.deepcopy(core)
    result['Parameters'][PARAMETER] = {
        'Type': 'String', 'Default': 'false', 'AllowedValues': ['false', 'true'],
        'Description': 'Initial deployment must use false. True requires a separately reviewed stage ownership/tagging plan; it does not adopt an external stage.',
    }
    result.setdefault('Conditions', {})[CONDITION] = {'Fn::Equals': [{'Ref': PARAMETER}, 'true']}
    result['Resources']['HttpApiStage']['Condition'] = CONDITION
    result['Resources']['HttpApiStage']['Properties']['AutoDeploy'] = False
    # The dormant true branch preserves existing tags. Removing this SAM tag
    # would not disable the provider's automatic CloudFormation system tags.
    result['Outputs']['ApiBaseUrl']['Condition'] = CONDITION
    result['Outputs']['ApiBaseUrl']['Description'] = 'Candidate stage URL only; the execute-api endpoint stays disabled. Omitted when the stage is external or absent.'
    result['Outputs']['HttpApiStageManaged'] = {'Value': {'Fn::If': [CONDITION, 'true', 'false']}}
    result['Metadata']['StageSeparation'] = {
        'InitialCloudFormationStage': False, 'AutoDeploy': False,
        'ExternalStageRequiresSeparateApproval': True, 'UntaggedStageAuthorizationNotYetTested': True,
    }
    result['Description'] = 'ActionBridge Dental staging core configuration; optional stage excluded by default, endpoint disabled, no automatic deployment.'
    require(all(result['Resources'][k] == v for k, v in resources.items() if k != 'HttpApiStage'), 'A non-stage resource changed')
    return result


def initial_resources(template, value='false'):
    require(value in ('false', 'true'), 'Stage selector must be a string boolean')
    require(template['Conditions'][CONDITION] == {'Fn::Equals': [{'Ref': PARAMETER}, 'true']}, 'Unknown condition semantics')
    active = {}
    for name, resource in template['Resources'].items():
        condition = resource.get('Condition')
        require(condition in (None, CONDITION), 'Do not silently discard an unfamiliar condition')
        if condition is None or value == 'true':
            active[name] = resource
    return active


def untagged_stage_request():
    # Deliberately OMIT Tags (including an empty Tags map), DeploymentId,
    # variables and other optional settings. This is a supported request shape,
    # not proof that the live tag-dependent authorization check is absent.
    return {'ApiId': API, 'StageName': 'staging', 'AutoDeploy': False,
            'DefaultRouteSettings': {'ThrottlingBurstLimit': 20, 'ThrottlingRateLimit': 10}}


def check_external_stage(api, stage):
    """Compare a readback bound to get-stage --api-id l52iwors8c.

    GetStage does not echo ApiId; a future live caller must record and constrain
    that exact request target rather than infer ownership from StageName alone.
    """
    require(api['ApiId'] == API and api['ProtocolType'] == 'HTTP' and api['DisableExecuteApiEndpoint'] is True, 'API identity or endpoint protection changed')
    require(stage['StageName'] == 'staging' and stage['AutoDeploy'] is False and not stage.get('DeploymentId') and not stage.get('Tags'),
            'The external stage must be untagged, nonautomatic and unbound to a deployment')
    route = stage['DefaultRouteSettings']
    expected = untagged_stage_request()['DefaultRouteSettings']
    require(all(route.get(k) == v for k, v in expected.items()) and
            set(route) <= set(expected) | {'DetailedMetricsEnabled', 'DataTraceEnabled', 'LoggingLevel'} and
            route.get('DetailedMetricsEnabled', False) is False and route.get('DataTraceEnabled', False) is False and
            route.get('LoggingLevel', 'OFF') == 'OFF' and not stage.get('RouteSettings') and
            not stage.get('StageVariables') and not stage.get('AccessLogSettings'), 'Unexpected stage configuration')
    return True


def initial_request(previous, template, name):
    require(previous['StackName'] == STACK_ID and previous['RoleARN'] == EXECUTOR and previous['ChangeSetType'] == 'UPDATE', 'Wrong target or role')
    require(previous['ImportExistingResources'] is False and previous['IncludeNestedStacks'] is False and
            not any(k in previous for k in ('Capabilities', 'ResourcesToImport', 'TemplateURL', 'UsePreviousTemplate')), 'Unexpected import or alternate template')
    require(not any(p['ParameterKey'] == PARAMETER for p in previous['Parameters']), 'Duplicate stage parameter')
    result = copy.deepcopy(previous)
    result.update(ChangeSetName=name, Description='Review only: staging core with CloudFormation stage excluded; no traffic or deployment activation.',
                  ClientToken=name, TemplateBody=json.dumps(template, separators=(',', ':')))
    result['Parameters'].append({'ParameterKey': PARAMETER, 'ParameterValue': 'false'})
    require(set(result['ResourceTypes']) == {r['Type'] for r in template['Resources'].values()}, 'Retain the exact nine declared resource types')
    require(len(result['TemplateBody'].encode()) <= 51200, 'Template exceeds inline limit')
    return result


def prepare(output):
    require(hashlib.sha256(FROZEN.read_bytes()).hexdigest() == FROZEN_SHA, 'Historical core template changed')
    require(hashlib.sha256(PREVIOUS_REQUEST.read_bytes()).hexdigest() == PREVIOUS_REQUEST_SHA, 'Historical request changed')
    require(not any((output / n).exists() for n in ('core-conditional-stage.json', 'core-update-request.NOT-SUBMITTED.json', 'create-untagged-stage-request.NOT-SUBMITTED.json', 'local-review.json')), 'Refuse to overwrite prepared artifacts')
    core = json.loads(FROZEN.read_text()); previous = json.loads(PREVIOUS_REQUEST.read_text())
    require(json.loads(previous['TemplateBody']) == core, 'Historical inputs differ')
    candidate = conditional_core(core)
    name = 'actionbridge-staging-core-stage-separated-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    request = initial_request(previous, candidate, name)
    active = initial_resources(candidate)
    output.mkdir(parents=True, exist_ok=True)
    artifacts = {'core-conditional-stage.json': candidate, 'core-update-request.NOT-SUBMITTED.json': request,
                 'create-untagged-stage-request.NOT-SUBMITTED.json': untagged_stage_request()}
    for filename, data in artifacts.items():
        with (output / filename).open('x') as f:
            json.dump(data, f, indent=2); f.write('\n')
        if filename == 'core-update-request.NOT-SUBMITTED.json':
            (output / filename).chmod(0o600)
    review = {'status': 'LOCAL_ALTERNATIVE_PREPARED_NOT_AUTHORIZED_FOR_EXECUTION', 'source_core_sha256': FROZEN_SHA,
              'all_non_stage_resources_exactly_unchanged': True, 'declared_resources': 41, 'declared_resource_types': 9,
              'initial_active_resources': len(active), 'initial_active_resource_types': len({r['Type'] for r in active.values()}),
              'expected_initial_additions': 39, 'expected_HttpApi_modifications': 1, 'expected_removals': 0,
              'HttpApi_replacement_expected': False, 'existing_api': API, 'endpoint_disabled': True,
              'AutoDeploy': False, 'stage_inbound_dependencies': 0, 'routes': 14, 'JWT_routes': 13,
              'existing_artifacts_reused': 3, 'stage_request_has_Tags': False, 'stage_request_has_DeploymentId': False,
              'untagged_request_authorization_verified_live': False, 'deployer_can_create_external_stage': False,
              'owner_stage_probe_must_precede_core_execution_recommendation': True,
              'import_supported_but_not_a_proven_tagging_bypass': True, 'unproven_provider_metadata_getters_unchanged': 11,
              'AWS_calls': 0, 'cloud_changes': 0, 'creation_authorized': False, 'execution_authorized': False,
              'artifact_sha256': {n: hashlib.sha256((output / n).read_bytes()).hexdigest() for n in artifacts}}
    with (output / 'local-review.json').open('x') as f:
        json.dump(review, f, indent=2); f.write('\n')
    return review


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / '.staging/stage-separated-core-review')
    args = parser.parse_args()
    print(json.dumps(prepare(args.output_dir), indent=2))
