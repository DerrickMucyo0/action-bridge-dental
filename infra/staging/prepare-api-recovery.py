#!/usr/bin/env python3
"""Prepare pinned staging API recovery policies locally; never call AWS.

Recovery A fixes the observed CORS rollback denial and protects the existing API
from deletion. Optional draft B models documented tag HTTP operations separately;
it is not recommended for live application because tagged CreateStage behavior
is unresolved. Neither draft includes the unapplied event-mapping repair.
"""
import argparse
import copy
import difflib
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[2]
ACCOUNT, REGION, STACK, API_ID = "631367363628", "us-east-2", "actionbridge-dental-staging", "l52iwors8c"
API = f"arn:aws:apigateway:{REGION}::/apis/{API_ID}"
CORS = API + "/cors"
OHIO = {"StringEquals": {"aws:RequestedRegion": REGION}}
FILES = ("identity-01.json", "identity-02.json", "identity-03.json", "guardrails-01.json", "guardrails-02.json")
CHANGED = ("identity-03.json", "guardrails-02.json")
UNCHANGED = tuple(name for name in FILES if name not in CHANGED)
PINS = {
    "identity-01.json": "65e4ac6a87ea0b1a1bf8b44f93c9836a894c988608119268b6bc7709d15e8d5b",
    "identity-02.json": "9b8c407018993fe2b02cff4304faa112214d34b6246afda7027c5e8818895c5f",
    "identity-03.json": "f7e85dadbf01bbf7553985822d343b0f96e959f20e785558f64386fc2df3ce9b",
    "guardrails-01.json": "8815922e7b6376f1b063eaa0d613a6923f95e6e40ccdf5f376961dceb996efbd",
    "guardrails-02.json": "0135b38399772f472d2b8d8d267ebdef5b83dc17a10ef05cf92418b6ad615a07",
}
LIVE_EXPORTS = {
    "identity-02.json": "identity-02-current.json", "identity-03.json": "identity-03-v3.json",
    "guardrails-01.json": "guardrails-01-v2.json", "guardrails-02.json": "guardrails-02-current.json",
}


