# Restricted staging backend preparation

Use synthetic treatment data only. Preserve existing application work, uncommitted changes, Git history and teammate infrastructure. The current review permits local work and offline tests; further AWS writes, test invocations and publication require their explicit approvals.

**Current status — October 28:** the stage-separated core reached
`UPDATE_COMPLETE` with 40 deployed resources and no resource failures. The
preserved API is `l52iwors8c`; its endpoint remains disabled and the externally
managed `staging` stage has AutoDeploy off and no attached deployment in the
recorded post-deployment verification. No fresh AWS read is implied by this
local review. Do not repeat setup, IAM repairs, recovery or core deployment.

The original synthetic T01 invocation was denied before the handler ran. Its
consumed attempt and nine evidence files are preserved. The exact `$LATEST`
permission correction was verified, but the original test window expired at
October 28, 8 PM EDT. Real backend functional tests, Cognito/API Gateway
authentication and website-to-staging checks remain incomplete. The owner
reported the later October 28 access-window update complete; its final live IAM
readback remains pending. The completion deadline is withdrawn. The selected
next proposal is October 30, 6–8 PM EDT (`22:00Z` to `00:00Z` October 31), in
`.staging/completion-review-20261028/phase1-access/`. The
[completion roadmap](COMPLETION_ROADMAP.md) records the remaining phases and
separate approval gates. Historical tonight artifacts are preserved; no renewal,
test or publication is authorized by any proposal's existence. Jobs, uploads, worker processing and live AI
remain deferred. Independent hosting uses the existing staging Amplify app;
publishing and adding its exact origin to `StagingWebOrigins` need review.

**Historical October 26 repair record:**
Recovery A is complete at UPDATE_ROLLBACK_COMPLETE; do not repeat it. The forward
identity-only literal tagging proposal remains withdrawn. The two recognized
HTTP replacements pass owner-reported Console validation and combined review;
live application is unapproved and tagged CreateStage remains runtime-unproven.
Existing API l52iwors8c is preserved, and the restored template keeps its endpoint
disabled; direct API-settings reads remain restricted. No new change set or
deployment is authorized. The setup/evidence sections below describe earlier preparation;
completed IAM, bucket, identity and artifact prerequisites must not be repeated.

## Scoped collision-read grant and runner

The 32-check plan was printed, not executed. The existing developer user has
limited permissions; AccessDenied never establishes a free name. The new
[collision-read policy](../infra/staging/collision-read-policy.json) and
[approval/authentication-gated runner](../infra/staging/run-collision-checks.py)
are prepared locally. [Owner instructions](../infra/staging/COLLISION_CHECKS.md)
describe the eleven read actions, unavoidable IAM/metadata exceptions and manual
customer-managed-policy grant to the existing user. They do not grant deployment
or identity-administration permissions.

The runner is offline by default. Actual reads require explicit opt-in and
successful authentication as the exact developer user in account `631367363628`.
All failures remain visible and denied/ambiguous results are UNKNOWN. No real
AWS calls, login, IAM changes, private parameter reads or deployment were used
to validate this work. Existing code, users, website and Git work are preserved.

Fresh local validation passed **99 infrastructure tests** (including nine read-policy
scope tests and 26 mocked-runner tests), local IAM-document lint without warnings,
offline-mode verification and whitespace/link checks. The new managed-policy draft
is 4,896 compact characters. No live IAM authorization or collision availability
was inferred from these local results.

## Independent staging preparation (2026-10-24)

The current deployment preparation is in
[infra/staging/RUNBOOK.md](../infra/staging/RUNBOOK.md). It supersedes the earlier
single-template deployment guidance below. No AWS login/account API calls,
resources, permissions, Cognito accounts, Vercel, commits or pushes were changed.

The owner now reports **153 resources**, mostly default networking, with no obvious
production application infrastructure. **The inventory remains incomplete.**
This is an owner-reported finding, not a new account inspection by this work.
Other Regions, services, global IAM and resource policies remain review scopes.

Prepared locally:

- An exact-name manifest and a print-only plan of 32 read-only collision checks.
  IAM role names, existing reserved paths, both API types and globally ambiguous
  S3 bucket names are covered. Denied/incomplete checks remain unknown.
