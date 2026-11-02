#!/usr/bin/env python3
"""Prepare the evidence-bound API/stage tagging repair, entirely locally.

The service reports a tagging identifier absent from its recognized IAM catalog.
Do not invent an Allow for that identifier. The complete bundle also covers the
raw API-root tag endpoint subsequently observed in the owner's CloudTrail event.
This proves explicit-Deny removal and scope, not service-side write success.
"""
import argparse
import copy
import difflib
from fnmatch import fnmatchcase
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

ACCOUNT, REGION, STACK = "631367363628", "us-east-2", "actionbridge-dental-staging"
API = f"arn:aws:apigateway:{REGION}::/apis/l52iwors8c"
STAGE_PATHS = [API + "/stages", API + "/stages/staging",
               f"arn:aws:apigateway:{REGION}::/tags/arn%3Aaws%3Aapigateway%3Aus-east-2%3A%3A%2Fapis%2Fl52iwors8c%2Fstages%2Fstaging"]
TAG_PREFIX = f"arn:aws:apigateway:{REGION}::/tags/"
TAG_PATHS = [STAGE_PATHS[2], TAG_PREFIX + STAGE_PATHS[1], TAG_PREFIX + quote(API, safe=""), TAG_PREFIX + API]
COMPLETE_PATHS = STAGE_PATHS[:2] + TAG_PATHS
BASELINE_SHA = "20acb3d8c843472cd8e58999da15d3e3cc2f3c61c5dcc913f0eceecdbc29dc24"
PREFIX = f"arn:aws:iam::{ACCOUNT}:policy/{STACK}-"
POLICY_PINS = {
    "cfn-identity-01": "65e4ac6a87ea0b1a1bf8b44f93c9836a894c988608119268b6bc7709d15e8d5b",
    "cfn-identity-02": "9b8c407018993fe2b02cff4304faa112214d34b6246afda7027c5e8818895c5f",
    "cfn-identity-03": "027627a200647da9ede5b55a5a1a4793d3ac9aff9742262f1451dd5dbc0e4e37",
    "cfn-guardrails-01": "8815922e7b6376f1b063eaa0d613a6923f95e6e40ccdf5f376961dceb996efbd",
    "cfn-guardrails-02": "1332e1cee527d366903730d258558bbd2a2aecd3cf60e206b685d23b610efdba",
    "owner-ceiling-1": "34128be1957ee64a973274bdfca98c28f41fc3007f34fb5519730489e78bd7f6",
    "owner-ceiling-2": "9fec3038ed3b9c12edf2fe2c156f4601e7ba14472d6ebac44db6d18843b9045a",
    "owner-ceiling-3": "341f93ae3af0f167df9979bce3e5b86faec09ca5a881558cd075b72f32b43dbe",
}
CAVEAT = (
    "Literal TagResource/UntagResource and Tag*/Untag* are not recognized IAM actions in AWS validation; "
    "IAM simulation rejects the named diagnostic action. Literal diagnostic strings are evaluated locally only "
    "to prove removal of the reported explicit Deny; their resulting implicitDeny is NOT labeled an Allow. "
    "Recognized HTTP verbs are evaluated separately under the official service operation mapping. "
    "No read-only test proves API Gateway's internal dependent-action enforcement or a successful deployment."
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    def invalid(_):
        raise ValueError("Non-JSON constant")
    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def validate_baseline(baseline, policies):
    require(canonical_sha(baseline) == BASELINE_SHA, "Unexpected access-stack baseline; KMS/runtime/security changes are forbidden")
    require(len(baseline["Resources"]) == 17, "Expected complete seventeen-resource KMS-repaired stack")
    require(set(policies) == {PREFIX + suffix for suffix in POLICY_PINS}, "Exactly eight actual executor policies are required")
    for suffix, pin in POLICY_PINS.items():
        require(canonical_sha(policies[PREFIX + suffix]) == pin, "Actual policy differs from reviewed default: " + suffix)
    for i in (1, 2, 3):
        resource = baseline["Resources"][f"ExecutionCeiling{i}"]
        require(resource["Type"] == "AWS::IAM::ManagedPolicy", "Unexpected owner ceiling type")
        require(resource["Properties"]["PolicyDocument"] == policies[PREFIX + f"owner-ceiling-{i}"], "Template/actual ceiling mismatch")
    statement = baseline["Resources"]["ExecutionCeiling1"]["Properties"]["PolicyDocument"]["Statement"][0]
    require(statement.get("Sid") == "CeilingNoUnlistedActions" and statement.get("Effect") == "Deny"
            and statement.get("Resource") == "*" and set(statement) == {"Sid", "Effect", "NotAction", "Resource"},
            "Unexpected target statement shape")


def repair_template(baseline, policies):
    validate_baseline(baseline, policies)
    candidate = copy.deepcopy(baseline)
    statement = candidate["Resources"]["ExecutionCeiling1"]["Properties"]["PolicyDocument"]["Statement"][0]
    del statement["Resource"]
    statement["NotResource"] = list(STAGE_PATHS)
    validate_candidate(baseline, candidate)
    return candidate


def validate_candidate(baseline, candidate):
    require(canonical_sha(baseline) == BASELINE_SHA, "Unexpected baseline")
    expected = copy.deepcopy(baseline)
    statement = expected["Resources"]["ExecutionCeiling1"]["Properties"]["PolicyDocument"]["Statement"][0]
    del statement["Resource"]
    statement["NotResource"] = list(STAGE_PATHS)
    require(candidate == expected, "Candidate differs from the sole permitted transformation")
    require(set(candidate["Resources"]) == set(baseline["Resources"]), "Unexpected addition/removal")
    require([key for key in baseline["Resources"] if baseline["Resources"][key] != candidate["Resources"][key]]
            == ["ExecutionCeiling1"], "Unexpected resource changes")
    policy = candidate["Resources"]["ExecutionCeiling1"]["Properties"]["PolicyDocument"]
    require(len(json.dumps(policy, separators=(",", ":"))) <= 6144, "Managed policy exceeds quota")
    return True


def values(value):
    return value if isinstance(value, list) else [value]


def api_decision(documents, action, resource, context):
    """Bounded API-only identity math, independently cross-checked in tests.

    Pinned full inputs prevent unknown fields from being silently discarded.
    Unknown *applicable* condition operators fail; unrelated KMS conditions are
    never interpreted as API permissions. No action-name recognition is claimed.
    """
    require(action.startswith("apigateway:"), "Only API Gateway contexts are modeled")
    allowed = False
    context = {key.lower(): value for key, value in context.items()}
    for document in documents:
        for statement in document["Statement"]:
            akey = "Action" if "Action" in statement else "NotAction"
            matched = any(fnmatchcase(action.lower(), value.lower()) for value in values(statement[akey]))
            if matched == (akey == "NotAction"):
                continue
            rkey = "Resource" if "Resource" in statement else "NotResource"
            matched = any(fnmatchcase(resource, value) for value in values(statement[rkey]))
            if matched == (rkey == "NotResource"):
                continue
            matches = True
            for op, clauses in statement.get("Condition", {}).items():
                require(op in ("StringEquals", "StringNotEquals"), "Unsupported applicable API condition")
                for key, wanted in clauses.items():
                    match = context.get(key.lower()) in values(wanted)
                    matches = matches and (not match if op == "StringNotEquals" else match)
            if not matches:
                continue
            if statement["Effect"] == "Deny":
                return "explicitDeny"
            require(statement["Effect"] == "Allow", "Unexpected effect")
            allowed = True
    return "allowed" if allowed else "implicitDeny"


def review_matrix(policies, candidate):
    before = [policies[PREFIX + suffix] for suffix in POLICY_PINS]
    after = copy.deepcopy(before)
    after[list(POLICY_PINS).index("owner-ceiling-1")] = candidate["Resources"]["ExecutionCeiling1"]["Properties"]["PolicyDocument"]
    broad = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]}
    ohio = {"aws:RequestedRegion": REGION}
    checks = []
    def add(label, action, resource, old, new, context=None, adversarial=False):
        context = ohio if context is None else context
        inputs = [broad] if adversarial else []
        b, a = (api_decision(documents + inputs, action, resource, context) for documents in (before, after))
        row = {"label": label, "action": action, "resource": resource, "context": context,
               "adversarial_simulation_only_Allow": adversarial, "before": b, "after": a,
               "expected_before": old, "expected_after": new, "passed": b == old and a == new}
        require(row["passed"], "Permission regression: " + str(row))
        checks.append(row)
    for resource in STAGE_PATHS:
        for verb in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            add("recognized_HTTP_lifecycle", "apigateway:" + verb, resource, "allowed", "allowed")
        for alias in ("TagResource", "UntagResource"):
            add("diagnostic_identifier_explicit_Deny_removed_NOT_Allow", "apigateway:" + alias,
                resource, "explicitDeny", "implicitDeny")
        for context in ({}, {"aws:RequestedRegion": "us-west-2"}):
            for name in ("POST", "TagResource", "UntagResource"):
                add("region_guard_preserved", "apigateway:" + name, resource, "explicitDeny", "explicitDeny", context, True)
    bad = [API, API + "/cors", API + "/stages/production", API + "/stages/staging-evil",
           API.replace("l52iwors8c", "unrelated") + "/stages", STAGE_PATHS[2].replace("l52iwors8c", "unrelated"),
           STAGE_PATHS[2].replace("us-east-2", "us-west-2"), API + "/deployments"]
    for resource in bad:
        for name in ("POST", "PUT", "PATCH", "DELETE", "TagResource", "UntagResource"):
            expected = "allowed" if (resource == API and name in ("POST", "PUT", "PATCH")) or (resource == API + "/cors" and name == "DELETE") else "explicitDeny"
            add("unchanged_scope_adversarial_Allow", "apigateway:" + name, resource, expected, expected, adversarial=True)
    for resource in (API + "/routes", API + "/routes/r1", API + "/integrations/i1", API + "/authorizers/a1"):
        for verb in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            add("other_configured_API_lifecycle_unchanged", "apigateway:" + verb, resource, "allowed", "allowed")
    return checks


