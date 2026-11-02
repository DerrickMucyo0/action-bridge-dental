"""Offline checks of the two-policy repair against an immutable legacy bundle."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import test_staging_role_lifecycle as LIFECYCLE


HERE = Path(__file__).resolve().parents[1] / "staging"


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


EXECUTION = module("execution_repair_reference", "build-execution-policy.py")
REPAIR = module("execution_repair_proposal", "prepare-execution-repair.py")
API = "l52iwors8c"
CONFIG = EXECUTION.manifest()
ROLES = ["arn:aws:iam::631367363628:role" + CONFIG["role_path"] + CONFIG["functions"][key]["role_name"]
         for key in EXECUTION.FUNCTIONS]
ALIASES = {"arn:aws:iam::631367363628:role/" + CONFIG["functions"][key]["role_name"]
           for key in EXECUTION.FUNCTIONS}


def only_alias_resources(statement):
    resource = statement.get("Resource", [])
    resource = [resource] if isinstance(resource, str) else resource
    return bool(resource) and set(resource).issubset(ALIASES)


def legacy_bundle():
    """Reconstruct the public pre-repair documents without reading .staging."""
    result = {}
    for label, document in (("identity", EXECUTION.backend_policy(API)),
                            ("guardrails", EXECUTION.guardrail_policy(API))):
        document = copy.deepcopy(document)
        document["Statement"] = [s for s in document["Statement"] if not only_alias_resources(s)]
        for statement in document["Statement"]:
            if statement.get("Action") == "iam:*" and "NotResource" in statement:
                statement["NotResource"] = list(ROLES)
            # Reconstruct the immutable pre-third-deployment mapping grants;
            # the current generator has a separately reviewed cleanup repair.
            if statement.get("Effect") == "Allow" and statement.get("Action") == [
                    "lambda:GetEventSourceMapping", "lambda:UpdateEventSourceMapping", "lambda:DeleteEventSourceMapping"]:
                statement["Resource"] = "arn:aws:lambda:us-east-2:631367363628:event-source-mapping:*"
            if statement.get("Effect") == "Deny" and statement.get("Action") == ["lambda:UpdateEventSourceMapping"] and "NotResource" in statement:
                statement["Action"] = ["lambda:GetEventSourceMapping", "lambda:UpdateEventSourceMapping", "lambda:DeleteEventSourceMapping"]
        for index, part in enumerate(EXECUTION.parts(document), 1):
            result[f"{label}-{index:02d}.json"] = part
    assert len(result) == 5
    return result


class MinimalRepairLifecycleTests(LIFECYCLE.StagingRoleLifecycleTests):
    """Run the complete lifecycle matrix against the exact owner proposal too."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The parent matrix uses a fictional API ID; use that same selector in
        # the locally evaluated proposal after validating its pinned target.
        repaired = REPAIR.repair_documents(legacy_bundle())
        cls.documents = []
        for name in sorted(repaired):
            document = json.loads(json.dumps(repaired[name]).replace(API, "a1b2c3d4e5"))
            cls.documents.append(document)