- A disabled empty-API bootstrap template and a separate, fully expanded staging
  backend template with 69 resources, five explicitly named runtime roles and
  zero Cognito resources. Both phases retain the same API logical ID, name and
  `ProtocolType: HTTP`. Only a same-stack UPDATE is permitted for the backend;
  API replacement and imports must be rejected.
- Five individual administrator-owned runtime-boundary drafts with exact staging
  resources, per-role logging/data/processing ceilings and explicit denials for
  other actions/resources/contexts. The generic source SAM template and dev/demo
  are unchanged. The legacy common-boundary parameter is accepted but ignored by
  the generated staging template.
- A constrained bootstrap execution-policy draft and an offline generator for
  exact-API-ID backend execution policies plus mandatory guardrail parts. The
  split backend documents fit IAM managed-policy limits; they are identity
  policies, not a single execution permissions boundary. All parts need review.
- A local deterministic ZIP packer producing five content-addressed artifact keys
  without uploads or identity-parameter reads. Real bundles were not rebuilt or
  uploaded by this preparation; synthetic bundles exercise the packer in tests.

The existing Cognito accounts and two confirmed testers remain unchanged. The
Git-ignored private parameter file was not opened or modified; tester UUIDs,
tokens and environment values were not displayed. Website design, application
code, Git history and unrelated uncommitted work are preserved.

Fresh local verification passed **64 infrastructure tests**, `sam validate --lint`
on the shared source and both generated staging templates, pinned `cfn-lint`
1.40.2 on all three templates without warnings, all generated-artifact consistency
checks and `git diff --check`. Validation used SAM CLI 1.170.0 and pinned SAM
translator 1.115.0. Policy/quota/ZIP tests use synthetic inputs; no AWS authorization,
real collision or paid processing was tested. Browser/application suites were not
rerun because no application code changed.

**Exact next action:** an already authorized non-root administrator first prints
the prepared plan with
`python3 infra/staging/collision-checks.py --profile YOUR_AUTHORIZED_ADMIN_PROFILE`,
then approves/runs the individual read-only checks and records collision findings
privately. Printing the plan executes no AWS commands. IAM provisioning and both
change-set executions require separate approvals after collision/isolation,
identity, model and spend-control review.

## Earlier generic-template IAM review (2026-10-24)

This historical record describes the generic SAM template before the independent
staging artifacts above were prepared. Follow the current runbook for deployment;
its five boundaries and bootstrap CREATE/backend UPDATE replace this older route.

Target: account `631367363628`, Region `us-east-2`, proposed new stack
`actionbridge-dental-staging`. The owner confirmed that the original ActionBridge
Dental Vercel website connects to an API in the teammate's separate account
`195469705669`. It is not a backend deployment in the target account.

The owner-reported checks found no active CloudFormation stacks, Lambda
functions, API Gateway APIs or DynamoDB tables in Ohio, and no general-purpose S3
buckets account-wide. **These checks are not a complete account inventory and do
not establish that the account has no production resources.** Other services,
Regions, global IAM policies and resource-based grants still need review. This
pass ran no AWS login or AWS API commands, made no AWS/IAM or Vercel changes, and
created/pushed no Git commits.

`.staging/parameters.json` was confirmed Git-ignored and untracked, with mode
`0600` in a `0700` directory. Its contents and the two private approved tester IDs
were not read, displayed or modified. Do not paste them into chat, logs, commands
or tracked files. Their current values/configuration were not validated here.

Safe local changes:

- Staging now requires `StagingRuntimePermissionsBoundaryArn`. SAM passes it to
  all five generated Lambda roles, along with role path
  `/actionbridge/staging/${AWS::StackName}/`. Dev/demo preserve their previous
  default role path and omit the new boundary. The ARN parameter only validates
  syntax; policy existence, same-account ownership and approved contents require
  administrator verification. This template does not create the boundary policy.
- The unapplied change-set-preparer draft now restricts preparation/review to
  `actionbridge-staging-initial-review`. Correct stack/SAM-transform scopes,
  single-role service-restricted PassRole, artifact account/prefix restrictions,
  and explicit execution/import denials remain. CREATE-only and disabled automatic
  imports remain mandatory command/review gates; this policy is not a permissions
  boundary and cannot certify the principal's other grants.
- The preflight draft includes read-only inspection of the exact proposed runtime
  boundary. `cloudformation-trust.json` remains service-only. No apply-ready
  execution policy or regional API write wildcard was introduced.