def prepare(baseline_path, policy_path, output):
    baseline, policies = decode(Path(baseline_path).read_text()), decode(Path(policy_path).read_text())
    candidate = repair_template(baseline, policies)
    matrix = review_matrix(policies, candidate)
    output = Path(output)
    require(not output.exists(), "Output must be a fresh directory; nothing overwritten")
    output.mkdir(parents=True)
    policy = candidate["Resources"]["ExecutionCeiling1"]["Properties"]["PolicyDocument"]
    original_policy = baseline["Resources"]["ExecutionCeiling1"]["Properties"]["PolicyDocument"]
    basepath = "/Resources/ExecutionCeiling1/Properties/PolicyDocument/Statement/0/"
    patch = [{"op": "test", "path": basepath + "Resource", "value": "*"},
             {"op": "remove", "path": basepath + "Resource"},
             {"op": "add", "path": basepath + "NotResource", "value": STAGE_PATHS}]
    def write(name, value):
        (output / name).write_text(json.dumps(value, indent=2) + "\n")
    write("access-stack-stage-tagging-repair.json", candidate)
    write("owner-ceiling-1.json", policy)
    write("exact-json-patch.json", patch)
    for name, old, new in (("access-stack.diff", baseline, candidate), ("owner-ceiling-1.diff", original_policy, policy)):
        (output / name).write_text("".join(difflib.unified_diff((json.dumps(old, indent=2) + "\n").splitlines(True),
                                   (json.dumps(new, indent=2) + "\n").splitlines(True), fromfile="approved-before", tofile="proposed-after")))
    review = {"status": "PASS_LOCAL_SCOPE_AND_EXPLICIT_DENY_REMOVAL_NOT_LIVE_ENFORCEMENT", "caveat": CAVEAT,
              "baseline_canonical_sha256": canonical_sha(baseline), "candidate_canonical_sha256": canonical_sha(candidate),
              "baseline_file_sha256": hashlib.sha256(Path(baseline_path).read_bytes()).hexdigest(),
              "actual_policy_documents_file_sha256": hashlib.sha256(Path(policy_path).read_bytes()).hexdigest(),
              "resources_before": 17, "resources_after": 17, "additions": 0, "modifications": 1, "removals": 0,
              "modified_resource": "ExecutionCeiling1", "no_replacement_expected": True,
              "KMS_runtime_boundaries_other_policies_unchanged": True,
              "new_Allow_statements": 0, "NotAction_unchanged": True,
              "owner_ceiling_1_compact_chars": len(json.dumps(policy, separators=(",", ":"))),
              "check_count": len(matrix), "checks": matrix, "AWS_calls": 0, "execution_or_update_authorized": False}
    write("local-review.json", review)
    return review


