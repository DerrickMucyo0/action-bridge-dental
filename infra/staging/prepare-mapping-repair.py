#!/usr/bin/env python3
"""Prepare the two-field staging mapping cleanup repair offline; never apply it.

Accept only the exact five reviewed policy documents after the identity-03 V3
and guardrails-01 V2 corrections. Preserve three parts byte-for-byte. Output is
exclusive and includes the precise JSON patches; live IAM provenance is an
independent owner check, never inferred from these local files.
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
WORKER = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{STACK}-job-worker"
MAPPING = f"arn:aws:lambda:{REGION}:{ACCOUNT}:event-source-mapping:*"
FILES = ("identity-01.json", "identity-02.json", "identity-03.json", "guardrails-01.json", "guardrails-02.json")
CHANGED = ("identity-02.json", "guardrails-02.json")
UNCHANGED = tuple(name for name in FILES if name not in CHANGED)
PINS = {
    "identity-01.json": "65e4ac6a87ea0b1a1bf8b44f93c9836a894c988608119268b6bc7709d15e8d5b",
    "identity-02.json": "9b8c407018993fe2b02cff4304faa112214d34b6246afda7027c5e8818895c5f",
    "identity-03.json": "f7e85dadbf01bbf7553985822d343b0f96e959f20e785558f64386fc2df3ce9b",
    "guardrails-01.json": "8815922e7b6376f1b063eaa0d613a6923f95e6e40ccdf5f376961dceb996efbd",
    "guardrails-02.json": "0135b38399772f472d2b8d8d267ebdef5b83dc17a10ef05cf92418b6ad615a07",
}


def canonical_sha256(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def compact_size(document):
    return len(json.dumps(document, separators=(",", ":")))


def encoded(document):
    return (json.dumps(document, indent=2) + "\n").encode()


def repair_documents(original):
    if not isinstance(original, dict) or set(original) != set(FILES):
        raise ValueError("Exactly five reviewed policy parts are required.")
    for name in FILES:
        if canonical_sha256(original[name]) != PINS[name]:
            raise ValueError("Reviewed post-V3 baseline mismatch: " + name)
    identity = original["identity-02.json"]["Statement"][4]
    expected = {"Effect": "Allow", "Action": ["lambda:GetEventSourceMapping", "lambda:UpdateEventSourceMapping", "lambda:DeleteEventSourceMapping"],
                "Resource": MAPPING, "Condition": {"StringEquals": {"aws:RequestedRegion": REGION}, "ArnEquals": {"lambda:FunctionArn": WORKER}}}
    if identity != expected:
        raise ValueError("Unexpected event-source-mapping identity grant.")
    guard = original["guardrails-02.json"]["Statement"][9]
    if guard != {"Effect": "Deny", "Action": expected["Action"], "NotResource": MAPPING}:
        raise ValueError("Unexpected mapping resource isolation denial.")
    repaired = copy.deepcopy(original)
    repaired["identity-02.json"]["Statement"][4]["Resource"] = "*"
    repaired["guardrails-02.json"]["Statement"][9]["Action"] = ["lambda:UpdateEventSourceMapping"]
    if {name for name in FILES if original[name] != repaired[name]} != set(CHANGED):
        raise ValueError("An unexpected policy part changed.")
    if any(compact_size(repaired[name]) > 6144 for name in FILES):
        raise ValueError("A policy exceeds the managed-policy size quota.")
    return repaired


def safe_path(path):
    result = Path(path).absolute()
    if any(part.is_symlink() for part in (result, *result.parents)):
        raise ValueError("Refusing a source/output path containing a symlink.")
    return result.resolve()


def write_repair(source_dir, output_dir):
    source, output = safe_path(source_dir), safe_path(output_dir)
    if output.exists() or source == output or source in output.parents:
        raise ValueError("Output must be a new directory outside the source directory.")
    original_bytes = {name: safe_path(source / name).read_bytes() for name in FILES}
    original = {name: json.loads(raw) for name, raw in original_bytes.items()}
    repaired = repair_documents(original)
    output_bytes = {name: original_bytes[name] if name in UNCHANGED else encoded(repaired[name]) for name in FILES}
    patches = {
        "identity-02.json": [{"op": "replace", "path": "/Statement/4/Resource", "old_value": MAPPING, "value": "*"}],
        "guardrails-02.json": [{"op": "replace", "path": "/Statement/9/Action",
                                "old_value": original["guardrails-02.json"]["Statement"][9]["Action"],
                                "value": ["lambda:UpdateEventSourceMapping"]}],
    }
    output_bytes["changes.json"] = encoded({"patches": patches, "unchanged_parts": list(UNCHANGED)})
    for name in CHANGED:
        output_bytes[name.removesuffix(".json") + ".diff"] = "".join(difflib.unified_diff(
            original_bytes[name].decode().splitlines(keepends=True), output_bytes[name].decode().splitlines(keepends=True),
            fromfile="reviewed-post-v3/" + name, tofile="proposed-unapplied/" + name)).encode()
    review = {
        "status": "UNAPPLIED_REQUIRES_OWNER_REVIEW_AND_MAPPING_STATE_CHECK", "aws_calls": 0,
        "account": ACCOUNT, "region": REGION, "stack_name": STACK, "api_id": API,
        "changed_parts": list(CHANGED), "unchanged_parts": list(UNCHANGED),
        "unchanged_parts_byte_identical": all(output_bytes[n] == original_bytes[n] for n in UNCHANGED),
        "source_directory": str(source), "output_directory": str(output),
        "source_canonical_sha256": dict(PINS),
        "proposed_canonical_sha256": {name: canonical_sha256(repaired[name]) for name in FILES},
        "compact_sizes": {name: compact_size(repaired[name]) for name in FILES},
        "live_source_documents_verified": False, "live_IAM_changes": 0,
        "new_policies_or_attachments_required": False, "deployment_authorized": False,
        "preserved_controls": ["Exact staging worker FunctionArn required for all four mapping actions",
                               "Missing or different FunctionArn explicitly denied",
                               "Requests outside Ohio explicitly denied",
                               "Update retains regional event-source-mapping ARN guard",
                               "All IAM role/boundary, API, production and business-data guards unchanged"],
        "limitation": "AWS failure identifies Resource '*' but does not disclose lambda:FunctionArn context. This repair authorizes Get/Delete only when the exact staging worker context is present. Missing context remains explicitly denied; no UUID-scoped wildcard fallback condition is available.",
        "required_owner_actions": ["Compare current live identity-02 and guardrails-02 documents with the pinned originals before applying the two replacements together under separate approval.",
                                   "Use an existing authorized read-only session to check mapping 35d44f01-0d10-4bae-9a76-60cd087e6d5e if developer reads remain denied; do not delete automatically.",
                                   "Do not prepare or execute another deployment until mapping state and permission context are resolved."],
        "sources": ["https://docs.aws.amazon.com/service-authorization/latest/reference/list_lambda.html",
                    "https://docs.aws.amazon.com/lambda/latest/dg/lambda-api-permissions-ref.html"],
    }
    output_bytes["review.json"] = encoded(review)
    for name, raw in original_bytes.items():
        if safe_path(source / name).read_bytes() != raw:
            raise ValueError("Source changed during preparation; no output written.")
    output.mkdir(mode=0o700)
    for name, raw in output_bytes.items():
        fd = os.open(safe_path(output / name), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
    return review


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT / ".staging/execution-repair-minimal-l52iwors8c")
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".staging/mapping-cleanup-correction-review")
    args = parser.parse_args(argv)
    try:
        review = write_repair(args.source_dir, args.output_dir)
    except (ValueError, OSError) as error:
        parser.exit(1, "Offline mapping repair refused: " + str(error) + "\n")
    print(json.dumps({key: review[key] for key in ("status", "changed_parts", "unchanged_parts_byte_identical", "compact_sizes", "output_directory", "aws_calls")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
