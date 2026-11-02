#!/usr/bin/env python3
"""Prepare the evidence-backed owner access-stack KMS repair locally.

No network calls, IAM writes, deployment, imports, artifact upload, or mutation
of the original generator/reviewed templates. The existing AWS-managed key
policies supply service permissions; owner ceilings remain deny-only. New
runtime boundaries are owned by the access stack; five existing external
boundary policies and all unrelated runtime roles remain unchanged.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPEC = importlib.util.spec_from_file_location("delegated", HERE / "prepare-delegated-access.py")
D = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D)
ACCOUNT, REGION, STACK = D.ACCOUNT, D.REGION, D.STACK
DDB_KEY = f"arn:aws:kms:{REGION}:{ACCOUNT}:key/dca2dce4-ca2e-455f-998d-37c12dc7854e"
LAMBDA_KEY = f"arn:aws:kms:{REGION}:{ACCOUNT}:key/8ec7726d-0244-4ba5-8e44-3da18d2ca847"
KEYS = [DDB_KEY, LAMBDA_KEY]
CORE_SLUGS = tuple(D.SLUGS[:3])
CORE_FUNCTIONS = tuple(D.FUNCTIONS[:3])
CORE_ROLES = tuple(D.ROLES[:3])
NEW_BOUNDARY_IDS = tuple(name + "KmsBoundary" for name in D.LOGICAL[:3])
NEW_BOUNDARY_REFS = tuple({"Ref": logical} for logical in NEW_BOUNDARY_IDS)
# Backwards-compatible exported label: these are references, not guessed ARNs.
NEW_BOUNDARY_ARNS = NEW_BOUNDARY_REFS
NEW_BOUNDARY_NAMES = NEW_BOUNDARY_IDS
LAMBDA_GRANTEES = tuple(f"arn:aws:sts::{ACCOUNT}:assumed-role/{STACK}-{slug}-role/{STACK}-{slug}" for slug in CORE_SLUGS)
CFN_KMS_ACTIONS = ["kms:CreateGrant", "kms:Decrypt", "kms:DescribeKey", "kms:Encrypt"]
METADATA_ACTIONS = ["kms:DescribeKey", "kms:GetKeyPolicy", "kms:ListGrants"]
DDB_GRANT_OPERATIONS = ["DescribeKey", "GenerateDataKey", "Decrypt", "Encrypt", "ReEncryptFrom", "ReEncryptTo", "RetireGrant"]
LAMBDA_GRANT_OPERATIONS = ["Decrypt", "RetireGrant"]
LAMBDA_SERVICE = f"lambda.{REGION}.amazonaws.com"
DDB_SERVICE = f"dynamodb.{REGION}.amazonaws.com"
FUNCTION_CONTEXT = "kms:EncryptionContext:aws:lambda:FunctionArn"
TABLE_CONTEXT = "kms:EncryptionContext:aws:dynamodb:tableName"
SUBSCRIBER_CONTEXT = "kms:EncryptionContext:aws:dynamodb:subscriberId"
BASELINE_SHA = "461aa5e33daf04201633f4545b6a3f2bafe808617a4ec02c3dbc1c0ff99c7227"
ORIGINAL_BOUNDARY_SHA256 = {
    "health": "fcaa3bd46b00bae1378779cde1dda71689208ace0a0af9345dffb33333d2c3ae",
    "cases": "d06a4b4763fc8e906651cf78e6b204e8195cc31ddc8b6a9308409d80b3d97dab",
    "calculations": "64adacfd900e5cb83031f8892ff85a3a95b4be3e52ff31b673a533190213a9df",
}
ACCESS_STACK_ID = f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{D.ACCESS_STACK}/fb1a3b90-d1cc-11f1-b28f-06ffe5e86011"
MAX_POLICY_SIZE = 6044  # At least 100 characters below IAM's 6144-character cap.


def require(condition, message):
    if not condition:
        raise ValueError(message)


def actions(statement):
    value = statement["Action"]
    return value if isinstance(value, list) else [value]


def policy_size(policy):
    return len(json.dumps(policy, separators=(",", ":")))


def resolve_policy_for_size(value):
    """Conservative expansion for the unchanged stack and generated boundaries.

    IAM ManagedPolicyName permits at most 128 characters. Reserve that maximum
    for each new Ref instead of guessing CloudFormation-generated names.
    Amplify app IDs are bounded by 20 characters; the exact application remains
    unchanged. Unknown intrinsics fail instead of being silently discarded.
    """
    if isinstance(value, list):
        return [resolve_policy_for_size(item) for item in value]
    if not isinstance(value, dict):
        return value
    if value == {"Ref": "AWS::StackId"}:
        return ACCESS_STACK_ID
    if value.get("Ref") in NEW_BOUNDARY_IDS and set(value) == {"Ref"}:
        return f"arn:aws:iam::{ACCOUNT}:policy/" + "x" * 128
    if value == {"Fn::GetAtt": ["FrontendApp", "Arn"]}:
        return f"arn:aws:amplify:{REGION}:{ACCOUNT}:apps/" + "x" * 20
    if "Fn::Sub" in value:
        text, mapping = value["Fn::Sub"]
        for key, replacement in mapping.items():
            text = text.replace("${" + key + "}", resolve_policy_for_size(replacement))
        require("${" not in text, "Unresolved policy-size substitution")
        return text
    require(not any(key in value for key in ("Ref", "Fn::GetAtt")), "Unknown policy intrinsic")
    return {key: resolve_policy_for_size(item) for key, item in value.items()}


def expanded_policy_size(policy):
    return max(policy_size(policy), policy_size(resolve_policy_for_size(policy)))


def deny_mismatch(action, resource, key, expected, sid):
    return D.statement("Deny", action, resource, condition={"StringNotEquals": {key: expected}}, sid=sid)


def ceiling_kms_denies():
    """Independent Denys constrain even a future matching broad/key-policy Allow.

    Encryption-context conditions are deliberately absent from DescribeKey.
    CreateGrant evaluates supported grant-constraint/operations/principal context.
    Decrypt on the Lambda key supports its actual context-only policy path.
    """
    result = [
        D.statement("Deny", CFN_KMS_ACTIONS, not_resource=KEYS, sid="CeilingKmsOnlyTwoKeys"),
        deny_mismatch(CFN_KMS_ACTIONS, "*", "kms:CallerAccount", ACCOUNT, "CeilingKmsCaller"),
        D.statement("Deny", "kms:Encrypt", DDB_KEY, sid="CeilingKmsNoDdbEncrypt"),
        deny_mismatch(["kms:CreateGrant", "kms:Decrypt"], DDB_KEY, "kms:ViaService", DDB_SERVICE, "CeilingKmsDdbService"),
        deny_mismatch(["kms:CreateGrant", "kms:Decrypt"], DDB_KEY, TABLE_CONTEXT, STACK + "-cases", "CeilingKmsDdbTable"),
        deny_mismatch(["kms:CreateGrant", "kms:Decrypt"], DDB_KEY, SUBSCRIBER_CONTEXT, ACCOUNT, "CeilingKmsDdbSubscriber"),
        deny_mismatch(["kms:Encrypt", "kms:CreateGrant"], LAMBDA_KEY, "kms:ViaService", LAMBDA_SERVICE, "CeilingKmsLambdaService"),
        deny_mismatch(["kms:Encrypt", "kms:Decrypt", "kms:CreateGrant"], LAMBDA_KEY, FUNCTION_CONTEXT, list(CORE_FUNCTIONS), "CeilingKmsCoreFunctions"),
        D.statement("Deny", "kms:CreateGrant", KEYS,
                    condition={"BoolIfExists": {"kms:GrantIsForAWSResource": "false"}}, sid="CeilingKmsServiceGrants"),
        D.statement("Deny", "kms:CreateGrant", KEYS,
                    condition={"Null": {"kms:GrantOperations": "true"}}, sid="CeilingKmsGrantOpsPresent"),
    ]
    for label, key, operation_set, constraint in (
        ("Ddb", DDB_KEY, DDB_GRANT_OPERATIONS, "EncryptionContextSubset"),
        ("Lambda", LAMBDA_KEY, LAMBDA_GRANT_OPERATIONS, "EncryptionContextEquals"),
    ):
        result.extend([
            D.statement("Deny", "kms:CreateGrant", key,
                        condition={"ForAnyValue:StringNotEquals": {"kms:GrantOperations": operation_set}}, sid="CeilingKms" + label + "GrantOps"),
            deny_mismatch("kms:CreateGrant", key, "kms:GrantConstraintType", constraint, "CeilingKms" + label + "Constraint"),
        ])
    # Legacy service-valued GranteePrincipal/RetiringPrincipal event parameters
    # do not prove ARN-only IAM condition values. Do not invent such guards.
    # FAS ViaService/AWSResource/context/type/operation guards constrain DDB
    # service grants. Lambda's observed STS-session grantee is a valid ARN.
    result.append(deny_mismatch("kms:CreateGrant", LAMBDA_KEY, "kms:GranteePrincipal", list(LAMBDA_GRANTEES), "CeilingKmsLambdaGrantee"))
    # The permitted grantee and function lists must not permit cross-pairing.
    for slug, grantee, function in zip(CORE_SLUGS, LAMBDA_GRANTEES, CORE_FUNCTIONS):
        result.append(D.statement("Deny", "kms:CreateGrant", LAMBDA_KEY, condition={
            "StringEquals": {"kms:GranteePrincipal": grantee},
            "StringNotEquals": {FUNCTION_CONTEXT: function}}, sid="CeilingKmsPair" + slug.title()))
    return result


def decrypt_allows(functions, *, runtime_ddb=False):
    result = [D.statement("Allow", "kms:Decrypt", LAMBDA_KEY, condition={"StringEquals": {
        "aws:RequestedRegion": REGION, "kms:CallerAccount": ACCOUNT, FUNCTION_CONTEXT: functions}}, sid="OwnLambdaEnvironment")]
    if runtime_ddb:
        result.append(D.statement("Allow", "kms:Decrypt", DDB_KEY, condition={"StringEquals": {
            "aws:RequestedRegion": REGION, "kms:CallerAccount": ACCOUNT, "kms:ViaService": DDB_SERVICE,
            TABLE_CONTEXT: STACK + "-cases", SUBSCRIBER_CONTEXT: ACCOUNT}}, sid="OwnCasesTableKey"))
    return result


def decrypt_denies(functions, *, runtime_ddb=False, prefix="Runtime"):
    keys = [LAMBDA_KEY, DDB_KEY] if runtime_ddb else [LAMBDA_KEY]
    result = [
        D.statement("Deny", "kms:Decrypt", not_resource=keys, sid=prefix + "KmsKeys"),
        deny_mismatch("kms:Decrypt", "*", "aws:RequestedRegion", REGION, prefix + "KmsOhio"),
        deny_mismatch("kms:Decrypt", "*", "kms:CallerAccount", ACCOUNT, prefix + "KmsCaller"),
        deny_mismatch("kms:Decrypt", LAMBDA_KEY, FUNCTION_CONTEXT, functions, prefix + "KmsFunction"),
    ]
    if runtime_ddb:
        result.extend([
            deny_mismatch("kms:Decrypt", DDB_KEY, "kms:ViaService", DDB_SERVICE, prefix + "KmsDdbService"),
            deny_mismatch("kms:Decrypt", DDB_KEY, TABLE_CONTEXT, STACK + "-cases", prefix + "KmsDdbTable"),
            deny_mismatch("kms:Decrypt", DDB_KEY, SUBSCRIBER_CONTEXT, ACCOUNT, prefix + "KmsDdbSubscriber"),
        ])
    return result


def runtime_boundary(index, original):
    require(index in range(3), "Only three core runtime boundaries may change")
    result = copy.deepcopy(original)
    not_actions = [entry for entry in result["Statement"] if entry.get("Sid") == "NoOtherActions"]
    require(len(not_actions) == 1 and not_actions[0]["Effect"] == "Deny", "Unexpected runtime boundary shape")
    not_actions[0]["NotAction"] = sorted(set(not_actions[0]["NotAction"] + ["kms:Decrypt"]))
    result["Statement"].extend(decrypt_allows(CORE_FUNCTIONS[index], runtime_ddb=index in (1, 2)))
    result["Statement"].extend(decrypt_denies(CORE_FUNCTIONS[index], runtime_ddb=index in (1, 2)))
    require(policy_size(result) <= 6144, "Runtime boundary exceeds IAM managed-policy limit")
    return result


def deployer_kms_allow_statements():
    return [D.statement("Allow", METADATA_ACTIONS, KEYS, condition=D.OHIO, sid="InspectTwoDependencyKeys"),
            *decrypt_allows(list(CORE_FUNCTIONS))]


def deployer_kms_deny_statements():
    # DeployerNoUnlistedActions independently keeps every unlisted KMS verb denied.
    return [D.statement("Deny", METADATA_ACTIONS + ["kms:Decrypt"], not_resource=KEYS, sid="DeployerKmsTwoKeys"),
            *decrypt_denies(list(CORE_FUNCTIONS), prefix="Deployer")]


def append_to_shards(shards, additions, order):
    """Keep every original shard/statement; place only new statements in free space."""
    for entry in sorted(additions, key=policy_size, reverse=True):
        for index in order:
            candidate = {**shards[index], "Statement": shards[index]["Statement"] + [entry]}
            if expanded_policy_size(candidate) <= MAX_POLICY_SIZE:
                shards[index]["Statement"].append(copy.deepcopy(entry))
                break
        else:
            raise ValueError("New scoped statements do not fit existing managed policy shards")


def statement_in(shards, predicate):
    matches = [entry for policy in shards for entry in policy["Statement"] if predicate(entry)]
    require(len(matches) == 1, "Expected exactly one policy statement for targeted patch")
    return matches[0]


def _repair_unchecked(baseline):
    require(baseline == D.access_template(), "Baseline differs from original reviewed delegation architecture")
    result = copy.deepcopy(baseline)
    resources = result["Resources"]
    ceilings = [resources[f"ExecutionCeiling{i}"]["Properties"]["PolicyDocument"] for i in range(1, 4)]
    no_unlisted = statement_in(ceilings, lambda entry: entry.get("Sid") == "CeilingNoUnlistedActions")
    no_unlisted["NotAction"] = sorted(set(no_unlisted["NotAction"] + CFN_KMS_ACTIONS))
    append_to_shards(ceilings, ceiling_kms_denies(), [1, 2, 0])
    # Install the restrictive shards before enabling the four KMS exceptions.
    # Reverse rollback order restores the original unlisted-action denial first.
    resources["ExecutionCeiling1"]["DependsOn"] = ["ExecutionCeiling2", "ExecutionCeiling3"]

    for index, logical in enumerate(D.LOGICAL[:3]):
        original = json.loads((HERE / "generated" / (STACK + "-" + CORE_SLUGS[index] + "-boundary.json")).read_text())
        boundary = runtime_boundary(index, original)
        resources[NEW_BOUNDARY_IDS[index]] = {
            "Type": "AWS::IAM::ManagedPolicy", "DeletionPolicy": "Retain", "UpdateReplacePolicy": "Retain",
            "Properties": {"PolicyDocument": boundary}}
        role = resources[logical + "Role"]["Properties"]
        role["PermissionsBoundary"] = {"Ref": NEW_BOUNDARY_IDS[index]}
        role["Policies"][0]["PolicyDocument"] = D.doc([copy.deepcopy(entry) for entry in boundary["Statement"] if entry["Effect"] == "Allow"])

    deployer = [resources[f"DeployerPolicy{i}"]["Properties"]["PolicyDocument"] for i in range(1, 5)]
    policy_reads = statement_in(deployer, lambda entry: entry["Effect"] == "Allow" and set(actions(entry)) == {"iam:GetPolicy", "iam:GetPolicyVersion", "iam:ListPolicyVersions"})
    # Separate Allow leaves the original shard statement unchanged and reserves
    # maximum generated-name expansion without overflowing its policy quota.
    new_boundary_read = D.statement("Allow", actions(policy_reads), list(NEW_BOUNDARY_REFS), sid="ReadCoreKmsBoundaries")
    access_read = statement_in(deployer, lambda entry: entry["Effect"] == "Allow" and entry.get("Resource") == {"Ref": "AWS::StackId"})
    require(actions(access_read) == ["cloudformation:DescribeStacks"], "Unexpected self access-stack read")
    access_read["Action"] = ["cloudformation:DescribeStacks", "cloudformation:GetTemplate"]
    deny_unlisted = statement_in(deployer, lambda entry: entry.get("Sid") == "DeployerNoUnlistedActions")
    deny_unlisted["NotAction"] = sorted(set(deny_unlisted["NotAction"] + METADATA_ACTIONS + ["kms:Decrypt"]))
    append_to_shards(deployer, deployer_kms_allow_statements() + deployer_kms_deny_statements() + [new_boundary_read], [3, 2, 0, 1])
    resources["DeployerPolicy4"]["DependsOn"] = ["DeployerPolicy3"]
    return result


def repair_template(baseline):
    """Pure local transformation. This does not make a CloudFormation request."""
    candidate = _repair_unchecked(baseline)
    validate_candidate(baseline, candidate)
    return candidate


def validate_candidate(baseline, candidate):
    # Exact transformation validation catches arbitrary additional Allow,
    # deleted protection, trust/path/role-policy change or unknown nested field.
    require(candidate == _repair_unchecked(baseline), "Candidate differs from the complete permitted transformation")
    original = baseline["Resources"]
    resources = candidate["Resources"]
    require(set(resources) - set(original) == set(NEW_BOUNDARY_IDS), "Unexpected new resources")
    require(not (set(original) - set(resources)), "Existing resource removal is forbidden")
    allowed = {"ExecutionCeiling1", "ExecutionCeiling2", "ExecutionCeiling3", "DeployerPolicy1", "DeployerPolicy2", "DeployerPolicy3", "DeployerPolicy4"}
    allowed.update(logical + "Role" for logical in D.LOGICAL[:3])
    changed = [name for name in original if original[name] != resources[name]]
    require(set(changed) <= allowed, "Unrelated access-stack resource changed")
    require({k: v for k, v in baseline.items() if k != "Resources"} == {k: v for k, v in candidate.items() if k != "Resources"}, "Unrelated template-level field changed")
    sizes, expanded_sizes = {}, {}
    for name, resource in resources.items():
        if resource["Type"] == "AWS::IAM::ManagedPolicy":
            size = policy_size(resource["Properties"]["PolicyDocument"])
            expanded = expanded_policy_size(resource["Properties"]["PolicyDocument"])
            require(expanded <= MAX_POLICY_SIZE, "Managed policy quota/headroom exceeded: " + name)
            sizes[name] = size
            expanded_sizes[name] = expanded
    for index in range(1, 4):
        require(all(s["Effect"] == "Deny" for s in resources[f"ExecutionCeiling{index}"]["Properties"]["PolicyDocument"]["Statement"]), "Owner ceiling must remain deny-only")
    for name in original:
        if name.startswith("ExecutionCeiling") or name.startswith("DeployerPolicy"):
            old = original[name]["Properties"]["PolicyDocument"]["Statement"]
            new = resources[name]["Properties"]["PolicyDocument"]["Statement"]
            require(len(new) >= len(old), "Original owner policy statement removed")
    for logical in D.LOGICAL[:3]:
        before = copy.deepcopy(original[logical + "Role"])
        after = copy.deepcopy(resources[logical + "Role"])
        for value in (before, after):
            value["Properties"].pop("PermissionsBoundary")
            value["Properties"].pop("Policies")
        require(before == after, "Runtime role trust/name/path/tags/retention changed")
    return {"status": "LOCAL_CANDIDATE_NOT_APPLIED", "new_boundary_policies": "Three CloudFormation-generated names; reference ARNs only",
            "additions": list(NEW_BOUNDARY_IDS), "modified_resources": changed, "removals": [],
            "resource_count": len(resources), "managed_policy_compact_sizes": sizes,
            "managed_policy_maximum_expanded_sizes": expanded_sizes,
            "minimum_policy_quota_headroom": min(6144 - size for size in expanded_sizes.values()),
            "policy_update_order": {"ExecutionCeiling1": ["ExecutionCeiling2", "ExecutionCeiling3"],
                                    "DeployerPolicy4": ["DeployerPolicy3"]},
            "post_update_gate": "IAM is eventually consistent. Verify every live default policy, boundary reference and effective permission after access-stack UPDATE_COMPLETE before any separately approved application deployment.",
            "CFN_KMS_exception_actions": CFN_KMS_ACTIONS, "runtime_KMS_actions": ["kms:Decrypt"],
            "original_five_external_boundaries_edited": False, "core_application_template_changed": False,
            "live_key_policies_changed": False, "AWS_operations": 0}


def load_verified_evidence(path):
    evidence = json.loads(Path(path).read_text())
    require(evidence["identity"]["Arn"] == D.DEVELOPER and evidence["identity"]["Account"] == ACCOUNT, "Evidence identity differs")
    require(evidence["region"] == REGION and not evidence.get("missing_reads"), "Incomplete or foreign-region key evidence")
    baseline = evidence["access_stack_template"]["TemplateBody"]
    if isinstance(baseline, str):
        baseline = json.loads(baseline)
    require(baseline == D.access_template(), "Actual access-stack template differs from reviewed baseline")
    for label, arn in (("dynamodb", DDB_KEY), ("lambda", LAMBDA_KEY)):
        key = evidence["keys"][label]
        meta = key["metadata"]["KeyMetadata"]
        require(meta["Arn"] == arn and meta["AWSAccountId"] == ACCOUNT and meta["KeyManager"] == "AWS"
                and meta["KeyState"] == "Enabled" and meta["Enabled"] is True and meta["KeySpec"] == "SYMMETRIC_DEFAULT"
                and meta["KeyUsage"] == "ENCRYPT_DECRYPT" and meta["Origin"] == "AWS_KMS" and meta["MultiRegion"] is False,
                "Unexpected actual KMS key configuration")
        require(all(s["Effect"] == "Allow" for s in key["policy"]["Policy"]["Statement"]), "Unexpected managed key Deny")
    baseline_file = ROOT / ".staging/delegated-access-final-review/access-stack.json"
    require(hashlib.sha256(baseline_file.read_bytes()).hexdigest() == BASELINE_SHA, "Original reviewed template bytes changed")
    # The access stack embeds only runtime Allow statements. Pin the complete
    # original external boundary documents too, including all their Denys.
    boundary_hashes = {}
    for slug in CORE_SLUGS:
        original = json.loads((HERE / "generated" / (STACK + "-" + slug + "-boundary.json")).read_text())
        digest = D.canonical_sha(original)
        require(digest == ORIGINAL_BOUNDARY_SHA256[slug], "Original external runtime boundary source changed: " + slug)
        boundary_hashes[slug] = digest
    return baseline, {"evidence_file": str(Path(path).resolve()), "evidence_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                      "baseline_template_exact_match": True, "keys_exact_enabled_AWS_managed": True,
                      "original_core_boundary_canonical_SHA256": boundary_hashes}


def prepare(evidence_path, output):
    baseline, evidence_review = load_verified_evidence(evidence_path)
    candidate = repair_template(baseline)
    review = {**validate_candidate(baseline, candidate), **evidence_review,
              "status": "LOCAL_CANDIDATE_AWAITING_INDEPENDENT_POLICY_AND_CLOUDFORMATION_REVIEW",
              "requires_owner_access_stack_update_approval": True, "deployment_retry_authorized": False}
    output = Path(output)
    require(not output.exists(), "Refusing to overwrite an existing repair review")
    output.mkdir(parents=True)
    for name, value in (("access-stack-kms-repair.json", candidate), ("review.json", review)):
        (output / name).write_text(json.dumps(value, indent=2) + "\n")
    for name, resource in candidate["Resources"].items():
        if resource["Type"] == "AWS::IAM::ManagedPolicy":
            (output / (name + ".json")).write_text(json.dumps(resource["Properties"]["PolicyDocument"], indent=2) + "\n")
    return review


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / ".staging/kms-repair-review/repair-candidate")
    args = parser.parse_args()
    print(json.dumps(prepare(args.evidence, args.output), indent=2))