def repair_bundle(baseline, policies):
    """Exact correction for both observed failures, with no invented actions.

    Preserve the old helper's three-path stage proposal as a testable subset;
    it is not the final application bundle after the root-tag CloudTrail event.
    """
    candidate = repair_template(baseline, policies)
    proposed = copy.deepcopy(policies)
    ceiling = candidate["Resources"]["ExecutionCeiling1"]["Properties"]["PolicyDocument"]
    ceiling["Statement"][0]["NotResource"] = list(COMPLETE_PATHS)
    scope = next(s for s in ceiling["Statement"] if s.get("Sid") == "CeilingNoOtherAPI")
    scope["NotResource"].extend(TAG_PATHS[1:])
    proposed[PREFIX + "owner-ceiling-1"] = ceiling
    identity = proposed[PREFIX + "cfn-identity-03"]["Statement"]
    guard = proposed[PREFIX + "cfn-guardrails-02"]["Statement"]
    require(identity[9]["Effect"] == "Deny" and identity[9]["Action"] == "apigateway:DELETE"
            and identity[10]["Effect"] == "Allow" and identity[10]["Resource"] == STAGE_PATHS[2], "Identity shape changed")
    require(guard[6]["Effect"] == "Deny" and guard[6]["NotResource"][-1] == STAGE_PATHS[2], "Guardrail shape changed")
    identity[9]["NotResource"].extend(TAG_PATHS[1:])
    identity[10]["Resource"] = list(TAG_PATHS)
    guard[6]["NotResource"].extend(TAG_PATHS[1:])
    require({arn for arn in policies if policies[arn] != proposed[arn]} ==
            {PREFIX + name for name in ("owner-ceiling-1", "cfn-identity-03", "cfn-guardrails-02")}, "Unexpected policy delta")
    # Complete input/output comparisons reject accidental nested or KMS changes.
    expected_template = copy.deepcopy(baseline)
    expected_template["Resources"]["ExecutionCeiling1"]["Properties"]["PolicyDocument"] = ceiling
    require(candidate == expected_template, "Unexpected access resource change")
    for arn in proposed:
        require(len(json.dumps(proposed[arn], separators=(",", ":"))) <= 6144, "Policy exceeds managed-policy quota: " + arn)
    return candidate, proposed