def canonical_sha256(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def compact_size(document):
    return len(json.dumps(document, separators=(",", ":")))


def encoded(document):
    return (json.dumps(document, indent=2) + "\n").encode()


def validate_original(documents):
    if not isinstance(documents, dict) or set(documents) != set(FILES):
        raise ValueError("Exactly five reviewed policy documents are required.")
    for name in FILES:
        if canonical_sha256(documents[name]) != PINS[name]:
            raise ValueError("Current reviewed policy mismatch: " + name)


def recovery_documents(original):
    validate_original(original)
    repaired = copy.deepcopy(original)
    delete_resources = [arn for arn in original["guardrails-02.json"]["Statement"][7]["NotResource"] if arn != API] + [CORS]
    repaired["identity-03.json"]["Statement"] += [
        {"Effect": "Allow", "Action": "apigateway:DELETE", "Resource": CORS, "Condition": copy.deepcopy(OHIO)},
        {"Effect": "Deny", "Action": "apigateway:DELETE", "NotResource": delete_resources},
    ]
    # Move only DELETE's isolation guard to identity-03. Its new complement
    # excludes the API itself and includes its exact CORS child. The other
    # four verbs retain their original explicit Deny and resource selectors.
    repaired["guardrails-02.json"]["Statement"][7]["Action"].remove("apigateway:DELETE")
    if {name for name in FILES if repaired[name] != original[name]} != set(CHANGED):
        raise ValueError("Recovery changed an unexpected policy part.")
    if any(compact_size(repaired[name]) > 6144 for name in FILES):
        raise ValueError("A recovery policy exceeds 6,144 compact characters.")
    return repaired


def tag_arns():
    # HTTP API resource ARNs use /apis, not the /v2 endpoint URL prefix.
    return [f"arn:aws:apigateway:{REGION}::/tags/" + quote(target, safe="")
            for target in (API + "/stages", API + "/stages/staging")]


def forward_documents(original):
    """Unrecommended forward draft; do not use it as the rollback recovery fix."""
    repaired = recovery_documents(original)
    tags = tag_arns()
    repaired["identity-03.json"]["Statement"] += [
        {"Effect": "Allow", "Action": ["apigateway:GET", "apigateway:POST", "apigateway:PATCH", "apigateway:PUT"],
         "Resource": tags, "Condition": copy.deepcopy(OHIO)},
    ]
    guards = repaired["guardrails-02.json"]["Statement"]
    # These two original Denies use exactly the same four function resources.
    # Unioning only their actions is equivalent and avoids any policy splitting.
    if guards[1].get("NotResource") != guards[2].get("NotResource") or set(guards[1]) != {"Effect", "Action", "NotResource"} or set(guards[2]) != set(guards[1]):
        raise ValueError("Equivalent Lambda guard consolidation cannot be verified.")
    guards[1]["Action"] += guards[2]["Action"]
    del guards[2]
    guards[6]["NotResource"] += tags
    if any(compact_size(repaired[name]) > 6144 for name in FILES):
        raise ValueError("A forward draft exceeds 6,144 compact characters.")
    return repaired


def patches(original, forward=False):
    allow = recovery_documents(original)["identity-03.json"]["Statement"][8]
    protected = recovery_documents(original)["identity-03.json"]["Statement"][9]
    result = {
        "identity-03.json": [
            {"op": "add", "path": "/Statement/-", "value": allow},
            {"op": "add", "path": "/Statement/-", "value": protected},
        ],
        "guardrails-02.json": [{"op": "replace", "path": "/Statement/7/Action",
                                "old_value": original["guardrails-02.json"]["Statement"][7]["Action"],
                                "value": recovery_documents(original)["guardrails-02.json"]["Statement"][7]["Action"]}],
    }
    if forward:
        proposed = forward_documents(original)
        result["identity-03.json"] += [{"op": "add", "path": "/Statement/-", "value": item}
                                       for item in proposed["identity-03.json"]["Statement"][10:]]
        result["guardrails-02.json"] += [
            {"op": "replace", "path": "/Statement/1/Action", "old_value": original["guardrails-02.json"]["Statement"][1]["Action"],
             "value": proposed["guardrails-02.json"]["Statement"][1]["Action"]},
            {"op": "remove", "path": "/Statement/2", "old_value": original["guardrails-02.json"]["Statement"][2]},
        ] + [{"op": "add", "path": "/Statement/6/NotResource/-", "value": arn} for arn in tag_arns()]
    return result


def safe_path(path):
    result = Path(path).absolute()
    if any(part.is_symlink() for part in (result, *result.parents)):
        raise ValueError("Refusing a symlink in source/output paths.")
    return result.resolve()


def prepare_bytes(original_bytes, original, source, output, saved_matches, forward=False):
    proposed = forward_documents(original) if forward else recovery_documents(original)
    outputs = {name: original_bytes[name] if name in UNCHANGED else encoded(proposed[name]) for name in FILES}
    outputs["changes.json"] = encoded({"format": "RFC 6902 with original-value evidence", "patches": patches(original, forward), "unchanged_parts": list(UNCHANGED)})
    for name in CHANGED:
        outputs[name.removesuffix(".json") + ".diff"] = "".join(difflib.unified_diff(
            original_bytes[name].decode().splitlines(keepends=True), outputs[name].decode().splitlines(keepends=True),
            fromfile="saved-current/" + name, tofile=("forward-draft-B/" if forward else "recovery-A/") + name)).encode()
    review = {
        "status": "DRAFT_B_NOT_RECOMMENDED_FOR_LIVE" if forward else "UNAPPLIED_RECOVERY_A_OWNER_APPROVAL_REQUIRED",
        "account": ACCOUNT, "region": REGION, "stack_name": STACK, "api_id": API_ID,
        "source_directory": str(source), "output_directory": str(output),
        "changed_parts": list(CHANGED), "unchanged_parts": list(UNCHANGED),
        "unchanged_parts_byte_identical": all(outputs[name] == original_bytes[name] for name in UNCHANGED),
        "source_canonical_sha256": dict(PINS),
        "proposed_canonical_sha256": {name: canonical_sha256(proposed[name]) for name in FILES},
        "compact_sizes": {name: compact_size(proposed[name]) for name in FILES},
        "saved_current_exports_match": saved_matches,
        "direct_live_IAM_read_performed": False, "live_IAM_changes": 0, "aws_calls": 0,
        "new_policies_or_attachments_required": False,
        "event_source_mapping_proposal_applied": False,
        "event_source_mapping_statements_unchanged": all(
            [s for s in original[name]["Statement"] if "EventSourceMapping" in json.dumps(s)] ==
            [s for s in proposed[name]["Statement"] if "EventSourceMapping" in json.dumps(s)] for name in FILES),
        "IAM_role_and_boundary_statements_unchanged": all(
            [s for s in original[name]["Statement"] if "iam:" in json.dumps(s)] ==
            [s for s in proposed[name]["Statement"] if "iam:" in json.dumps(s)] for name in FILES),
        "preserved_API_delete_explicitly_denied": True,
        "CORS_rollback_scope": {"action": "apigateway:DELETE", "resource": CORS, "region": REGION},
        "traffic_enablement_authorized": False, "deployment_authorized": False,
        "rollback_continuation_authorized": False,
        "tagged_CreateStage_failure_resolved": False,
        "forward_tagging_status": "UNVERIFIED_SEPARATE_DRAFT" if forward else "EXCLUDED_FROM_RECOVERY_A",
        "sources": ["https://docs.aws.amazon.com/service-authorization/latest/reference/list_apigatewayv2.html",
                    "https://docs.aws.amazon.com/apigatewayv2/latest/api-reference/apis-apiid-cors.html",
                    "https://docs.aws.amazon.com/apigatewayv2/latest/api-reference/tags-resource-arn.html",
                    "https://docs.aws.amazon.com/apigateway/latest/developerguide/arn-format-reference.html"],
    }
    if forward:
        review.update({
            "encoded_tag_resource_arns": tag_arns(),
            "Lambda_guard_consolidation": "Original statements 1 and 2 share identical NotResource lists; only their Action lists are unioned.",
            "known_limit": "AWS reports apigateway:TagResource on the stages collection during tagged CreateStage, while current SAR maps tagging to HTTP verbs. This draft grants documented HTTP operations on exact encoded tag ARNs only; it does not prove that tag-on-create permission checks are resolved. Do not apply it for recovery or start another deployment based on it.",
        })
    else:
        review["next_owner_action"] = "Review only the identity-03 and guardrails-02 replacement versions in bundle A. Applying them and continuing rollback each require separate approval; no resource skipping or API deletion is authorized."
    outputs["review.json"] = encoded(review)
    return outputs, review


def write_reviews(source_dir, live_review_dir, recovery_dir, forward_dir=None):
    source, live, recovery = map(safe_path, (source_dir, live_review_dir, recovery_dir))
    destinations = [recovery] + ([safe_path(forward_dir)] if forward_dir is not None else [])
    if len(set(destinations)) != len(destinations) or any(path.exists() or path == source or source in path.parents for path in destinations):
        raise ValueError("Each output must be a new exclusive directory outside the source.")
    raw = {name: safe_path(source / name).read_bytes() for name in FILES}
    original = {name: json.loads(value) for name, value in raw.items()}
    validate_original(original)
    live_raw = {name: safe_path(live / filename).read_bytes() for name, filename in LIVE_EXPORTS.items()}
    for name, value in live_raw.items():
        if json.loads(value) != original[name]:
            raise ValueError("Saved current export differs from the reviewed original: " + name)
    matches = {name: {"path": str(live / filename), "canonical_sha256": canonical_sha256(json.loads(live_raw[name])), "match": True}
               for name, filename in LIVE_EXPORTS.items()}
    prepared = [prepare_bytes(raw, original, source, recovery, matches)]
    if len(destinations) == 2:
        prepared.append(prepare_bytes(raw, original, source, destinations[1], matches, forward=True))
    for name, value in raw.items():
        if safe_path(source / name).read_bytes() != value:
            raise ValueError("Original policy changed during preparation; no output written.")
    for name, value in live_raw.items():
        if safe_path(live / LIVE_EXPORTS[name]).read_bytes() != value:
            raise ValueError("Saved current export changed during preparation; no output written.")
    for destination, (outputs, _) in zip(destinations, prepared):
        destination.mkdir(mode=0o700)
        for name, value in outputs.items():
            fd = os.open(safe_path(destination / name), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(value)
    return [review for _, review in prepared]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT / ".staging/execution-repair-minimal-l52iwors8c")
    parser.add_argument("--live-review-dir", type=Path, default=ROOT / ".staging/live-policy-review")
    parser.add_argument("--recovery-dir", type=Path, default=ROOT / ".staging/api-recovery-review")
    parser.add_argument("--forward-dir", type=Path, help="Optional exclusive directory for separate UNRECOMMENDED tagging draft B.")
    args = parser.parse_args(argv)
    try:
        reviews = write_reviews(args.source_dir, args.live_review_dir, args.recovery_dir, args.forward_dir)
    except (ValueError, OSError) as error:
        parser.exit(1, "Offline API recovery preparation refused: " + str(error) + "\n")
    for review in reviews:
        print(json.dumps({key: review[key] for key in ("status", "changed_parts", "unchanged_parts_byte_identical", "compact_sizes", "output_directory", "aws_calls")}, indent=2))
    return 0


if __name__ == "__main__":
    main()
