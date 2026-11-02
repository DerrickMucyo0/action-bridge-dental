"""Local ZIP integrity and preservation checks using synthetic bundles only."""
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parents[1] / "staging"
SPEC = importlib.util.spec_from_file_location("staging_artifacts", HERE / "package-artifacts.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MANIFEST = json.loads((HERE / "resources.json").read_text())


class StagingArtifactTests(unittest.TestCase):
    def fixtures(self, root):
        bundles = root / "bundles"
        for slug in MODULE.SLUGS.values():
            path = bundles / slug
            path.mkdir(parents=True)
            (path / "index.mjs").write_text("export const handler = async () => ({statusCode: 200});\n")
        return bundles

    def test_all_zip_digests_keys_and_parameters_match_template_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            bundles = self.fixtures(root)
            output = root / "artifacts"
            parameters = MODULE.package(bundles, output, MANIFEST)
            self.assertEqual(len(parameters), 5)
            self.assertEqual({item["ParameterKey"] for item in parameters}, {"HealthArtifactKey", "CasesArtifactKey", "CalculationsArtifactKey", "JobsArtifactKey", "JobWorkerArtifactKey"})
            for item in parameters:
                slug, name = item["ParameterValue"].removeprefix(MANIFEST["artifact_prefix"]).split("/")
                content = (output / slug / name).read_bytes()
                self.assertEqual(name, hashlib.sha256(content).hexdigest() + ".zip")
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    self.assertEqual(archive.namelist(), ["index.mjs"])
                    self.assertEqual(archive.read("index.mjs"), (bundles / slug / "index.mjs").read_bytes())
            self.assertEqual(MODULE.package(bundles, output, MANIFEST), parameters)

    def test_changed_build_refuses_to_overwrite_existing_parameter_record(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            bundles = self.fixtures(root)
            output = root / "artifacts"
            MODULE.package(bundles, output, MANIFEST)
            before = (output / "artifact-parameters.json").read_bytes()
            (bundles / "health" / "index.mjs").write_text("export const handler = 1;\n")
            with self.assertRaisesRegex(ValueError, "Existing artifact"):
                MODULE.package(bundles, output, MANIFEST)
            self.assertEqual((output / "artifact-parameters.json").read_bytes(), before)

    def test_missing_build_and_symlinks_fail_before_any_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            bundles = self.fixtures(root)
            (bundles / "jobs" / "index.mjs").unlink()
            with self.assertRaises(ValueError):
                MODULE.package(bundles, root / "output", MANIFEST)
            self.assertFalse((root / "output").exists())
            (bundles / "jobs" / "index.mjs").symlink_to(bundles / "health" / "index.mjs")
            with self.assertRaisesRegex(ValueError, "symlink"):
                MODULE.package(bundles, root / "output", MANIFEST)
            self.assertFalse((root / "output").exists())


if __name__ == "__main__":
    unittest.main()
