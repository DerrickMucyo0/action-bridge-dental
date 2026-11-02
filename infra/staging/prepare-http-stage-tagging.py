#!/usr/bin/env python3
"""Prepare the reviewed, recognized HTTP tagging proposal locally; no AWS calls.

Copy the owner's Console-validated policy bytes exactly. This changes the tenth
identity statement narrowly; it does not satisfy an unchanged-ten constraint.
Scope/action checks do not prove the provider's tagged CreateStage request will
succeed. No policy application, change set, deployment, or traffic is authorized.
"""
import argparse
import copy
import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from urllib.parse import quote


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("http_tagging_strict_utilities", HERE / "prepare-core-forward-repair.py")
STRICT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STRICT)
ROOT, FILES, PINS = STRICT.ROOT, STRICT.FILES, dict(STRICT.PINS)
API, STAGE, REGION = STRICT.API, STRICT.STAGE, STRICT.REGION
TAGS = f"arn:aws:apigateway:{REGION}::/tags/" + quote(STAGE, safe="")
METHODS = ["apigateway:GET", "apigateway:PATCH", "apigateway:POST", "apigateway:PUT", "apigateway:DELETE"]
CHANGED = ("identity-03.json", "guardrails-02.json")
UNCHANGED = tuple(name for name in FILES if name not in CHANGED)
COUNTER_CANONICAL = {"identity-03.json": "027627a200647da9ede5b55a5a1a4793d3ac9aff9742262f1451dd5dbc0e4e37",
                     "guardrails-02.json": "1332e1cee527d366903730d258558bbd2a2aecd3cf60e206b685d23b610efdba"}
COUNTER_RAW = {"identity-03.json": "bbe5d560e4a6d61d1e92323afa005cd7a5ebafbf7c5dd56b35deabe6e0bfc5f4",
               "guardrails-02.json": "5ac45fcaaf967fe8cfdc5d42036af58b046d8de5d96ac9953d0db7edd36a8f2c"}


def proposal_documents(original):
    STRICT.validate_original(original)
    result = copy.deepcopy(original)
    result["identity-03.json"]["Statement"][9]["NotResource"].append(TAGS)
    result["identity-03.json"]["Statement"].append({"Effect": "Allow", "Action": list(METHODS), "Resource": TAGS,
                                                  "Condition": {"StringEquals": {"aws:RequestedRegion": REGION}}})
    guards = result["guardrails-02.json"]["Statement"]
    if guards[1]["NotResource"] != guards[2]["NotResource"] or set(guards[1]) != {"Effect", "Action", "NotResource"} or set(guards[2]) != set(guards[1]):
        raise ValueError("Equivalent Lambda Deny scopes cannot be verified.")
    guards[1]["Action"] += guards[2]["Action"]
    del guards[2]
    guards[6]["NotResource"].append(TAGS)
    if result["identity-03.json"]["Statement"][:9] != original["identity-03.json"]["Statement"][:9]:
        raise ValueError("An original first-nine identity statement changed.")
    if any(STRICT.canonical_sha256(result[name]) != digest for name, digest in COUNTER_CANONICAL.items()):
        raise ValueError("The proposal differs from the exact reviewed HTTP counterproposal.")
    if any(STRICT.compact_size(result[name]) > 6144 for name in FILES):
        raise ValueError("A proposal exceeds the managed-policy size quota.")
    return result


def proposal_patches(original, proposed):
    return {
        "identity-03.json": [{"op": "add", "path": "/Statement/9/NotResource/-", "value": TAGS},
                             {"op": "add", "path": "/Statement/-", "value": proposed["identity-03.json"]["Statement"][10]}],
        "guardrails-02.json": [{"op": "replace", "path": "/Statement/1/Action", "old_value": original["guardrails-02.json"]["Statement"][1]["Action"],
                                "value": proposed["guardrails-02.json"]["Statement"][1]["Action"]},
                               {"op": "remove", "path": "/Statement/2", "old_value": original["guardrails-02.json"]["Statement"][2]},
                               {"op": "add", "path": "/Statement/6/NotResource/-", "value": TAGS}],
    }