- The execution review corrects HTTP API import/reimport and tagging action
  mappings and explains why API names/tags do not establish safe scoping for the
  generated V2 API and all its children. A possible separately authorized empty-API
  bootstrap requires a new staged-template review; it is not implemented here.

Validation for this review: `sam validate --lint` passed (SAM CLI 1.170.0), pinned
`cfn-lint` 1.40.2 passed without warnings, and all **23 offline infrastructure
tests** passed (15 template, eight policy-draft tests; SAM translator 1.115.0).
Validation tools were installed in a temporary virtual environment under
`/private/tmp/actionbridge-staging-infra-checks`, without changing application
dependencies. The SAM translator runs with fictional identity/artifact/boundary values
and denied network connections. Staging with external identity selects **43
resources and zero Cognito resources**. These checks do not establish live AWS
permissions or deployability. Application/browser suites and Lambda bundles were
not rebuilt by this infrastructure-only review; their earlier evidence below is
historical.

Deployment remains blocked on an administrator-reviewed inventory/isolation
decision, immutable runtime-boundary contents and enforcement, a separately
constrained CloudFormation execution role and caller, API-ID scoping, and artifact
bucket provisioning. The proposed artifact bucket is absent according to the
owner's S3 checks. The intended Cognito pool/client's owning account, settings and
tester membership, model access and spend controls also need verification.

**Next safe owner action:** have an already authorized, non-root AWS administrator
review [execution-role-review.md](../infra/staging/execution-role-review.md) and
record the production-isolation decision and proposed boundary/API-scoping design
for `631367363628` before authorizing any IAM or resource creation. Review only;
do not attach the draft policies yet. After an actual boundary is separately
approved/provisioned, its ARN must be added privately as
`StagingRuntimePermissionsBoundaryArn` in the ignored parameter file, preserving
existing values. This review did not inspect whether that parameter is present.

The complete local handoff and future, separately gated packaging commands are in
[infra/staging/README.md](../infra/staging/README.md).

## Identity and environment selection

`AppEnv` accepts `dev`, `demo` and `staging` in SAM; the backend also retains `local`. Existing dev/demo defaults, managed Cognito properties, API throttling, engine behavior, data layout and retention remain unchanged. JWT handlers now deliberately require `token_use=access` in every environment; the direct Cognito sign-in flow already returns access tokens. Local/demo-header authentication remains available outside staging only.

`ExistingUserPoolId` and `ExistingUserPoolClientId` default to empty and must be supplied together. With both empty, SAM retains its pool/client/domain. With both supplied, no Cognito resources or managed-login domain output are created; issuer, audience and identity outputs reference the external values. The backend stack does not import, modify, own or delete the supplied identity resources.

For the requested staging deployment, the public identifiers are:

```text
Region: us-east-2
ExistingUserPoolId: us-east-2_GErUtH894
ExistingUserPoolClientId: 7uotveip0c7k931lv2te275fjg
Issuer: https://cognito-idp.us-east-2.amazonaws.com/us-east-2_GErUtH894
```

**Use a new isolated stack. Never switch an existing stack from managed to external identity.** CloudFormation would remove that stack's old conditionally managed Cognito resources. Reject any change set containing Cognito operations, existing-table replacements, or changes outside the intended new staging stack. Keep the external staging pool/client outside this stack's lifecycle. The managed pool's existing password policy is unchanged; external pool settings remain authoritative.

API Gateway validates signature, issuer, audience/client and token timestamps. Lambda trusts only its authorizer claims, then requires an access token and derives ownership from `sub`. Browser owner IDs, demo headers and decoded unverified bearer content cannot establish ownership. No Cognito secret, AWS key or database password belongs in the browser.

## Approved testers and distributed limits

Staging requires `AUTH_MODE=jwt` and `StagingAllowedUserSubs`: 1–10 unique approved Cognito subject UUIDs, comma-separated without spaces. It defaults to empty, so an unconfigured staging deployment fails validation rather than permitting public access. Obtain approved subject IDs from the staging identity owner; use no email addresses or tokens. The parameter is `NoEcho`, is not an output and must never be a `VITE_*` setting. Lambda environment access remains privileged infrastructure access.

Every known private HTTP route checks approval before handler I/O. `/health` remains public when configuration is valid. The worker checks approval again before loading a queued job or calling billable services. Existing owner-scoped repositories continue to isolate approved testers from one another. Approval is a deployment configuration snapshot: removing a subject requires a staging configuration update and does not cancel already-running work.