def bundle_matrix(policies, proposed):
    """Literal diagnostics and recognized HTTP authorization stay distinct."""
    checks = []
    broad = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]}
    ohio = {"aws:RequestedRegion": REGION}
    def check(label, action, resource, before, after, context=ohio, adversarial=False):
        extra = [broad] if adversarial else []
        old = api_decision(list(policies.values()) + extra, action, resource, context)
        new = api_decision(list(proposed.values()) + extra, action, resource, context)
        row = {"label": label, "action": action, "resource": resource, "context": context,
               "adversarial_simulation_only_Allow": adversarial, "before": old, "after": new,
               "expected_before": before, "expected_after": after, "passed": old == before and new == after}
        require(row["passed"], "Combined permission regression: " + str(row))
        checks.append(row)
    for resource in COMPLETE_PATHS:
        for verb in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            check("mapped_HTTP_full_lifecycle", "apigateway:" + verb, resource,
                  "allowed" if resource in STAGE_PATHS else "explicitDeny", "allowed")
        for name in ("TagResource", "UntagResource"):
            check("diagnostic_explicit_Deny_removed_NOT_Allow", "apigateway:" + name, resource, "explicitDeny", "implicitDeny")
        for context in ({}, {"aws:RequestedRegion": "us-east-1"}):
            for verb in ("GET", "POST", "PUT", "PATCH", "DELETE", "TagResource", "UntagResource"):
                check("region_or_missing_context_denied", "apigateway:" + verb, resource,
                      "explicitDeny", "explicitDeny", context, True)
    bad = [API.replace("l52iwors8c", "production") + "/stages", API + "/stages/production",
           API + "/stages/staging-evil", API + "/stages/staging/child", API + "/deployments",
           TAG_PREFIX + API.replace("l52iwors8c", "production"), TAG_PATHS[0].replace("staging", "production"),
           TAG_PATHS[0] + "%2Fchild", TAG_PATHS[1] + "/child", TAG_PATHS[2] + "%2Fchild",
           TAG_PATHS[3] + "/routes/r1", TAG_PREFIX + quote(quote(API, safe=""), safe=""),
           TAG_PREFIX + API.replace("/apis/", "/v2/apis/"), TAG_PATHS[0].replace("%3A", "%3a"),
           TAG_PATHS[3].replace("us-east-2", "us-east-1")]
    for resource in bad:
        for verb in ("GET", "POST", "PUT", "PATCH", "DELETE", "TagResource", "UntagResource"):
            check("unrelated_API_stage_or_tag_path_denied", "apigateway:" + verb, resource,
                  "explicitDeny", "explicitDeny", adversarial=True)
    check("original_API_deletion_stays_denied", "apigateway:DELETE", API, "explicitDeny", "explicitDeny", adversarial=True)
    check("CORS_rollback_still_allowed", "apigateway:DELETE", API + "/cors", "allowed", "allowed")
    for resource in (API, API + "/routes/r1", API + "/integrations/i1", API + "/authorizers/a1"):
        for verb in ("GET", "POST", "PUT", "PATCH"):
            check("existing_configuration_unchanged", "apigateway:" + verb, resource, "allowed", "allowed")
    return checks


