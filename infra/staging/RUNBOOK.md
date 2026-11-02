# Independent staging backend — owner handoff

**Current status — October 26:** use [CORE_FORWARD_REPAIR.md](CORE_FORWARD_REPAIR.md).
Recovery A is complete at UPDATE_ROLLBACK_COMPLETE. The identity-only literal
tagging proposal remains withdrawn. Two recognized HTTP replacements have passed
owner-reported Console validation and combined review; live application is
unapproved and tagged CreateStage remains runtime-unproven. Do not create another
change set or deploy without separate approval. Existing API l52iwors8c is
preserved; direct API-settings reads remain restricted. Background/worker phases remain deferred.
Do not repeat the completed initial setup
below or reuse earlier change-set requests/approvals.

Target **631367363628 / us-east-2 / actionbridge-dental-staging**. Everything in
this directory is local preparation and unapplied policy/template drafts. No AWS
login, account API call, deployment, IAM change, user change, Vercel change,
commit or push was performed. Public AWS documentation was consulted only.

The owner reports 153 discovered resources, mostly default networking, with no
obvious production application infrastructure. **The inventory is incomplete.**
Existing resources, other Regions and global IAM remain outside the new backend.
The original website's backend remains in teammate account `195469705669`.

## Historical initial action: exact-name collision review (completed)

The print-only plan has already been produced. The account owner's next action is
to review and, after approval, grant the scoped customer-managed
[collision-read-policy.json](collision-read-policy.json) to the existing
`actionbridge-developer` IAM user. See
[COLLISION_CHECKS.md](COLLISION_CHECKS.md) for console steps and the
authentication/approval-gated runner. The broader preflight/deployment drafts are
not required merely to perform these 32 reads. No grant or actual read was made by
this preparation.

In this checkout, print the prepared plan using the name of an **existing,
authorized non-root administrator profile**:

```bash
python3 infra/staging/collision-checks.py --profile YOUR_AUTHORIZED_ADMIN_PROFILE
```

This program prints 32 read-only checks; it never executes AWS. **Do not pipe its
output into a shell.** The owner/administrator must approve and run the individual
reads, first confirming account `631367363628` and a non-root identity. Record
results privately as absent, approved existing prerequisite, collision or unknown.
Only metadata is requested; private Lambda environments and Cognito users are
excluded. AccessDenied, network errors, incomplete pagination and ambiguous S3
errors mean **unknown**, never available.

The names are in [resources.json](resources.json):

| Resource | Proposed name |
| --- | --- |
| Functions | `actionbridge-dental-staging-` + `health`, `cases`, `calculations`, `jobs`, `job-worker` |
| Five runtime roles | Corresponding function name + `-role`, under `/actionbridge/staging/actionbridge-dental-staging/` |
| Five boundary policies | Corresponding function name + `-boundary` |
| Table | `actionbridge-dental-staging-cases` |
| Work queue / dead-letter queue | `actionbridge-dental-staging-jobs` / `actionbridge-dental-staging-dlq` |
| Upload bucket | `ab-dental-staging-uploads-631367363628-us-east-2` |
| Artifact bucket | `ab-dental-staging-artifacts-631367363628-us-east-2` |
| Execution role | `actionbridge-dental-staging-cfn` |
| HTTP API / stage | `actionbridge-dental-staging` / `staging` |
| Log groups | `/aws/lambda/<each exact function name>` |

All application names must be new. Approved pre-existing artifact/IAM prerequisites
need a separate ownership/configuration review; do not adopt a resource by name.
IAM role names are account-global even across paths. API names are not unique.
S3 names are globally shared: HeadBucket 400/403/404 does not prove availability.
Recheck collisions immediately before approved creation to account for races.

Supplement these exact Ohio checks with review of other enabled/previously used
Regions and global IAM, resource policies, cross-account trust and applicable
SCP/session restrictions. Check SQS, logs, Cognito, KMS, secrets and any discovered
compute/database/CloudFront/Route 53 workloads. Unchecked scopes remain unknown;
the goal is to protect existing resources, not declare the entire account empty.

## Completed local preparation

- [generated/bootstrap.yaml](generated/bootstrap.yaml) creates only one empty HTTP
  API with its execute-api endpoint disabled. It has no routes, integrations,
  stage, Lambda, storage or Cognito resources.
- [generated/backend.yaml](generated/backend.yaml) is an offline-expanded
  CloudFormation template: 69 resources, five explicitly named runtime roles,
  exact staging data/function names and **zero Cognito resources**. It is an
  **UPDATE of that same bootstrap stack**, not a direct CREATE or import.