| Operation                                              | Parameter / server variable                              | Default per user per UTC day |           Global default per UTC day |
| ------------------------------------------------------ | -------------------------------------------------------- | ---------------------------: | -----------------------------------: |
| Jobs, including answer follow-ups and explicit retries | `StagingJobDailyLimit` / `STAGING_JOB_DAILY_LIMIT`       |                           10 |    20 (`StagingGlobalJobDailyLimit`) |
| Upload slots                                           | `StagingUploadDailyLimit` / `STAGING_UPLOAD_DAILY_LIMIT` |                           10 | 20 (`StagingGlobalUploadDailyLimit`) |
| Read-aloud                                             | `StagingSpeechDailyLimit` / `STAGING_SPEECH_DAILY_LIMIT` |                           30 | 60 (`StagingGlobalSpeechDailyLimit`) |

Global server variable names use `STAGING_GLOBAL_JOB_DAILY_LIMIT`, `STAGING_GLOBAL_UPLOAD_DAILY_LIMIT` and `STAGING_GLOBAL_SPEECH_DAILY_LIMIT`. Per-user overrides must be integers 1–100; global overrides 1–1000. Changes require configuration review. No staging quota variables or quota-write permissions are applied to dev/demo.

Two conditional DynamoDB updates atomically reserve both allowances in one transaction. Counters use a `STAGING_QUOTA#` namespace, hashed owner IDs and server-side UTC dates. Daily reset uses a new key, independently of eventual TTL deletion; counters expire three days after their UTC-day start. No in-process deployed counter or unavailable-store fallback exists. The Jobs role can update only quota-prefixed keys.

Validate ownership, input and state before reserving quota, and reserve before mutations, queue sends, presigning or speech calls. A limit violation returns the nested `RATE_LIMITED` 429 envelope. Store failures deny the operation with a generic retryable service error. Accepted attempts remain charged if downstream work fails or a concurrent state transition loses; there is no refund that can be exploited through repeated failure. SQS delivery retries remain bounded by queue/worker controls and can cause additional service usage. A pre-existing concurrent-answer race can create duplicate follow-ups; each now consumes quota, but answer submission is not guaranteed to be idempotent.

These are staging admission limits, not a billing ceiling. Uploads retain the existing 5 MiB constraints, five-minute signed POSTs, real-file-signature checks and owner-derived keys. The upload quota counts issued slots, not S3 requests: a signed POST can be replayed until its five-minute expiry, so it does not cap upload request charges. Returning the first five PDF pages does not limit all pages processed/billed by asynchronous Textract. Use bounded synthetic PDFs. API throttling remains 10 requests/second, burst 20; worker maximum concurrency remains two.

A later public production release needs a separately reviewed enrollment/access policy, durable user/tenant abuse controls, per-period usage and concurrency limits, monitoring, spend response and data-retention/durability design. Do not disable staging restrictions and call that a public launch. Frontend access restrictions or private URLs do not protect a directly callable API.

## IAM, diagnostics and regional behavior

Runtime Marketplace subscription permissions are removed because the default first-party Nova model does not use them. An operator choosing a Marketplace model must arrange approved model/subscription access separately. Staging transcription names and Get/Delete permissions use `actionbridge-${AWS::StackName}_*` in the deployment account/Region, so staging cannot read or delete another stack's jobs. The underscore delimiter cannot occur in a CloudFormation stack name, preventing overlap between names such as `foo` and `foo-bar`. The worker requires this stack-specific prefix and fails closed if it is missing or malformed. Dev/demo retain their existing `actionbridge-*` names and permission scope. StartTranscriptionJob, supported Textract operations and Polly retain required wildcard resources where those operations lack applicable resource scoping. Bedrock remains scoped to the configured inference profile/model; its geographic inference profile needs destination-Region model permissions.

Health/authorization guards import no DynamoDB SDK. The quota adapter is constructed only for staging Jobs handlers. Execution credentials come from IAM roles. Worker/HTTP/speech diagnostic exception names use an exact fixed allowlist, with unknown names collapsed to `UnknownError`; AWS messages, arbitrary exception names, request bodies and ModelError details are not logged. Safe request IDs, generated job IDs, status and duration remain useful for operations.