def json_changes(before, after, path=""):
    """Lossless deterministic JSON patch; list edits are whole-array replacements."""
    if before == after:
        return []
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        return [row for i, (old, new) in enumerate(zip(before, after))
                for row in json_changes(old, new, path + "/" + str(i))]
    if isinstance(before, dict) and isinstance(after, dict):
        rows = []
        for key in before.keys() | after.keys():
            pointer = path + "/" + key.replace("~", "~0").replace("/", "~1")
            if key not in after:
                rows.append({"op": "remove", "path": pointer, "old_value": before[key]})
            elif key not in before:
                rows.append({"op": "add", "path": pointer, "value": after[key]})
            else:
                rows.extend(json_changes(before[key], after[key], pointer))
        return sorted(rows, key=lambda row: row["path"])
    return [{"op": "replace", "path": path, "old_value": before, "value": after}]


def simulation_resource_decisions(request, response):
    """Require every action/resource decision, never trust an aggregate result.

    IAM groups multiple requested resources under one EvaluationResult per
    action; that aggregate can conceal a denied child or an allowed resource.
    Missing, duplicate or extra decisions fail closed.
    """
    require(not response.get("IsTruncated"), "Incomplete IAM simulation response")
    wanted = {(a, r) for a in request["ActionNames"] for r in request["ResourceArns"]}
    found = {}
    for result in response["EvaluationResults"]:
        action = result["EvalActionName"]
        specific = result.get("ResourceSpecificResults", [])
        require(specific or len(request["ResourceArns"]) == 1, "Missing resource-specific IAM decisions")
        rows = specific or [{"EvalResourceName": result["EvalResourceName"], "EvalResourceDecision": result["EvalDecision"]}]
        for row in rows:
            key = (action, row["EvalResourceName"])
            require(key in wanted and key not in found, "Unexpected or duplicate IAM simulation resource")
            require(row["EvalResourceDecision"] in ("allowed", "explicitDeny", "implicitDeny"), "Unknown IAM decision")
            found[key] = row["EvalResourceDecision"]
    require(set(found) == wanted, "Incomplete action/resource IAM simulation coverage")
    return [{"action": action, "resource": resource, "decision": value} for (action, resource), value in sorted(found.items())]


