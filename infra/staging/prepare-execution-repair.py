#!/usr/bin/env python3
"""Prepare the fixed staging IAM repair offline; never apply permissions.

Accept only the five reviewed local baseline documents for API l52iwors8c. Keep
three parts byte-identical and prepare two replacement policy versions in a new,
exclusive directory. The canonical pins describe local drafts, not live IAM.
"""
import argparse
import copy
import difflib
import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ACCOUNT, REGION, API = "631367363628", "us-east-2", "l52iwors8c"
STACK = "actionbridge-dental-staging"
ROLE_PATH = "/actionbridge/staging/actionbridge-dental-staging/"
SLUGS = ("health", "cases", "calculations", "jobs", "job-worker")
ROLES = [f"arn:aws:iam::{ACCOUNT}:role{ROLE_PATH}{STACK}-{slug}-role" for slug in SLUGS]
ALIASES = [f"arn:aws:iam::{ACCOUNT}:role/{STACK}-{slug}-role" for slug in SLUGS]
BOUNDARIES = [f"arn:aws:iam::{ACCOUNT}:policy/{STACK}-{slug}-boundary" for slug in SLUGS]
BASIC = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
SQS = "arn:aws:iam::aws:policy/service-role/AWSLambdaSQSQueueExecutionRole"
POLICY_FILES = (
    "identity-01.json", "identity-02.json", "identity-03.json",
    "guardrails-01.json", "guardrails-02.json",
)
CHANGED_FILES = ("guardrails-01.json", "identity-03.json")
UNCHANGED_FILES = ("identity-01.json", "identity-02.json", "guardrails-02.json")
DEFAULT_SOURCE = ROOT / ".staging/execution-review-l52iwors8c"
DEFAULT_OUTPUT = ROOT / ".staging/execution-repair-minimal-l52iwors8c"
BASELINE_CANONICAL_SHA256 = {
    "identity-01.json": "65e4ac6a87ea0b1a1bf8b44f93c9836a894c988608119268b6bc7709d15e8d5b",
    "identity-02.json": "9b8c407018993fe2b02cff4304faa112214d34b6246afda7027c5e8818895c5f",
    "identity-03.json": "ab6a91ef34042a1ae49b481ed812691d82a03f3f27271b7bcc32e2fdbab5589e",
    "guardrails-01.json": "ccb45f1295c915a904e230a5c8ba947051c1983976fc784bd0fc4e77aa931bfa",
    "guardrails-02.json": "0135b38399772f472d2b8d8d267ebdef5b83dc17a10ef05cf92418b6ad615a07",
}


def canonical_sha256(document):
    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def compact_size(document):
    return len(json.dumps(document, separators=(",", ":")))


def encoded(document):
    return (json.dumps(document, indent=2) + "\n").encode()


def validate_baseline(original):
    if not isinstance(original, dict) or set(original) != set(POLICY_FILES):
        raise ValueError("The baseline must contain exactly the five reviewed policy parts.")
    for name in POLICY_FILES:
        document = original[name]
        if canonical_sha256(document) != BASELINE_CANONICAL_SHA256[name]:
            raise ValueError(f"Reviewed local baseline mismatch: {name}; no output is authorized.")
        if document.get("Version") != "2012-10-17" or compact_size(document) > 6144:
            raise ValueError(f"Invalid baseline policy document: {name}.")
    # Pin the editable structures explicitly as well as the complete documents.
    statements = original["guardrails-01.json"]["Statement"]
    if statements[5] != {"Effect": "Deny", "Action": "iam:*", "NotResource": ROLES}:
        raise ValueError("Unexpected original IAM resource isolation guard.")
    boundary_actions = [
        "iam:CreateRole", "iam:PutRolePolicy", "iam:UpdateAssumeRolePolicy",
        "iam:AttachRolePolicy", "iam:DetachRolePolicy",
    ]
    for index, (role, boundary) in enumerate(zip(ROLES, BOUNDARIES)):
        expected = {
            "Effect": "Deny", "Action": boundary_actions, "Resource": role,
            "Condition": {"ArnNotEquals": {"iam:PermissionsBoundary": boundary}},
        }
        if statements[7 + 2 * index] != expected:
            raise ValueError("A role-specific boundary guard differs from the reviewed baseline.")
        expected = {
            "Effect": "Deny", "Action": ["iam:AttachRolePolicy", "iam:DetachRolePolicy"],
            "Resource": role,
            "Condition": {"ArnNotEquals": {"iam:PolicyARN": [BASIC, SQS] if index == 4 else BASIC}},
        }
        if statements[8 + 2 * index] != expected:
            raise ValueError("A managed-policy allowlist guard differs from the reviewed baseline.")


