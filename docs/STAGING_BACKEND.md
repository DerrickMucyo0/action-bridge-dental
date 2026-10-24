# Restricted staging backend preparation

This change prepares local code and infrastructure only. It does not deploy, create a change set, change Cognito/Vercel, or publish a release. Use synthetic treatment data. The nine pre-existing web configuration/authentication changes are separate local work and must remain intact.

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
AWS_EC2_METADATA_DISABLED=true AWS_DEFAULT_REGION=us-east-2 \
  web/.runtime/infra-checks/bin/cfn-lint --template infra/template.yaml --regions us-east-2
AWS_EC2_METADATA_DISABLED=true AWS_DEFAULT_REGION=us-east-2 \
  web/.runtime/infra-checks/bin/python -m unittest discover -s infra/tests -v
```

Final offline validation passed 583 repository tests across 48 files, 176 browser tests, backend/test and web TypeScript, the web production build, Lambda packaging, infrastructure lint and 11 infrastructure regression tests. The browser suite used installed Chrome through an ignored local runner configuration; Cognito/API calls were mocked. No live AWS authorization, CORS or resource operation was exercised. The web build reports non-blocking dependency annotation and bundle-size warnings.

Infrastructure tests use the actual SAM translator with fictional package references and a network-denial guard. They test managed/external identity across dev/demo/staging, paired parameter rules, approval requirements, expanded JWT/CORS, unchanged managed defaults, quota IAM and removed Marketplace permissions. They do not simulate AWS resource creation or certify live account permissions.

Before any cloud operation: obtain separate authorization, a reviewed clean source revision/build workspace, approved staging account/profile/CloudFormation role, artifact bucket, tester subjects, exact Preview origin if needed, model access and budgets/alerts. Preserve this checkout's unrelated local work. Verify account identity, pool/client membership, no client secret and required direct sign-in flows with safe read-only queries. No runtime role needs Cognito administration.

Only after those gates, prepare a staging-only change set using explicit stack/account/Region/role, `AppEnv=staging`, both external identity parameters, approved subject IDs, `StagingWebOrigins` and reviewed limits. `sam deploy --no-execute-changeset` still uploads artifacts and creates a change set; `--resolve-s3` can create a bucket. Neither command is part of this local preparation. Review the processed template and exact change-set ARN before separately authorized execution. Do not rely on historical dev stack/profile/API defaults.

After deployment, use two manually confirmed synthetic accounts. Test bad/expired/wrong-pool/client/ID tokens; unapproved and approved subjects; cross-user reads/writes/calculations/saved comparisons/jobs/uploads; per-user/global quota boundaries under parallel requests; unavailable quota-store denial; estimates and Plan A/B comparison; save/reload/reopen; S3 policy/type/size enforcement; document/voice processing; and allowed/disallowed origins. Never print tokens or patient data. A missing second user must fail the isolation gate rather than skip it.

Do not run `infra/scripts/smoke-aws.sh` unchanged against this pool: it defaults to the old dev stack, administratively confirms/reset users and its generated password does not guarantee a special character. Use already confirmed test identities and short-lived process-only access tokens with reviewed smoke/API tests. The older basic smoke does not cover all Plan A/B save/reopen routes.

## Costs, rollback and cleanup

As a planning example, 2M input plus 0.5M output Nova tokens across all turns/retries, 100 processed OCR pages, ten batch audio minutes and 10,000 neural Polly characters total about $2.41 before backend/storage/logging/authentication costs. Regional on-demand rates checked during the audit: [Bedrock Ohio catalog](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrock/current/us-east-2/index.json), [Textract](https://aws.amazon.com/textract/pricing/), [Transcribe](https://aws.amazon.com/transcribe/pricing/), [Polly](https://aws.amazon.com/polly/pricing/). Prices, account allowances and actual usage must be rechecked before deployment. A $10–$20 initial staging allowance with alerts is a planning figure, not a spending cap. Count every model turn/retry, actual PDF pages, queue polling, logs and failed processing. Cognito tier/email, egress and other account costs remain separate.

For updates, retain the reviewed packaged template, parameters and physical-resource inventory; roll back through a staging-only change set without replacing data resources. New-stack failure uses CloudFormation's normal rollback. Removing the API URL from the frontend does not stop direct API use or queued work.

For full shutdown, restrict staging entry points and disable/drain staging job processing, identify exact physical resources, empty only the staging upload bucket if required, then delete only that backend stack after separate authorization. Remove orphaned transcription jobs using captured staging job IDs and the exact `actionbridge-${AWS::StackName}_` prefix, plus staging-only artifact prefixes. Table, queue, log and upload deletion destroys synthetic records. TTL/lifecycle deletion is eventual. Preserve the externally referenced pool/client and shared artifact buckets; reject Cognito actions and existing-resource replacements during every change-set review.

## Files changed by this preparation

These 32 paths comprise the reviewed preparation. No application dependency, engine, shared fixture, license, contributor-credit or existing web file was changed by this work.

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

The nine pre-existing uncommitted paths were verified byte-identical against the initial SHA-256 baseline and remain excluded from this change:

- `web/README.md`
- `web/src/components/shell.tsx`
- `web/src/config.ts`
- `web/src/features/auth/sign-in-page.tsx`
- `web/src/state/auth.tsx`
- `web/tests/plan-comparison-api.spec.ts`
- `web/tests/public-registration.spec.ts`
- `web/tests/saved-plan-comparison.spec.ts`
- `web/tests/auth-config.spec.ts`