Polly currently defaults to `us-east-1`. The configured `us.amazon.nova-2-lite-v1:0` profile can process in `us-east-1`, `us-east-2` or `us-west-2`; do not claim all processing stays in Ohio. No regional service configuration is changed by this preparation.

## CORS and local configuration

`StagingWebOrigins` defaults to only `http://localhost:5173,http://127.0.0.1:5173`. It supplies both HTTP API and S3 CORS when staging is selected. Add only the exact approved HTTPS Preview origin; the parameter rejects wildcard origins, URL paths and insecure remote origins. Existing `WebOrigins` and its dev/demo defaults remain unchanged. API authorization/content-type/idempotency headers and S3 POST support remain enabled. CORS does not authorize users.

After a separately approved deployment, set ignored `web/.env.local` `VITE_API_BASE_URL` to the actual `ApiBaseUrl` output, including `/staging`, without `/v1`. Retain staging region/public client. Restart Vite. There is no guessed or production API fallback. Do not change Vercel production or assume a Vercel project is linked to this repository.

## Offline validation and future deployment gates

Run from the approved checkout with Node 22.13+ and installed locked application dependencies:

```bash
npm run check
npm --prefix web run typecheck
npm --prefix web test
npm --prefix web run build
npm run build:lambda
python3 -m venv web/.runtime/infra-checks
web/.runtime/infra-checks/bin/python -m pip install -r infra/requirements-checks.txt
SAM_CLI_TELEMETRY=0 AWS_EC2_METADATA_DISABLED=true AWS_DEFAULT_REGION=us-east-2 \
  sam validate --lint --template-file infra/template.yaml --region us-east-2
AWS_EC2_METADATA_DISABLED=true AWS_DEFAULT_REGION=us-east-2 \
  web/.runtime/infra-checks/bin/cfn-lint --template infra/template.yaml --regions us-east-2
AWS_EC2_METADATA_DISABLED=true AWS_DEFAULT_REGION=us-east-2 \
  web/.runtime/infra-checks/bin/python -m unittest discover -s infra/tests -v
```

The earlier application-preparation record reported 583 repository tests across 48 files, 176 browser tests, backend/test and web TypeScript, the web production build, Lambda packaging, infrastructure lint and 11 infrastructure regression tests. Those are historical results, not fresh checks from the local IAM review above. The browser suite used installed Chrome through an ignored local runner configuration; Cognito/API calls were mocked. No live AWS authorization, CORS or resource operation was exercised. The web build reported non-blocking dependency annotation and bundle-size warnings.

Infrastructure tests use the actual SAM translator with fictional package references and a network-denial guard. They test managed/external identity across dev/demo/staging, paired parameter rules, approval requirements, expanded JWT/CORS, unchanged managed defaults, quota IAM and removed Marketplace permissions. They do not simulate AWS resource creation or certify live account permissions.

Before any cloud operation: obtain separate authorization, a reviewed clean source revision/build workspace, approved staging account/profile/CloudFormation role, artifact bucket, tester subjects, exact Preview origin if needed, model access and budgets/alerts. Preserve this checkout's unrelated local work. Verify account identity, pool/client membership, no client secret and required direct sign-in flows with safe read-only queries. No runtime role needs Cognito administration.

Only after those gates, prepare a staging-only change set using explicit stack/account/Region/role, `AppEnv=staging`, both external identity parameters, approved subject IDs, `StagingWebOrigins` and reviewed limits. `sam deploy --no-execute-changeset` still uploads artifacts and creates a change set; `--resolve-s3` can create a bucket. Neither command is part of this local preparation. Review the processed template and exact change-set ARN before separately authorized execution. Do not rely on historical dev stack/profile/API defaults.

After deployment, use two manually confirmed synthetic accounts. Test bad/expired/wrong-pool/client/ID tokens; unapproved and approved subjects; cross-user reads/writes/calculations/saved comparisons/jobs/uploads; per-user/global quota boundaries under parallel requests; unavailable quota-store denial; estimates and Plan A/B comparison; save/reload/reopen; S3 policy/type/size enforcement; document/voice processing; and allowed/disallowed origins. Never print tokens or patient data. A missing second user must fail the isolation gate rather than skip it.