class StagingExecutionRepairTests(unittest.TestCase):
    def test_exactly_two_documents_change_without_mutating_the_baseline(self):
        original = legacy_bundle()
        before = copy.deepcopy(original)
        repaired = REPAIR.repair_documents(original)
        self.assertEqual(original, before)
        self.assertEqual(set(repaired), set(original))
        self.assertEqual({name for name in original if original[name] != repaired[name]},
                         {"guardrails-01.json", "identity-03.json"})
        for document in repaired.values():
            self.assertLessEqual(EXECUTION.compact_size(document), 6144)

    def test_guardrail_and_identity_changes_are_exactly_bounded(self):
        original = legacy_bundle()
        repaired = REPAIR.repair_documents(original)
        old_guard = original["guardrails-01.json"]["Statement"]
        new_guard = repaired["guardrails-01.json"]["Statement"]
        old_global = old_guard[5]
        globals_ = [s for s in new_guard if s.get("Action") == "iam:*" and "NotResource" in s]
        self.assertEqual(len(globals_), 1)
        self.assertEqual(set(globals_[0]["NotResource"]), set(old_global["NotResource"]) | ALIASES)
        for statement in old_guard:
            if "iam:PermissionsBoundary" in statement.get("Condition", {}).get("ArnNotEquals", {}):
                self.assertIn(statement, new_guard)
        old_identity = original["identity-03.json"]["Statement"]
        added = repaired["identity-03.json"]["Statement"][len(old_identity):]
        self.assertEqual(repaired["identity-03.json"]["Statement"][:len(old_identity)], old_identity)
        self.assertEqual(len(added), 5)
        self.assertEqual(sum(s["Effect"] == "Allow" for s in added), 3)
        self.assertEqual(sum(s["Effect"] == "Deny" for s in added), 2)

    def test_drift_in_any_baseline_policy_fails_closed(self):
        for name in legacy_bundle():
            with self.subTest(policy=name):
                drifted = legacy_bundle()
                drifted[name]["Statement"].append({"Effect": "Allow", "Action": "*", "Resource": "*"})
                with self.assertRaises((ValueError, AssertionError)):
                    REPAIR.repair_documents(drifted)
        incomplete = legacy_bundle()
        incomplete.pop("guardrails-02.json")
        with self.assertRaises((ValueError, AssertionError)):
            REPAIR.repair_documents(incomplete)

    def test_exclusive_output_preserves_original_and_unchanged_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            source, target = base / "original", base / "repair"
            source.mkdir()
            for name, document in legacy_bundle().items():
                # Use valid alternate formatting to prove unchanged files copy
                # byte-for-byte, while validation compares canonical JSON.
                (source / name).write_text(json.dumps(document, indent=3) + "\n")
            before = {p.name: p.read_bytes() for p in source.iterdir()}
            REPAIR.write_repair(source, target)
            self.assertEqual({p.name: p.read_bytes() for p in source.iterdir()}, before)
            for name in ("identity-01.json", "identity-02.json", "guardrails-02.json"):
                self.assertEqual((target / name).read_bytes(), before[name])
            written = {p.name: p.read_bytes() for p in target.iterdir()}
            with self.assertRaises((ValueError, FileExistsError)):
                REPAIR.write_repair(source, target)
            self.assertEqual({p.name: p.read_bytes() for p in target.iterdir()}, written)

    def test_symlink_source_or_output_is_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            source, actual = base / "original", base / "actual"
            source.mkdir()
            actual.mkdir()
            for name, document in legacy_bundle().items():
                (source / name).write_text(json.dumps(document))
            linked = base / "linked"
            linked.symlink_to(actual, target_is_directory=True)
            with self.assertRaises((ValueError, FileExistsError)):
                REPAIR.write_repair(source, linked / "repair")
            self.assertEqual(list(actual.iterdir()), [])
            policy = source / "identity-01.json"
            moved = base / "identity.json"
            policy.rename(moved)
            policy.symlink_to(moved)
            with self.assertRaises(ValueError):
                REPAIR.write_repair(source, base / "repair")
            self.assertFalse((base / "repair").exists())

    def test_review_patches_exactly_reconstruct_both_replacements(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            source, target = base / "original", base / "repair"
            source.mkdir()
            original = legacy_bundle()
            for name, document in original.items():
                (source / name).write_text(json.dumps(document))
            review = REPAIR.write_repair(source, target)
            self.assertEqual(review["status"], "UNAPPLIED")
            self.assertFalse(review["live_policy_changes_performed"])
            self.assertFalse(review["new_policy_attachments_required"])
            patches = json.loads((target / "changes.json").read_text())["patches"]
            for name, operations in patches.items():
                actual = copy.deepcopy(original[name])
                for operation in operations:
                    parts = operation["path"].lstrip("/").split("/")
                    parent = actual
                    for part in parts[:-1]:
                        parent = parent[int(part)] if isinstance(parent, list) else parent[part]
                    key = int(parts[-1]) if isinstance(parent, list) and parts[-1] != "-" else parts[-1]
                    if "old_value" in operation:
                        self.assertEqual(parent[key], operation["old_value"])
                    if operation["op"] == "replace":
                        parent[key] = operation["value"]
                    elif operation["op"] == "remove":
                        del parent[key]
                    elif operation["op"] == "add" and key == "-":
                        parent.append(operation["value"])
                    else:
                        self.fail("Unsupported review patch operation")
                self.assertEqual(actual, json.loads((target / name).read_text()))

    def test_helper_has_no_aws_network_or_private_parameter_dependencies(self):
        tree = ast.parse((HERE / "prepare-execution-repair.py").read_text())
        imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imports |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        self.assertFalse(imports & {"boto3", "botocore", "subprocess", "socket", "urllib", "requests"})


if __name__ == "__main__":
    unittest.main()