def alias_supplements():
    """Required allow and deny additions carried together by identity-03."""
    return [
        {"Effect": "Allow", "Action": "iam:GetRole", "Resource": ALIASES},
        {
            "Effect": "Allow", "Action": "iam:DetachRolePolicy", "Resource": ALIASES[:4],
            "Condition": {"ArnEquals": {"iam:PolicyARN": BASIC},
                          "Null": {"iam:PermissionsBoundary": "true"}},
        },
        {
            "Effect": "Allow", "Action": "iam:DetachRolePolicy", "Resource": ALIASES[4],
            "Condition": {"ArnEquals": {"iam:PolicyARN": [BASIC, SQS]},
                          "Null": {"iam:PermissionsBoundary": "true"}},
        },
        {"Effect": "Deny", "NotAction": ["iam:GetRole", "iam:DetachRolePolicy"], "Resource": ALIASES},
        {"Effect": "Deny", "Action": "iam:DetachRolePolicy", "Resource": ALIASES,
         "Condition": {"Null": {"iam:PermissionsBoundary": "false"}}},
    ]


def grouped_policy_guards():
    return [
        {
            "Effect": "Deny", "Action": ["iam:AttachRolePolicy", "iam:DetachRolePolicy"],
            "Resource": ROLES[:4] + ALIASES[:4],
            "Condition": {"ArnNotEquals": {"iam:PolicyARN": BASIC}},
        },
        {
            "Effect": "Deny", "Action": ["iam:AttachRolePolicy", "iam:DetachRolePolicy"],
            "Resource": [ROLES[4], ALIASES[4]],
            "Condition": {"ArnNotEquals": {"iam:PolicyARN": [BASIC, SQS]}},
        },
    ]


def repair_documents(original):
    """Return five repaired JSON documents, rejecting any baseline drift."""
    validate_baseline(original)
    repaired = copy.deepcopy(original)
    guards = repaired["guardrails-01.json"]["Statement"]
    guards[5]["NotResource"] = ROLES + ALIASES
    old_policy_guards = {8, 10, 12, 14, 16}
    repaired["guardrails-01.json"]["Statement"] = [
        statement for index, statement in enumerate(guards) if index not in old_policy_guards
    ] + grouped_policy_guards()
    repaired["identity-03.json"]["Statement"] += alias_supplements()
    changed = {name for name in POLICY_FILES if repaired[name] != original[name]}
    if changed != set(CHANGED_FILES):
        raise ValueError("The repair changed an unexpected policy part.")
    if any(compact_size(repaired[name]) > 6144 for name in POLICY_FILES):
        raise ValueError("A repaired managed-policy document exceeds 6,144 characters.")
    # Boundary guards survive byte-for-byte as JSON objects, with only their
    # array positions changing after equivalent policy guards are consolidated.
    new_guards = repaired["guardrails-01.json"]["Statement"]
    for index in range(5):
        if original["guardrails-01.json"]["Statement"][7 + 2 * index] not in new_guards:
            raise ValueError("A role-specific boundary guard was changed.")
    return repaired


