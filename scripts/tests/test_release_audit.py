import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import warnings
import zipfile


SCRIPT = Path(__file__).resolve().parents[1] / "release_audit.py"
SPEC = importlib.util.spec_from_file_location("release_audit", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)
ROOT = SCRIPT.parents[1]


class ReleaseAuditTests(unittest.TestCase):
    def test_public_configuration_not_secret(self):
        self.assertEqual(audit.scan_bytes(b"https://l52iwors8c.execute-api.us-east-2.amazonaws.com/staging 631367363628"), [])

    def test_aws_access_key_is_redacted(self):
        fake = b"AK" + b"IA" + b"0" * 16
        result = audit.scan_bytes(b"key=" + fake)
        self.assertEqual(result, [{"line": 1, "category": "aws-access-key-id"}])
        self.assertNotIn(fake.decode(), json.dumps(result))

    def test_temporary_access_key_is_redacted(self):
        self.assertEqual(audit.scan_bytes(b"AS" + b"IA" + b"A" * 16)[0]["category"], "aws-access-key-id")

    def test_private_key_body_and_header_distinguished(self):
        header = b"-----BEGIN " + b"PRIVATE KEY-----"
        end = b"-----END " + b"PRIVATE KEY-----"
        self.assertEqual(audit.scan_bytes(header)[0]["category"], "private-key-header-without-body-candidate")
        self.assertEqual(audit.scan_bytes(header + b"\nfictional\n" + end)[0]["category"], "private-key")

    def test_provider_token_is_redacted(self):
        fake = b"gh" + b"p_" + b"A" * 36
        self.assertEqual(audit.scan_bytes(fake)[0]["category"], "provider-token")
        self.assertNotIn(fake.decode(), json.dumps(audit.scan_bytes(fake)))

    def test_url_credentials_are_redacted(self):
        data = b"https://fictional:fictional@invalid.example/path"
        self.assertEqual(audit.scan_bytes(data)[0]["category"], "url-embedded-credential")

    def test_shared_inline_credentials_without_email(self):
        data = b"**Try it:** `fictional-user` / `fictional-pass`"
        self.assertEqual(audit.scan_bytes(data, True)[0]["category"], "shared-account-inline-candidate")
        self.assertNotIn("fictional-pass", json.dumps(audit.scan_bytes(data, True)))

    def test_minified_js_does_not_use_prose_heuristic(self):
        self.assertEqual(audit.scan_bytes(b'const x="password";`a`;`b`'), [])

    def test_binary_is_explicitly_not_text_scanned(self):
        self.assertEqual(audit.scan_bytes(b"\0" + b"AK" + b"IA" + b"A" * 16), [])

    def make_archive(self, target, changed=None, excluded=None, extra=None):
        with zipfile.ZipFile(target, "x") as archive:
            archive.writestr("index.html", "<html></html>")
            for name in audit.NOTICE_FILES:
                if name != excluded:
                    data = (ROOT / "web/public" / name).read_bytes()
                    archive.writestr(name, b"tampered" if name == changed else data)
            if extra:
                archive.writestr(extra, "fictional")

    def test_notices_must_be_present(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidate.zip"
            self.make_archive(path, excluded="licenses/geist-OFL.txt")
            result = audit.audit_archive(path)
            self.assertEqual(result["artifact_gate"], "FAIL")
            self.assertIn("licenses/geist-OFL.txt", result["missing_notices"])

    def test_notices_must_match_verified_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidate.zip"
            self.make_archive(path, changed="licenses/geist-OFL.txt")
            result = audit.audit_archive(path)
            self.assertEqual(result["artifact_gate"], "FAIL")
            self.assertIn("licenses/geist-OFL.txt", result["notice_hash_mismatches"])

    def test_complete_clean_archive_passes_artifact_gate_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidate.zip"
            self.make_archive(path)
            self.assertEqual(audit.audit_archive(path)["artifact_gate"], "PASS")

    def test_archive_paths_cannot_escape_or_hide(self):
        for extra in ["../outside.txt", "/absolute.txt", ".env", "..\\outside.txt", "C:/outside.txt", "control\x01.txt"]:
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "candidate.zip"
                self.make_archive(path, extra=extra)
                result = audit.audit_archive(path)
                self.assertEqual(result["artifact_gate"], "FAIL")
                self.assertIn(extra, result["unsafe_paths"])

    def test_archive_duplicate_members_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidate.zip"
            self.make_archive(path)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(path, "a") as archive:
                    archive.writestr("index.html", "different")
            result = audit.audit_archive(path)
            self.assertEqual(result["artifact_gate"], "FAIL")
            self.assertEqual(result["duplicate_paths"], ["index.html"])

    def test_history_scan_preserves_git_and_finds_deleted_credential(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            def git(*args):
                return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout
            git("init", "-q")
            git("config", "user.name", "Fictional test author")
            git("config", "user.email", "fixture@invalid.example")
            page = repo / "README.md"
            page.write_text("**Try it:** `fictional-user` / `fictional-pass`\n")
            git("add", "README.md")
            git("commit", "-qm", "Fictional fixture")
            page.write_text("Request private access.\n")
            git("add", "README.md")
            git("commit", "-qm", "Remove fictional fixture")
            before = (git("rev-parse", "HEAD"), git("status", "--porcelain"))
            self.assertEqual(audit.audit_current(repo)["findings"], [])
            result = audit.audit_history(repo)
            self.assertEqual(len(result["findings"]), 1)
            self.assertEqual(result["findings"][0]["path"], "README.md")
            self.assertEqual(len(result["findings"][0]["change_commits"]), 2)
            self.assertNotIn("fictional-pass", json.dumps(result))
            self.assertEqual(before, (git("rev-parse", "HEAD"), git("status", "--porcelain")))


if __name__ == "__main__":
    unittest.main()