- Both phases retain logical ID `HttpApi`, `ProtocolType: HTTP` and the same API
  name. Retaining ProtocolType avoids the replacement risk from simply switching
  a raw bootstrap API to SAM's usual output. Explicit routes/integrations and the
  JWT authorizer avoid the rejected Body-plus-ProtocolType import configuration.
  The backend keeps the endpoint disabled until separate security verification
  and traffic approval. Future change-set review must reject API replacement;
  see [THIRD_DEPLOYMENT_REPAIR.md](THIRD_DEPLOYMENT_REPAIR.md) for current blockers.
- Five individual boundary JSON drafts in `generated/` are exact to each role.
  Health writes its own log streams only; calculations read the staging table;
  cases manage the required staging records; Jobs can enqueue/presign/use speech
  and reserve quota; the worker can poll/read/process/remove staging uploads.
  Quota UpdateItem requires present `STAGING_QUOTA#*` partition keys. S3 checks
  expected ownership. Bedrock foundation models require the exact Nova profile.
  Explicit denies reject other actions/resources and out-of-context processing.
- The preparer draft permits only the two named review change sets. It retains
  execution/direct-stack/import denials, exact CloudFormation PassRole and
  artifact-prefix access. No SAM transform permission is needed for the generated
  templates. The service-only [cloudformation-trust.json](cloudformation-trust.json)
  is unchanged.
- [package-artifacts.py](package-artifacts.py) prepares deterministic local Lambda
  ZIPs and five artifact-key parameters, with ZIP SHA-256 in each key. It performs
  no upload and reads no identity parameters. Changed existing outputs and
  symlinks are refused.

The shared `infra/template.yaml`, application code and restored website are not
changed by this preparation. Staging artifacts are derived from that source;
dev/demo behavior stays intact. The existing private parameter file is ignored,
untracked and untouched. Its contents and the two confirmed testers' IDs were not
read or displayed. Users must not be recreated or reset.

## Approvals required before any cloud writes

1. **Collision/isolation:** record the scoped findings and protected resources,
   including unknown scopes. A 153-resource inventory is not complete isolation.
2. **Identity:** confirm the intended existing pool/client's owning account,
   membership, public-client/no-secret settings and required direct sign-in flows.
   Reuse the two confirmed users; never place their subjects in tracked files,
   command arguments, logs, screenshots or browser environment variables.
3. **IAM:** an administrator reviews the five boundaries, runtime trust, exact
   names, bootstrap execution draft and later API-ID-specific execution bundle.
   Require each role's exact boundary on creation; prohibit boundary removal,
   replacement and policy-version mutation by deployment principals. Runtime
   roles trust only Lambda. The execution role trusts only CloudFormation and
   cannot change itself, the caller or boundary policies. Do not attach drafts
   before this review. See [execution-role-review.md](execution-role-review.md).
4. **Service limits:** approve actual Nova availability/destination model ARNs,
   synthetic-only retention/quotas and spend alerts. The proposed US model profile
   permits three named destination Regions; the owner must verify its current
   destinations before approving the worker boundary. Polly remains in
   `us-east-1`. No inference or processing was run to verify access here.
5. **Prerequisites and execution:** separately authorize the administrator to
   provision/review the artifact bucket and IAM prerequisites, then separately
   authorize each reviewed change-set execution. The preparer has an explicit
   ExecuteChangeSet deny: adding another Allow cannot make it the executor.

The runtime service ceilings retain necessary limitations: Transcribe Start and
the used Textract/Polly APIs require wildcard resources. Textract job results
cannot be isolated by job ARN here. These statements have explicit Region limits,
but are not proof of complete production isolation. Keep the application approval,
quota and upload controls, and review resource-based policies as well.

## Local regeneration and validation

Use the pinned tools already installed in the temporary validation environment:

```bash
python3 infra/staging/build-boundaries.py --check
/private/tmp/actionbridge-staging-infra-checks/bin/python infra/staging/build-templates.py --check
python3 infra/staging/build-execution-policy.py --check
AWS_EC2_METADATA_DISABLED=true AWS_DEFAULT_REGION=us-east-2 \
  /private/tmp/actionbridge-staging-infra-checks/bin/python -m unittest discover -s infra/tests -v
SAM_CLI_TELEMETRY=0 AWS_EC2_METADATA_DISABLED=true AWS_DEFAULT_REGION=us-east-2 \
  sam validate --lint --template-file infra/template.yaml --region us-east-2
SAM_CLI_TELEMETRY=0 AWS_EC2_METADATA_DISABLED=true AWS_DEFAULT_REGION=us-east-2 \
  sam validate --lint --template-file infra/staging/generated/bootstrap.yaml --region us-east-2
SAM_CLI_TELEMETRY=0 AWS_EC2_METADATA_DISABLED=true AWS_DEFAULT_REGION=us-east-2 \
  sam validate --lint --template-file infra/staging/generated/backend.yaml --region us-east-2
AWS_EC2_METADATA_DISABLED=true AWS_DEFAULT_REGION=us-east-2 \
  /private/tmp/actionbridge-staging-infra-checks/bin/cfn-lint \
    --template infra/template.yaml infra/staging/generated/bootstrap.yaml infra/staging/generated/backend.yaml \
    --regions us-east-2
```

If the temporary environment is gone, create a new local virtual environment and
install `infra/requirements-checks.txt`. Regeneration omits `--check` and changes
only the public generated artifacts. It never reads `.staging/parameters.json`.
Local tests use fictional inputs and denied network connections. They do not
establish live permissions, provider behavior or collision availability.

The earlier staging-template verification on 2026-10-24 passed **64 infrastructure tests**, SAM validation
with lint on the shared source and both staging templates, pinned cfn-lint 1.40.2
on all three templates without warnings, generator consistency checks and
`git diff --check` (SAM CLI 1.170.0; translator 1.115.0). Real Lambda bundles and
application/browser suites were not rebuilt or rerun by this infrastructure work.
The subsequent read-policy/runner validation passed 99 infrastructure tests;
see [COLLISION_CHECKS.md](COLLISION_CHECKS.md) for the latest results and owner grant.

## Future cloud steps — not executed or authorized by this preparation

Follow only after the preceding approvals, using explicit target/profile/role.

1. **Provision prerequisites separately.** An authorized administrator creates or
   approves the artifact bucket in Ohio, five boundary policies and the
   CloudFormation execution role with its bootstrap-only policy. Preserve the
   existing external identity. No automatic artifact bucket creation or
   `--resolve-s3` is allowed.
2. **Bootstrap CREATE.** Prepare `actionbridge-staging-initial-review` for the new
   stack using `generated/bootstrap.yaml`, type CREATE, the explicit execution
   role and `--no-import-existing-resources`. Supply no private tester parameters.
   Reject anything except Add `HttpApi`. A separately authorized executor reviews
   the exact change-set ARN and performs that execution.
3. **Bind permissions to the returned API ID.** Obtain `HttpApiId` from this
   stack's output and verify ownership, HTTP protocol, disabled endpoint and
   absence of routes/stages. Generate the **local** execution review bundle:

   ```bash
   python3 infra/staging/build-execution-policy.py \
     --api-id ACTUAL_REVIEWED_API_ID --output-dir .staging/execution-review
   ```

   The generator validates syntax, not ownership. An administrator reviews all
   policy parts and replaces bootstrap permissions with the complete reviewed
   backend execution configuration. Backend permissions must have **no API
   collection create/import grant**; all API mutations use the captured ID and
   required children. Bootstrap recovery needing a delete permission must be
   separately scoped to the captured API ID; do not add regional writes for
   rollback. No role should have unrelated attached policies.
4. **Build/package locally, then separately approve uploads.** From a reviewed
   source/build workspace preserving existing local work:

   ```bash
   npm run build:lambda
   python3 infra/staging/package-artifacts.py
   ```

   The ZIPs are under `.staging/artifacts/<slug>/<sha256>.zip`; their five S3 keys
   are in `.staging/artifacts/artifact-parameters.json`. Upload only those reviewed
   files to the approved bucket and keys. Use conditional uploads that refuse
   overwrite (S3 PutObject `If-None-Match: *`) and verify the recorded checksums.
   A content-addressed key is not an S3 immutability guarantee by itself.
5. **Prepare private backend parameters.** In a private local editor, copy the
   existing ignored parameter file to a new ignored `.staging/backend-parameters.json`,
   preserve its values and add the five public artifact-key parameters. Retain
   file mode `0600` and directory mode `0700`. Both external identity parameters,
   approved subjects and approved staging origins remain required. The legacy
   common-boundary parameter is accepted but ignored: the five fixed boundary
   ARNs are authoritative. No helper from this preparation opens that file.