def pointer_patches(original, repaired):
    """RFC 6902 operations with evidence pointers into the original documents."""
    before = original["guardrails-01.json"]["Statement"]
    changes = [{
        "op": "replace", "path": "/Statement/5/NotResource",
        "original_json_pointer": "/Statement/5/NotResource",
        "old_value": before[5]["NotResource"], "value": ROLES + ALIASES,
    }]
    # Descending removals keep every path valid in the original array.
    for index in (16, 14, 12, 10, 8):
        changes.append({
            "op": "remove", "path": f"/Statement/{index}",
            "original_json_pointer": f"/Statement/{index}", "old_value": before[index],
        })
    for index, statement in enumerate(grouped_policy_guards(), start=12):
        changes.append({
            "op": "add", "path": "/Statement/-", "original_json_pointer": "/Statement",
            "proposed_json_pointer": f"/Statement/{index}", "value": statement,
            "consolidates_original_json_pointers": [f"/Statement/{i}" for i in ((8, 10, 12, 14) if index == 12 else (16,))],
        })
    additions = [{
        "op": "add", "path": "/Statement/-", "original_json_pointer": "/Statement",
        "proposed_json_pointer": f"/Statement/{index}", "value": statement,
    } for index, statement in enumerate(alias_supplements(), start=3)]
    return {
        "format": "RFC 6902 patches with original-value and JSON-pointer evidence",
        "patches": {"guardrails-01.json": changes, "identity-03.json": additions},
        "unchanged_parts": list(UNCHANGED_FILES),
        "boundary_guard_evidence": [{
            "original_json_pointer": f"/Statement/{7 + 2 * i}",
            "proposed_json_pointer": f"/Statement/{7 + i}",
            "unchanged": original["guardrails-01.json"]["Statement"][7 + 2 * i]
                         == repaired["guardrails-01.json"]["Statement"][7 + i],
        } for i in range(5)],
    }


def safe_path(path):
    absolute = Path(path).absolute()
    if any(part.is_symlink() for part in (absolute, *absolute.parents)):
        raise ValueError("Refusing a symlink in a source or output path.")
    return absolute.resolve()


