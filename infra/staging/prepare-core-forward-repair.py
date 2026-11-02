#!/usr/bin/env python3
"""Audit an unapproved Stage tagging candidate offline and fail closed.

The provider schema names TagResource/UntagResource, but its permission labels do
not establish that IAM recognizes those actions. The candidate function remains
for regression analysis only. The writer requires the pinned official IAM action
catalog and refuses application-format output for unrecognized actions. It never
calls AWS, applies policies, or prepares/executes a change set.
"""
import argparse
import copy
import difflib
import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ACCOUNT, REGION, STACK, API_ID = "631367363628", "us-east-2", "actionbridge-dental-staging", "l52iwors8c"
API = f"arn:aws:apigateway:{REGION}::/apis/{API_ID}"
STAGES, STAGE = API + "/stages", API + "/stages/staging"
FILES = ("identity-01.json", "identity-02.json", "identity-03.json", "guardrails-01.json", "guardrails-02.json")
CHANGED = "identity-03.json"
UNCHANGED = tuple(name for name in FILES if name != CHANGED)
PINS = {
    "identity-01.json": "65e4ac6a87ea0b1a1bf8b44f93c9836a894c988608119268b6bc7709d15e8d5b",
    "identity-02.json": "9b8c407018993fe2b02cff4304faa112214d34b6246afda7027c5e8818895c5f",
    "identity-03.json": "9e6fcedb45c43ee8d4db4bd63650f93494492087fc2cdaffbba0f3f97d304dc0",
    "guardrails-01.json": "8815922e7b6376f1b063eaa0d613a6923f95e6e40ccdf5f376961dceb996efbd",
    "guardrails-02.json": "d901e874a52040bd406834ebbf3c1cee3dec718577080a0a0185363877f3f7e0",
}
SAVED_EXPORTS = {
    "identity-02.json": "identity-02-current.json", "identity-03.json": "identity-03-recovery-a.json",
    "guardrails-01.json": "guardrails-01-v2.json", "guardrails-02.json": "guardrails-02-recovery-a.json",
}
STAGE_SCHEMA_SHA256 = "d257a8bc9dbb7e6c47f3396fc4021a60b5cb9cf7920117a3187d1f8f6c2b30e8"
SCHEMA_SOURCE = "https://schema.cloudformation.us-east-2.amazonaws.com/CloudformationSchema.zip"
CATALOG_SOURCE = "https://servicereference.us-east-1.amazonaws.com/v1/apigateway/apigateway.json"
CATALOG_SHA256 = "a89cf68f8f0c509b726695174f57fa61be969d00320aea4bb35f441e713a5c7b"
DEFAULT_CATALOG = ROOT / ".staging/core-forward-deployment-review/apigateway-service-authorization.json"