Do not run `infra/scripts/smoke-aws.sh` unchanged against this pool: it defaults to the old dev stack, administratively confirms/reset users and its generated password does not guarantee a special character. Use already confirmed test identities and short-lived process-only access tokens with reviewed smoke/API tests. The older basic smoke does not cover all Plan A/B save/reopen routes.

## Costs, rollback and cleanup

The earlier preparation used a planning example of about $2.41 for 2M input plus 0.5M output Nova tokens across all turns/retries, 100 processed OCR pages, ten batch audio minutes and 10,000 neural Polly characters, excluding backend/storage/logging/authentication costs. This is historical, not a current quote; the later pricing note in [infra/staging/README.md](../infra/staging/README.md#model-and-costs) supersedes its model-cost assumption. No rates were refreshed by this IAM review. Pricing references: [Bedrock Ohio catalog](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrock/current/us-east-2/index.json), [Textract](https://aws.amazon.com/textract/pricing/), [Transcribe](https://aws.amazon.com/transcribe/pricing/), [Polly](https://aws.amazon.com/polly/pricing/). Prices, account allowances and actual usage must be rechecked before deployment. A $10–$20 initial staging allowance with alerts is a planning figure, not a spending cap. Count every model turn/retry, actual PDF pages, queue polling, logs and failed processing. Cognito tier/email, egress and other account costs remain separate.

For updates, retain the reviewed packaged template, parameters and physical-resource inventory; roll back through a staging-only change set without replacing data resources. New-stack failure uses CloudFormation's normal rollback. Removing the API URL from the frontend does not stop direct API use or queued work.

For full shutdown, restrict staging entry points and disable/drain staging job processing, identify exact physical resources, empty only the staging upload bucket if required, then delete only that backend stack after separate authorization. Remove orphaned transcription jobs using captured staging job IDs and the exact `actionbridge-${AWS::StackName}_` prefix, plus staging-only artifact prefixes. Table, queue, log and upload deletion destroys synthetic records. TTL/lifecycle deletion is eventual. Preserve the externally referenced pool/client and shared artifact buckets; reject Cognito actions and existing-resource replacements during every change-set review.

## Earlier application-preparation file record

These 32 paths comprise the earlier application preparation. The current IAM review changes only infrastructure preparation, its tests and staging documentation; it does not repeat or alter the application/browser work listed here.

- `.github/workflows/ci.yml`
- `backend/src/features/agent-jobs/application/job-runner.ts`
- `backend/src/features/agent-jobs/application/job-service.ts`
- `backend/src/features/agent-jobs/application/upload-service.ts`
- `backend/src/features/agent-jobs/infrastructure/aws.ts`
- `backend/src/features/agent-jobs/ports.ts`
- `backend/src/features/speech/speech.ts`
- `backend/src/functions/compose.ts`
- `backend/src/functions/job-worker.ts`
- `backend/src/functions/jobs.ts`
- `backend/src/shared/auth.ts`
- `backend/src/shared/config.ts`
- `backend/src/shared/dynamo-staging-quota-store.ts`
- `backend/src/shared/http.ts`
- `backend/src/shared/logger.ts`
- `backend/src/shared/staging-controls.ts`
- `backend/test/agent-harness.ts`
- `backend/test/api.test.ts`
- `backend/test/config.test.ts`
- `backend/test/jwt-access-security.test.ts`
- `backend/test/plan-comparison-api.test.ts`
- `backend/test/safe-error-logging.test.ts`
- `backend/test/saved-plan-comparisons.test.ts`
- `backend/test/staging-controls.test.ts`
- `backend/test/transcription-prefix.test.ts`
- `docs/PUBLIC_REGISTRATION.md`
- `docs/README.md`
- `docs/STAGING_BACKEND.md`
- `infra/.gitignore`
- `infra/requirements-checks.txt`
- `infra/template.yaml`
- `infra/tests/test_template.py`

The earlier preparation recorded these nine pre-existing uncommitted paths as byte-identical against its initial SHA-256 baseline and excluded them from its change. The current IAM review preserves the restored website and does not edit these paths:

- `web/README.md`
- `web/src/components/shell.tsx`
- `web/src/config.ts`
- `web/src/features/auth/sign-in-page.tsx`
- `web/src/state/auth.tsx`
- `web/tests/plan-comparison-api.spec.ts`
- `web/tests/public-registration.spec.ts`
- `web/tests/saved-plan-comparison.spec.ts`
- `web/tests/auth-config.spec.ts`