def validate_owner_report(report, counter_dir):
    if (not isinstance(report.get("source"), str) or not report["source"].strip()
            or report.get("independent_server_validation_by_assistant") is not False
            or report.get("live_IAM_changes_reported") is not False):
        raise ValueError("The owner report must describe unsaved Console validation, not assistant server validation or live changes.")
    for name in CHANGED:
        item = report.get("policies", {}).get(name, {})
        if (item.get("raw_sha256") != COUNTER_RAW[name] or item.get("canonical_sha256") != COUNTER_CANONICAL[name]
                or item.get("validation_reported_by_owner") is not True
                or any(type(item.get(key)) is not int or item[key] != 0 for key in ("errors", "warnings", "security_findings", "suggestions"))
                or STRICT.safe_path(item.get("path", "")) != counter_dir / name):
            raise ValueError("Owner Console validation is not bound to the exact reviewed policy: " + name)


def write_proposal(source_dir, live_review_dir, counter_dir, catalog_path, owner_report_path, output_dir):
    source, live, counter, owner_path, output = map(STRICT.safe_path, (source_dir, live_review_dir, counter_dir, owner_report_path, output_dir))
    if output.exists() or any(output == path or path in output.parents for path in (source, counter)):
        raise ValueError("Output must be a new exclusive directory outside both input bundles.")
    source_bytes = {name: STRICT.safe_path(source / name).read_bytes() for name in FILES}
    original = {name: STRICT.decode_json(raw) for name, raw in source_bytes.items()}
    proposed = proposal_documents(original)
    saved_bytes = {name: STRICT.safe_path(live / filename).read_bytes() for name, filename in STRICT.SAVED_EXPORTS.items()}
    for name, raw in saved_bytes.items():
        if STRICT.decode_json(raw) != original[name]:
            raise ValueError("Saved current policy differs from the pinned Recovery A source: " + name)
    counter_bytes = {name: STRICT.safe_path(counter / name).read_bytes() for name in FILES}
    for name, raw in counter_bytes.items():
        if STRICT.decode_json(raw) != proposed[name]:
            raise ValueError("A reviewed counterproposal document changed: " + name)
        if name in CHANGED and hashlib.sha256(raw).hexdigest() != COUNTER_RAW[name]:
            raise ValueError("Console-validated bytes changed; reformatting is not accepted: " + name)
        if name in UNCHANGED and raw != source_bytes[name]:
            raise ValueError("An unchanged counterproposal policy is not byte-identical: " + name)
    catalog = STRICT.load_authorization_catalog(catalog_path)
    for document in proposed.values():
        STRICT.validate_action_recognition(document, catalog)
    owner_bytes = owner_path.read_bytes()
    owner = STRICT.decode_json(owner_bytes)
    validate_owner_report(owner, counter)
    outputs = {name: counter_bytes[name] if name in CHANGED else source_bytes[name] for name in FILES}
    outputs["changes.json"] = STRICT.encoded({"patches": proposal_patches(original, proposed), "unchanged_parts": list(UNCHANGED),
                                             "original_first_nine_identity_statements_unchanged": True,
                                             "original_tenth_identity_statement_changed": True})
    for name in CHANGED:
        outputs[name.removesuffix(".json") + ".diff"] = "".join(difflib.unified_diff(
            source_bytes[name].decode().splitlines(keepends=True), outputs[name].decode().splitlines(keepends=True),
            fromfile="current-Recovery-A/" + name, tofile="recognized-HTTP-proposal/" + name)).encode()
    review = {
        "status": "PASS_POLICY_SECURITY_REVIEW_RUNTIME_CREATESTAGE_UNPROVEN_AWAITING_APPROVAL",
        "account": STRICT.ACCOUNT, "region": REGION, "stack_name": STRICT.STACK, "api_id": STRICT.API_ID,
        "source_directory": str(source), "counterproposal_directory": str(counter), "output_directory": str(output),
        "changed_parts": list(CHANGED), "unchanged_parts": list(UNCHANGED),
        "source_canonical_sha256": dict(PINS),
        "proposed_canonical_sha256": {name: STRICT.canonical_sha256(proposed[name]) for name in FILES},
        "proposed_raw_sha256": {name: hashlib.sha256(outputs[name]).hexdigest() for name in FILES},
        "compact_sizes": {name: STRICT.compact_size(proposed[name]) for name in FILES},
        "statement_counts": {name: len(proposed[name]["Statement"]) for name in FILES},
        "three_other_parts_byte_identical": all(outputs[name] == source_bytes[name] for name in UNCHANGED),
        "changed_parts_copy_exact_Console_validated_bytes": True,
        "original_first_nine_identity_statements_unchanged": True, "original_ten_identity_statements_unchanged": False,
        "original_identity_statement_requiring_owner_review": "/Statement/9/NotResource adds only the exact encoded staging Stage Tags ARN",
        "exact_stage_tag_ARN": TAGS,
        "recognized_HTTP_actions": list(METHODS), "official_action_catalog": catalog,
        "owner_Console_validation": {"source": owner["source"], "report_path": str(owner_path),
                                     "independent_assistant_server_validation": False,
                                     "findings_per_changed_policy": {name: {key: owner["policies"][name][key] for key in ("errors", "warnings", "security_findings", "suggestions")} for name in CHANGED}},
        "CORS_rollback_API_self_DELETE_IAM_boundaries_mapping_guards_preserved": True,
        "new_managed_policies_or_attachments_required": False,
        "actual_tagged_CreateStage_authorization_verified": False,
        "provider_schema_labels_do_not_override_IAM_catalog": True,
        "previous_literal_action_proposal_included": False,
        "live_IAM_changes": 0, "aws_calls": 0, "deployment_authorized": False, "change_set_creation_authorized": False,
        "traffic_enablement_authorized": False, "deployment_ready_claimed": False,
        "limitations": ["Owner Console validation is reported evidence for the exact copied bytes, not independent CLI/server validation by the assistant.",
                        "Local IAM scope and recognized-action checks do not prove that the provider's tagged CreateStage request will succeed.",
                        "The old requirement to preserve all ten identity statements unchanged is not satisfied; the tenth statement's narrow Tags exception requires explicit owner acceptance.",
                        "The existing API identity, disabled endpoint, template, artifacts, IAM boundaries and unrelated resources are not changed by this local preparation."],
        "next_owner_action": "Review the two existing-policy replacements and explicitly accept the narrow amendment to the tenth identity statement. No live application or deployment is authorized by this file.",
    }
    outputs["review.json"] = STRICT.encoded(review)
    for directory, old in ((source, source_bytes), (counter, counter_bytes)):
        if any(STRICT.safe_path(directory / name).read_bytes() != raw for name, raw in old.items()):
            raise ValueError("An input bundle changed during review; no output written.")
    if any(STRICT.safe_path(live / STRICT.SAVED_EXPORTS[name]).read_bytes() != raw for name, raw in saved_bytes.items()) or owner_path.read_bytes() != owner_bytes:
        raise ValueError("Saved policy/validation evidence changed during review; no output written.")
    if STRICT.load_authorization_catalog(catalog_path) != catalog:
        raise ValueError("The official action catalog changed during review; no output written.")
    output.mkdir(mode=0o700)
    for name, raw in outputs.items():
        fd = os.open(STRICT.safe_path(output / name), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
    return review


def main(argv=None):
    base = ROOT / ".staging/core-forward-deployment-review"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT / ".staging/api-recovery-review/policies-A")
    parser.add_argument("--live-review-dir", type=Path, default=ROOT / ".staging/live-policy-review")
    parser.add_argument("--counterproposal-dir", type=Path, default=base / "http-tagging-counterproposal-NOT-APPROVED")
    parser.add_argument("--authorization-catalog", type=Path, default=STRICT.DEFAULT_CATALOG)
    parser.add_argument("--owner-validation-report", type=Path, default=base / "console-validation-reported.json")
    parser.add_argument("--output-dir", type=Path, default=base / "policies-http-stage-tagging")
    args = parser.parse_args(argv)
    try:
        review = write_proposal(args.source_dir, args.live_review_dir, args.counterproposal_dir, args.authorization_catalog, args.owner_validation_report, args.output_dir)
    except (ValueError, OSError) as error:
        parser.exit(1, "Offline HTTP Stage proposal refused: " + str(error) + "\n")
    print(json.dumps({key: review[key] for key in ("status", "changed_parts", "three_other_parts_byte_identical", "changed_parts_copy_exact_Console_validated_bytes", "compact_sizes", "output_directory", "aws_calls")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