def canonical_sha256(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def compact_size(document):
    return len(json.dumps(document, separators=(",", ":")))


def encoded(document):
    return (json.dumps(document, indent=2) + "\n").encode()


def decode_json(raw):
    """Reject ambiguous documents and JavaScript constants outside JSON."""
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON object keys are not accepted.")
            result[key] = value
        return result

    def invalid_constant(_):
        raise ValueError("Non-JSON numeric constants are not accepted.")

    return json.loads(raw, object_pairs_hook=unique_pairs, parse_constant=invalid_constant)


def validate_original(original):
    if not isinstance(original, dict) or set(original) != set(FILES):
        raise ValueError("Exactly the five reviewed Recovery A policy parts are required.")
    for name in FILES:
        if canonical_sha256(original[name]) != PINS[name]:
            raise ValueError("Recovery A policy baseline mismatch: " + name)


def tagging_statements():
    regional = {"StringEquals": {"aws:RequestedRegion": REGION}}
    return [
        {"Effect": "Allow", "Action": "apigateway:TagResource", "Resource": [STAGES, STAGE], "Condition": copy.deepcopy(regional)},
        {"Effect": "Allow", "Action": "apigateway:UntagResource", "Resource": STAGE, "Condition": copy.deepcopy(regional)},
        {"Effect": "Deny", "Action": "apigateway:TagResource", "NotResource": [STAGES, STAGE]},
        {"Effect": "Deny", "Action": "apigateway:UntagResource", "NotResource": STAGE},
    ]


def repair_documents(original):
    """Return the unapproved literal-action candidate for regression math ONLY.

    A returned dictionary is not an approved or recognized IAM policy. The
    writer independently validates action recognition and currently rejects it.
    """
    validate_original(original)
    proposed = copy.deepcopy(original)
    proposed[CHANGED]["Statement"] += tagging_statements()
    if len(original[CHANGED]["Statement"]) != 10 or len(proposed[CHANGED]["Statement"]) != 14:
        raise ValueError("Expected the ten-statement Recovery A identity baseline and four additions.")
    if proposed[CHANGED]["Statement"][:10] != original[CHANGED]["Statement"]:
        raise ValueError("An existing Recovery A identity statement changed.")
    if {name for name in FILES if original[name] != proposed[name]} != {CHANGED}:
        raise ValueError("An unexpected policy part changed.")
    if any(compact_size(doc) > 6144 for doc in proposed.values()):
        raise ValueError("A proposed policy exceeds 6,144 compact characters.")
    return proposed


def validate_provider_document(document):
    """Check the permissions relevant to this repair, beyond the full raw pin."""
    if document.get("typeName") != "AWS::ApiGatewayV2::Stage":
        raise ValueError("The provider document is not AWS::ApiGatewayV2::Stage.")
    handlers = document.get("handlers", {})
    required = {"create": {"apigateway:POST", "apigateway:TagResource"},
                "update": {"apigateway:PATCH", "apigateway:POST", "apigateway:DELETE", "apigateway:TagResource", "apigateway:UntagResource"},
                "read": {"apigateway:GET"}, "list": {"apigateway:GET"}, "delete": {"apigateway:DELETE"}}
    if any(set(handlers.get(name, {}).get("permissions", [])) != actions for name, actions in required.items()):
        raise ValueError("The reviewed Stage handler permissions differ from the pinned contract.")
    tagging = document.get("tagging", {})
    if any(tagging.get(name) is not True for name in ("taggable", "tagOnCreate", "tagUpdatable", "cloudFormationSystemTags")):
        raise ValueError("The reviewed Stage tagging/system-tag contract changed.")
    if set(tagging.get("permissions", [])) != {"apigateway:POST", "apigateway:TagResource", "apigateway:UntagResource"}:
        raise ValueError("The reviewed Stage tagging permissions changed.")


def safe_path(path):
    result = Path(path).absolute()
    if any(part.is_symlink() for part in (result, *result.parents)):
        raise ValueError("Refusing a symlink in source/output paths.")
    return result.resolve()


def load_provider_schema(directory):
    path = safe_path(Path(directory) / "aws-apigatewayv2-stage.json")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != STAGE_SCHEMA_SHA256:
        raise ValueError("The reviewed Ohio Stage provider schema changed; stop for review.")
    document = decode_json(raw)
    validate_provider_document(document)
    return {"path": str(path), "raw_sha256": STAGE_SCHEMA_SHA256, "source": SCHEMA_SOURCE,
            "typeName": document["typeName"], "handlers": document["handlers"], "tagging": document["tagging"]}


def load_authorization_catalog(path):
    path = safe_path(path)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CATALOG_SHA256:
        raise ValueError("The reviewed API Gateway IAM action catalog changed; stop for review.")
    document = decode_json(raw)
    if document.get("Name") != "apigateway" or not isinstance(document.get("Actions"), list):
        raise ValueError("The action catalog is not the reviewed API Gateway catalog.")
    if not all(isinstance(item, dict) for item in document["Actions"]):
        raise ValueError("The action catalog contains invalid entries.")
    names = [item.get("Name") for item in document["Actions"]]
    if not all(isinstance(name, str) and name for name in names) or len(names) != len(set(names)):
        raise ValueError("The action catalog contains invalid action names.")
    return {"path": str(path), "raw_sha256": CATALOG_SHA256, "source": CATALOG_SOURCE,
            "recognized_actions": ["apigateway:" + name for name in names]}


def validate_action_recognition(document, catalog):
    recognized = {name.lower() for name in catalog["recognized_actions"]}
    unsupported = set()
    for statement in document["Statement"]:
        for key in ("Action", "NotAction"):
            actions = statement.get(key, [])
            actions = [actions] if isinstance(actions, str) else actions
            unsupported.update(action for action in actions
                               if action.lower().startswith("apigateway:") and action.lower() not in recognized)
    if unsupported:
        raise ValueError("BLOCKED: unrecognized API Gateway IAM actions: " + ", ".join(sorted(unsupported))
                         + ". Provider permission labels do not override the IAM action catalog; no policy output written.")


def write_repair(source_dir, live_review_dir, provider_schema_dir, output_dir, authorization_catalog=None):
    source, live, output = map(safe_path, (source_dir, live_review_dir, output_dir))
    if output.exists() or output == source or source in output.parents:
        raise ValueError("Output must be a new exclusive directory outside the source bundle.")
    original_bytes = {name: safe_path(source / name).read_bytes() for name in FILES}
    original = {name: decode_json(raw) for name, raw in original_bytes.items()}
    proposed = repair_documents(original)
    saved_bytes = {name: safe_path(live / filename).read_bytes() for name, filename in SAVED_EXPORTS.items()}
    for name, raw in saved_bytes.items():
        if decode_json(raw) != original[name]:
            raise ValueError("Saved current export does not match Recovery A: " + name)
    provider = load_provider_schema(provider_schema_dir)
    catalog = load_authorization_catalog(authorization_catalog or DEFAULT_CATALOG)
    # The currently retained literal-action candidate fails here. Matching
    # resource strings in a local evaluator is not action recognition evidence.
    validate_action_recognition(proposed[CHANGED], catalog)
    outputs = {name: encoded(proposed[name]) if name == CHANGED else original_bytes[name] for name in FILES}
    operations = [{"op": "add", "path": "/Statement/-", "proposed_index": index, "value": statement}
                  for index, statement in enumerate(tagging_statements(), start=10)]
    outputs["changes.json"] = encoded({"format": "RFC 6902 additions with proposed array indexes", "patches": {CHANGED: operations},
                                       "unchanged_parts": list(UNCHANGED), "original_ten_identity_statements_unchanged": True})
    outputs["identity-03.diff"] = "".join(difflib.unified_diff(
        original_bytes[CHANGED].decode().splitlines(keepends=True), outputs[CHANGED].decode().splitlines(keepends=True),
        fromfile="current-Recovery-A/" + CHANGED, tofile="proposed-stage-tagging/" + CHANGED)).encode()
    review = {
        "status": "BLOCKED_CANDIDATE_NOT_FOR_APPLICATION",
        "account": ACCOUNT, "region": REGION, "stack_name": STACK, "api_id": API_ID,
        "source_directory": str(source), "output_directory": str(output),
        "changed_parts": [CHANGED], "unchanged_parts": list(UNCHANGED),
        "policy_to_update": f"arn:aws:iam::{ACCOUNT}:policy/{STACK}-cfn-identity-03",
        "original_identity_statement_count": 10, "proposed_identity_statement_count": 14,
        "original_ten_identity_statements_unchanged": True,
        "four_other_parts_byte_identical": all(outputs[name] == original_bytes[name] for name in UNCHANGED),
        "source_canonical_sha256": dict(PINS),
        "proposed_canonical_sha256": {name: canonical_sha256(proposed[name]) for name in FILES},
        "compact_sizes": {name: compact_size(proposed[name]) for name in FILES},
        "saved_current_exports_match": {name: {"path": str(live / SAVED_EXPORTS[name]), "canonical_sha256": canonical_sha256(decode_json(raw)), "match": True}
                                        for name, raw in saved_bytes.items()},
        "Stage_provider_contract": provider,
        "IAM_action_catalog": catalog,
        "literal_action_basis": "Provider metadata and the prior service error name TagResource/UntagResource, but those labels are not proof that IAM recognizes the literal action names. The pinned official IAM catalog controls the recognition gate.",
        "scope": {"TagResource": [STAGES, STAGE], "UntagResource": [STAGE], "requested_region": REGION},
        "candidate_pattern_denials_outside_scope": True,
        "CORS_rollback_and_API_delete_protections_preserved": True,
        "existing_IAM_role_boundary_and_mapping_statements_preserved": True,
        "unapplied_mapping_or_encoded_tag_HTTP_drafts_included": False,
        "API_endpoint_or_template_changed": False,
        "live_policy_document_reads_performed": False, "aws_calls": 0, "live_IAM_changes": 0,
        "new_policies_or_attachments_required": False,
        "deployment_authorized": False, "change_set_creation_authorized": False, "traffic_enablement_authorized": False,
        "limitations": ["This is a blocked offline candidate, not an approved permission repair; AWS has not evaluated a new stage creation with it.",
                        "The IAM action catalog does not recognize the literal actions. Provider metadata and service error labels cannot override that recognition failure.",
                        "The reviewed deployment scope is initial creation of the current core resources, update of the existing API, and rollback of those additions; not all possible future provider read/update paths have been validated.",
                        "Additional Lambda, DynamoDB and Logs getter/read paths in provider union lists remain unproven; optional absent features do not justify granting unrelated actions.",
                        "Provider schema handler permission arrays also include optional-feature permissions for other resource types; do not grant unrelated actions merely because they appear in a union list."],
        "next_owner_action": "Do not apply this candidate. A recognized HTTP tagging repair must address explicit denials in guardrails-02 and identity-03 Statement 9; preserving all original ten identity statements prevents allowing DELETE on a separate Tags ARN.",
    }
    outputs["review.json"] = encoded(review)
    for name, raw in original_bytes.items():
        if safe_path(source / name).read_bytes() != raw:
            raise ValueError("A source policy changed during preparation; no output written.")
    for name, raw in saved_bytes.items():
        if safe_path(live / SAVED_EXPORTS[name]).read_bytes() != raw:
            raise ValueError("A saved current export changed during preparation; no output written.")
    # Recheck the exact provider evidence before writing the exclusive bundle.
    if load_provider_schema(provider_schema_dir) != provider:
        raise ValueError("Provider evidence changed during preparation; no output written.")
    if load_authorization_catalog(authorization_catalog or DEFAULT_CATALOG) != catalog:
        raise ValueError("IAM action catalog changed during preparation; no output written.")
    output.mkdir(mode=0o700)
    for name, raw in outputs.items():
        fd = os.open(safe_path(output / name), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
    return review


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT / ".staging/api-recovery-review/policies-A")
    parser.add_argument("--live-review-dir", type=Path, default=ROOT / ".staging/live-policy-review")
    parser.add_argument("--provider-schema-dir", type=Path, default=ROOT / ".staging/core-forward-deployment-review/provider-schemas")
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".staging/core-forward-deployment-review/policies-stage-tagging")
    parser.add_argument("--authorization-catalog", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args(argv)
    try:
        review = write_repair(args.source_dir, args.live_review_dir, args.provider_schema_dir, args.output_dir, args.authorization_catalog)
    except (ValueError, OSError) as error:
        parser.exit(1, "Offline core forward repair refused: " + str(error) + "\n")
    print(json.dumps({key: review[key] for key in ("status", "changed_parts", "four_other_parts_byte_identical", "compact_sizes", "output_directory", "aws_calls")}, indent=2))
    return 0


if __name__ == "__main__":
    main()