def prepare_bundle(baseline_path, policy_path, output):
    baseline, policies = decode(Path(baseline_path).read_text()), decode(Path(policy_path).read_text())
    candidate, proposed = repair_bundle(baseline, policies)
    checks = bundle_matrix(policies, proposed)
    output = Path(output)
    require(not output.exists(), "Output must be a fresh directory")
    output.mkdir(parents=True)
    def write(name, value):
        (output / name).write_text(json.dumps(value, indent=2) + "\n")
    write("access-stack-api-tagging-repair.json", candidate)
    diffs = {}
    for suffix in ("owner-ceiling-1", "cfn-identity-03", "cfn-guardrails-02"):
        arn = PREFIX + suffix
        name = suffix.removeprefix("cfn-")
        write(name + ".json", proposed[arn])
        diffs[name] = json_changes(policies[arn], proposed[arn])
        (output / (name + ".diff")).write_text("".join(difflib.unified_diff(
            (json.dumps(policies[arn], indent=2) + "\n").splitlines(True),
            (json.dumps(proposed[arn], indent=2) + "\n").splitlines(True), fromfile="live-before", tofile="proposed-after")))
    write("proposed-effective-policy-documents.json", proposed)
    write("exact-policy-json-differences.json", diffs)
    write("exact-access-stack-json-differences.json", json_changes(baseline, candidate))
    report = {"status": "PASS_LOCAL_CONSOLIDATED_SCOPE_NOT_LIVE_ENFORCEMENT", "caveat": CAVEAT,
              "CloudTrail_API_root_tag_failure_included": True, "tag_resource_paths": TAG_PATHS,
              "checks": checks, "check_count": len(checks), "all_passed": True,
              "owner_stack_expected_changes": {"Add": 0, "Modify": 1, "Remove": 0, "Replacement": False},
              "external_policy_changes": ["identity-03", "guardrails-02"],
              "policy_compact_chars": {name: len(json.dumps(proposed[PREFIX + name], separators=(",", ":")))
                                       for name in ("owner-ceiling-1", "cfn-identity-03", "cfn-guardrails-02")},
              "new_action_names": [], "no_broad_API_Gateway_Allow": True,
              "KMS_runtime_other_owner_resources_unchanged": True, "AWS_calls": 0,
              "application_blocked_until_complete_evidence_capacity_and_separate_approval": True}
    write("local-review.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--policies", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    review = prepare_bundle(args.baseline, args.policies, args.output)
    print(json.dumps({key: review[key] for key in ("status", "check_count", "policy_compact_chars", "AWS_calls")}))


if __name__ == "__main__":
    main()
