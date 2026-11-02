import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1] / "staging"
SPEC = importlib.util.spec_from_file_location("delegated_preflight", HERE / "verify-delegated-access.py")
V = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V)


class DelegatedPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_staging_http_stage_tagging as TAGGING
        cls._temp_dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._temp_dir.cleanup)
        source = Path(cls._temp_dir.name)
        proposed = TAGGING.PROPOSAL.proposal_documents(TAGGING.PREVIOUS.recovery_a_baseline())
        for name, policy in proposed.items():
            (source / name).write_text(json.dumps(policy, indent=2) + "\n")
        patcher = patch.object(V.D, "POLICY_SOURCE", source)
        patcher.start()
        cls.addClassCleanup(patcher.stop)

    def test_root_other_profiles_static_overrides_and_user_sessions_fail_before_network(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config"
            with patch.dict(os.environ, {"AWS_CONFIG_FILE": str(config)}, clear=True):
                for profile, login in (("actionbridge-staging", "arn:aws:iam::631367363628:root"),
                                       ("actionbridge-staging-deployer", "arn:aws:iam::631367363628:root"),
                                       ("actionbridge-staging-deployer", V.D.DEVELOPER)):
                    config.write_text(f"[profile {profile}]\nlogin_session = {login}\n")
                    with self.subTest(login=login), self.assertRaises(ValueError), patch.object(V.subprocess, "run") as run:
                        V.AwsReads(profile)
                    run.assert_not_called()
                config.write_text(f"[profile actionbridge-staging-deployer]\nlogin_session = {V.D.DEPLOYER}\n")
                with patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "synthetic-placeholder"}), self.assertRaises(ValueError):
                    V.AwsReads("actionbridge-staging-deployer")

    def test_write_operations_are_rejected_and_no_fallback_or_retry_is_available(self):
        with patch.object(V, "validate_profile"):
            reader = V.AwsReads("actionbridge-staging-deployer")
        for service, action in (("iam", "create-policy-version"), ("cloudformation", "execute-change-set"),
                                ("cloudformation", "continue-update-rollback"), ("s3api", "put-object"), ("amplify", "start-deployment")):
            with self.assertRaises(ValueError), patch.object(V.subprocess, "run") as run:
                reader(service, action)
            run.assert_not_called()

    def test_concurrent_login_cache_use_is_rejected_before_starting_cli(self):
        with patch.object(V, "validate_profile"):
            reader = V.AwsReads("actionbridge-staging-deployer")
        with patch.object(V.fcntl, "flock", side_effect=BlockingIOError), patch.object(V.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "serialize calls"):
                reader("sts", "get-caller-identity")
            run.assert_not_called()

    def test_aws_reads_ignore_configured_endpoint_overrides(self):
        with patch.object(V, "validate_profile"):
            reader = V.AwsReads("actionbridge-staging-deployer")
        result = V.subprocess.CompletedProcess(args=[], returncode=0, stdout='{}', stderr='')
        with patch.object(V.subprocess, "run", return_value=result) as run:
            self.assertEqual(reader("sts", "get-caller-identity"), {})
        self.assertEqual(run.call_args.kwargs["env"]["AWS_IGNORE_CONFIGURED_ENDPOINT_URLS"], "true")
        self.assertEqual(run.call_args.kwargs["env"]["AWS_MAX_ATTEMPTS"], "1")

    def test_exact_staging_branch_absence_is_accepted_without_listing_or_hiding_denials(self):
        def absent(*args):
            self.assertEqual(args, ("amplify", "get-branch", "--app-id", "synthetic", "--branch-name", "staging"))
            raise V.AwsReadError("amplify", "get-branch", "NotFoundException")
        V.require_unpublished_staging_branch(absent, "synthetic")
        for code in ("AccessDeniedException", "ThrottlingException", "CLI_AUTH_OR_TRANSPORT_ERROR"):
            with self.subTest(code=code), self.assertRaises(V.AwsReadError):
                V.require_unpublished_staging_branch(lambda *args: (_ for _ in ()).throw(V.AwsReadError("amplify", "get-branch", code)), "synthetic")
        with self.assertRaisesRegex(ValueError, "already exists"):
            V.require_unpublished_staging_branch(lambda *args: {"branch": {}}, "synthetic")

    def test_wrong_account_or_root_identity_stops_before_further_reads(self):
        for identity in ({"Account": "195469705669", "Arn": "arn:aws:iam::195469705669:root"},
                         {"Account": V.D.ACCOUNT, "Arn": f"arn:aws:iam::{V.D.ACCOUNT}:root"},
                         {"Account": V.D.ACCOUNT, "Arn": V.D.DEVELOPER}):
            calls = []
            def read(*args):
                calls.append(args)
                return identity
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / "access-stack.json").write_text(json.dumps(V.D.access_template()))
                with self.assertRaises(ValueError):
                    V.verify(read, root)
            self.assertEqual(calls, [("sts", "get-caller-identity")])

    def test_unexpected_default_version_metadata_fails_closed(self):
        arn = V.D.EDITABLE[0]
        def read(service, action, *args):
            if action == "get-policy":
                return {"Policy": {"Arn": arn, "DefaultVersionId": "v4"}}
            if action == "list-policy-versions":
                return {"Versions": [{"VersionId": "v3", "IsDefaultVersion": True}]}
            return {"PolicyVersion": {"Document": {"Version": "2012-10-17", "Statement": []}}}
        with self.assertRaises(ValueError):
            V.default_policy(read, arn)

    def test_live_owner_policy_resolution_keeps_exact_app_and_stack_scope(self):
        app = f"arn:aws:amplify:{V.D.REGION}:{V.D.ACCOUNT}:apps/synthetic"
        stack = f"arn:aws:cloudformation:{V.D.REGION}:{V.D.ACCOUNT}:stack/{V.D.ACCESS_STACK}/synthetic"
        result = V.resolve_policy(V.D.deployer_policy(), app, stack)
        self.assertNotIn("Fn::", json.dumps(result))
        self.assertNotIn('"Ref"', json.dumps(result))
        self.assertIn(app + "/branches/staging", json.dumps(result))
        self.assertIn(stack, json.dumps(result))
        with self.assertRaises(ValueError):
            V.resolve_policy({"Ref": "Unknown"}, app, stack)


if __name__ == "__main__":
    unittest.main()