def write_repair(source_dir, output_dir):
    """Read public baseline policies and exclusively write an UNAPPLIED review bundle."""
    source, output = safe_path(source_dir), safe_path(output_dir)
    if not source.is_dir():
        raise ValueError("The original reviewed policy directory does not exist.")
    if output.exists():
        raise ValueError("Output already exists; refusing to overwrite any review artifact.")
    if source == output or source in output.parents:
        raise ValueError("The repair output must not modify the original review directory.")
    original_bytes = {}
    for name in POLICY_FILES:
        path = safe_path(source / name)
        if not path.is_file():
            raise ValueError(f"Missing original policy part: {name}.")
        original_bytes[name] = path.read_bytes()
    original = {name: json.loads(raw) for name, raw in original_bytes.items()}
    repaired = repair_documents(original)
    source_review = source / "review.json"
    source_review_raw = None
    if source_review.exists() or source_review.is_symlink():
        safe_path(source_review)
        source_review_raw = source_review.read_bytes()
        metadata = json.loads(source_review_raw)
        expected = {"account": ACCOUNT, "region": REGION, "stack_name": STACK, "api_id": API,
                    "event_source_mapping_id": None}
        if any(metadata.get(key) != value for key, value in expected.items()):
            raise ValueError("Original review metadata does not match the fixed staging target.")
    output_bytes = {
        name: original_bytes[name] if name in UNCHANGED_FILES else encoded(repaired[name])
        for name in POLICY_FILES
    }
    pointer_diff = pointer_patches(original, repaired)
    output_bytes["changes.json"] = encoded(pointer_diff)
    diff_names = []
    for name in CHANGED_FILES:
        diff_name = name.removesuffix(".json") + ".diff"
        diff_names.append(diff_name)
        output_bytes[diff_name] = "".join(difflib.unified_diff(
            original_bytes[name].decode().splitlines(keepends=True),
            output_bytes[name].decode().splitlines(keepends=True),
            fromfile="original/" + name, tofile="proposed/" + name,
        )).encode()
    review = {
        "status": "UNAPPLIED", "account": ACCOUNT, "region": REGION,
        "stack_name": STACK, "api_id": API,
        "execution_role": f"arn:aws:iam::{ACCOUNT}:role/{STACK}-cfn",
        "source_directory": str(source), "output_directory": str(output),
        "aws_calls": 0, "live_policy_changes_performed": False,
        "live_policy_document_match_verified": False,
        "baseline_pin_scope": "Exact reviewed local baseline only; owner must compare with current live policy versions.",
        "policy_part_count": 5, "managed_policy_size_limit": 6144,
        "compact_sizes": {name: compact_size(repaired[name]) for name in POLICY_FILES},
        "changed_parts": list(CHANGED_FILES), "unchanged_parts": list(UNCHANGED_FILES),
        "unchanged_parts_byte_identical": all(output_bytes[name] == original_bytes[name] for name in UNCHANGED_FILES),
        "existing_policy_versions_requiring_review": list(CHANGED_FILES),
        "new_managed_policies_required": False, "new_policy_attachments_required": False,
        "required_attached_policy_parts": list(POLICY_FILES),
        "required_guardrail_carriers": ["guardrails-01.json", "guardrails-02.json", "identity-03.json"],
        "identity_03_contains_required_deny_supplements": True,
        "source_sha256": {name: hashlib.sha256(raw).hexdigest() for name, raw in original_bytes.items()},
        "source_canonical_sha256": dict(BASELINE_CANONICAL_SHA256),
        "proposed_sha256": {name: hashlib.sha256(output_bytes[name]).hexdigest() for name in POLICY_FILES},
        "json_pointer_diff": "changes.json", "unified_diffs": diff_names,
        "role_specific_boundary_guards_unchanged": all(item["unchanged"] for item in pointer_diff["boundary_guard_evidence"]),
        "root_aliases": list(ALIASES),
        "cleanup_condition": "Null iam:PermissionsBoundary=true means missing context, not proof that a role does not exist.",
        "cleanup_tradeoff": "An existing unbounded root role with the same reserved name could lose only an allowlisted managed policy. Existing bounded root roles and every other root-role mutation remain denied.",
        "required_owner_checks": [
            "Compare the original local policy documents with current live policy versions; this helper cannot read IAM.",
            "Review both changed existing policy versions together; preserve all five required policy attachments.",
            "Verify all five reserved role names are absent immediately before any separately approved deployment retry.",
            "The identity-03 part now contains mandatory denials as well as allows; it must remain attached.",
            "Policy application and change-set preparation/execution each require their own authorization.",
        ],
        "boundary_removal_and_policy_version_denials_preserved": True,
        "api_protections_unchanged": True, "deployment_authorized": False,
    }
    if source_review_raw is not None:
        review["source_review_sha256"] = hashlib.sha256(source_review_raw).hexdigest()
    output_bytes["review.json"] = encoded(review)
    # Validate everything and recheck immutable inputs before the first write.
    for name, raw in original_bytes.items():
        if safe_path(source / name).read_bytes() != raw:
            raise ValueError("An original policy changed during preparation; no output written.")
    if source_review_raw is not None and safe_path(source_review).read_bytes() != source_review_raw:
        raise ValueError("Original review metadata changed during preparation; no output written.")
    safe_path(output)
    output.mkdir(mode=0o700)
    for name, raw in output_bytes.items():
        path = safe_path(output / name)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
    return review


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        review = write_repair(args.source_dir, args.output_dir)
    except (ValueError, OSError) as error:
        parser.exit(1, "Offline repair preparation refused: " + str(error) + "\n")
    print(json.dumps({"status": review["status"], "changed_parts": review["changed_parts"],
                      "unchanged_parts_byte_identical": review["unchanged_parts_byte_identical"],
                      "compact_sizes": review["compact_sizes"], "aws_calls": 0,
                      "output_directory": review["output_directory"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
