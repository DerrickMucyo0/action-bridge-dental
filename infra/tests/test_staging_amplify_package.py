import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

SPEC = importlib.util.spec_from_file_location("amplify_package", Path(__file__).resolve().parents[1] / "staging/package-amplify.py")
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)


class AmplifyPackageTests(unittest.TestCase):
    def build(self, root):
        dist = root / "dist"
        dist.mkdir()
        (dist / "index.html").write_text('<html><script src="/assets/app.js"></script></html>')
        (dist / "assets").mkdir()
        (dist / "assets/app.js").write_text('const config={apiBaseUrl:"' + P.PUBLIC['VITE_API_BASE_URL'] +
            '",cognitoClientId:"' + P.PUBLIC['VITE_COGNITO_CLIENT_ID'] +
            '",cognitoRegion:"us-east-2",backgroundJobsEnabled:"false",publicAccountActionsEnabled:"false"};')
        return dist

    def test_zip_root_determinism_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dist = self.build(root)
            a = P.package(dist, root / "a")
            b = P.package(dist, root / "b")
            self.assertEqual(a["zip_sha256"], b["zip_sha256"])
            with zipfile.ZipFile(root / "a/frontend.zip") as archive:
                self.assertIn("index.html", archive.namelist())
                self.assertNotIn("dist/index.html", archive.namelist())
            with self.assertRaises(ValueError):
                P.package(dist, root / "a")

    def test_symlinks_secrets_maps_and_wrong_bundle_are_blocked(self):
        for bad in ("link", "private.pem", "app.js.map", ".env", "credential.js", "wrong-client", "jobs-enabled"):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                dist = self.build(root)
                if bad == "link":
                    (dist / "assets/link.js").symlink_to(dist / "assets/app.js")
                elif bad == "credential.js":
                    (dist / bad).write_text("-----BEGIN PRIVATE KEY-----")
                elif bad == "wrong-client":
                    (dist / "assets/app.js").write_text("unrelated client build")
                elif bad == "jobs-enabled":
                    js = dist / "assets/app.js"
                    js.write_text(js.read_text().replace('"false"', '"true"'))
                else:
                    (dist / bad).write_text("synthetic forbidden file")
                with self.assertRaises(ValueError):
                    P.package(dist, root / "output")
                self.assertFalse((root / "output").exists())

    def test_public_account_gate_must_be_false_in_the_actual_config(self):
        for mode in ("enabled", "missing", "unrelated-false"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                dist = self.build(root)
                js = dist / "assets/app.js"
                original = js.read_text()
                if mode == "missing":
                    changed = original.replace(',publicAccountActionsEnabled:"false"', "")
                else:
                    changed = original.replace('publicAccountActionsEnabled:"false"', 'publicAccountActionsEnabled:"true"')
                    if mode == "unrelated-false":
                        changed += '\nconst unrelated={publicAccountActionsEnabled:"false"};'
                js.write_text(changed)
                with self.assertRaises(ValueError):
                    P.package(dist, root / "output")
                self.assertFalse((root / "output").exists())

    def test_manifest_records_the_restricted_account_build_binding(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = P.package(self.build(root), root / "output")
            self.assertEqual(manifest["public_build_configuration"]["VITE_PUBLIC_ACCOUNT_ACTIONS_ENABLED"], "false")


if __name__ == "__main__":
    unittest.main()