6. **Backend UPDATE.** Prepare `actionbridge-staging-backend-review` against that
   same stack with `generated/backend.yaml`, type UPDATE,
   `CAPABILITY_NAMED_IAM`, the private parameter file, explicit role and
   `--no-import-existing-resources`. Expected changes are additions for the new
   backend and an in-place modification of the known empty API. Reject API
   replacement (including conditional replacement), imports, Cognito operations,
   unrelated changes and data-resource replacements/deletions. Recheck that the
   API ID and exact policies match. Separately approve execution of this ARN.
7. **Verify with existing users.** Check code ZIP hashes against Lambda's
   CodeSha256, health/authentication, unapproved-subject denial, both approved
   users' ownership isolation, quotas, uploads and processing using bounded
   synthetic inputs. Test through localhost or an explicitly approved Preview
   origin. Keep Vercel production and the teammate's backend unchanged.

No cloud mutation or execution command is provided for automatic use. Reconcile
provider read-back/rollback permissions with actual service responses under the
approved scope; do not resolve AccessDenied by adding full-service policies.

AWS references: [IAM boundaries](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_boundaries.html),
[API Gateway authorization](https://docs.aws.amazon.com/service-authorization/latest/reference/list_apigatewayv2.html),
[CloudFormation API properties](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-apigatewayv2-api.html),
[inference-profile restrictions](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-prereq.html).

## Files changed by this local preparation

The earlier staging-template/boundary preparation modified six existing
preparation/docs/test files and added twenty local files, as recorded below.
The subsequent collision-read grant/runner work is documented in
[COLLISION_CHECKS.md](COLLISION_CHECKS.md).
The generic SAM template, its original tests, existing ignore rules, CloudFormation
trust, private-input helper, application code and restored website remained unchanged
from this pass's initial preservation baseline. No Git history was changed.

| File | Change |
| --- | --- |
| [docs/STAGING_BACKEND.md](../../docs/STAGING_BACKEND.md) | Updated |
| [infra/staging/README.md](README.md) | Updated |
| [infra/staging/change-set-preparer-policy.json](change-set-preparer-policy.json) | Updated |
| [infra/staging/execution-role-review.md](execution-role-review.md) | Updated |
| [infra/staging/preflight-read-policy.json](preflight-read-policy.json) | Updated |
| [infra/tests/test_staging_policies.py](../tests/test_staging_policies.py) | Updated |
| [infra/staging/RUNBOOK.md](RUNBOOK.md) | Added |
| [infra/staging/build-boundaries.py](build-boundaries.py) | Added |
| [infra/staging/build-execution-policy.py](build-execution-policy.py) | Added |
| [infra/staging/build-templates.py](build-templates.py) | Added |
| [infra/staging/collision-checks.py](collision-checks.py) | Added |
| [infra/staging/generated/actionbridge-dental-staging-calculations-boundary.json](generated/actionbridge-dental-staging-calculations-boundary.json) | Added |
| [infra/staging/generated/actionbridge-dental-staging-cases-boundary.json](generated/actionbridge-dental-staging-cases-boundary.json) | Added |
| [infra/staging/generated/actionbridge-dental-staging-health-boundary.json](generated/actionbridge-dental-staging-health-boundary.json) | Added |
| [infra/staging/generated/actionbridge-dental-staging-job-worker-boundary.json](generated/actionbridge-dental-staging-job-worker-boundary.json) | Added |
| [infra/staging/generated/actionbridge-dental-staging-jobs-boundary.json](generated/actionbridge-dental-staging-jobs-boundary.json) | Added |
| [infra/staging/generated/backend.yaml](generated/backend.yaml) | Added |
| [infra/staging/generated/bootstrap-execution-policy.json](generated/bootstrap-execution-policy.json) | Added |
| [infra/staging/generated/bootstrap.yaml](generated/bootstrap.yaml) | Added |
| [infra/staging/package-artifacts.py](package-artifacts.py) | Added |
| [infra/staging/resources.json](resources.json) | Added |
| [infra/tests/test_staging_artifacts.py](../tests/test_staging_artifacts.py) | Added |
| [infra/tests/test_staging_boundaries.py](../tests/test_staging_boundaries.py) | Added |
| [infra/tests/test_staging_collisions.py](../tests/test_staging_collisions.py) | Added |
| [infra/tests/test_staging_execution.py](../tests/test_staging_execution.py) | Added |
| [infra/tests/test_staging_templates.py](../tests/test_staging_templates.py) | Added |
