# ActionBridge Dental completion roadmap

> Status tracking moved to [FINAL_COMPLETION_TRACKER.md](FINAL_COMPLETION_TRACKER.md)
> on October29. This document is retained as the prior plan/evidence history;
> subsequent task status and approval boundaries are maintained only there.

Updated October 29, 2026. This replaces the deadline to finish tonight. Continue
from the deployed staging core; do not recreate the project or repeat completed
IAM, KMS, recovery or deployment work. The selected schedule alone does not
approve cloud changes. Subsequent explicit Phase 1 approval covers fresh reads,
server validation, one verified private upload and one review-only access change
set. Execution, invocations, activation, publication and cleanup remain unapproved.
The current accelerated-plan review performs no cloud writes. Only the user's
summary of Gemini's proposal was supplied; no complete Gemini plan was available.

## Accelerated recommendation and the next owner action

**GO for the completed local work; NO-GO for live testing, publication or AI
deployment at this checkpoint.** At October 29 **13:58:54 EDT (17:58:54Z)**,
the proposed 11:30 start had passed. The separate local 14:00–16:00 draft also
missed its 13:30 setup/review checkpoint. Do not backdate or apply either draft.
Use the already selected **October 30, 18:00–20:00 EDT**, or
**2026-10-30T22:00:00Z inclusive through 2026-10-31T00:00:00Z exclusive**.
This recommendation does not automatically extend expired access.

The initial afternoon STS attempts returned SESSION_EXPIRED. A later protected
role login also stopped on an overwrite prompt; the owner confirmed only the
developer user was offered. The deployer profile is unchanged. Repeating that
same browser role-login path is not the next step.

**Latest follow-through:** the developer profile was successfully renewed and
its exact IAM-user identity independently verified. Fresh reads at approximately
October 29 14:29 EDT confirm backend UPDATE_COMPLETE/normal rollback, preserved
API l52iwors8c with endpoint disabled and localhost-only CORS, and ACTIVE Cases
table with the expected KMS encryption. ListRoles supplied the current deployer
trust (exact developer principal/MFA/3600 seconds) and tester trust (old expired
window), matching the saved trust baseline. These are actual API reads, not
owner screenshot observations. The external stage, deployment snapshots, full
tester inline policy/baseline and Amplify remain to be refreshed.

**Immediate owner action:** use an already authorized administrator/owner
Console session, separate from the limited developer/deployer session, to read
the actual device assignment for actionbridge-developer. Report only the public
ARN/serial, no device assigned, or owner/admin session unavailable. The user
reports password/six-digit sign-in but the device assignment/identifier is not
independently verified. The denied Console page cannot supply this information.
No MFA code, seed or password should be shared. The saved policies and 1,725
local text files provide no permitted alternative device metadata path; browser
automation is unavailable. One isolated source-session role probe failed without
a classified AWS error and was not retried; it establishes no MFA verdict.
Existing home profiles remain unchanged. Prepare the exact MFA role profile
only after resolving those prerequisites; change no IAM/MFA requirement. See
[the supported alternative and recorded stop](../.staging/staged-completion-followthrough-20261029/AUTHENTICATION-NEXT-SUPPORTED-PATH.NOT-APPLIED.md).

After renewal use authorized reads serially under the existing lock. Stop on a
real access denial and use one consolidated owner evidence checkpoint for only
inaccessible fields; do not request broader access or repeated screenshots.
The saved deployer scope excludes the synthetic-access stack/tester role, so
this owner checkpoint may remain necessary even after login succeeds.

New local preparation, separate from application-suite counts: 24 offline tests
pass for the future HTTP budget/manifest journal (no network/dispatch path), and
27 structural/security tests pass for an intentionally nondeployable AI
infrastructure draft. The latter preserves the core and adds 23 deferred
resources plus one TLS bucket policy with mapping disabled and retained bucket
protections. It is not CloudFormation/server validated or approved for release.
See [continued preparation results](../.staging/staged-completion-followthrough-20261029/LOCAL-PREPARATION-RESULTS.md).

The minimum future approval sequence is: **review-only access preparation →
execute the exact reviewed access ARN → audited controller binding/live
preflight → 20 new direct tests → bounded API/Cognito/HTTP activation tests →
exact Amplify publication**. AI and cleanup remain separate. Prior approvals
and receipts remain recorded; no later operation is claimed without evidence.

## Recorded state and completed local work

The last independent backend verification recorded `UPDATE_COMPLETE`, 40 core
resources, three Lambda functions and 14 API routes. API `l52iwors8c` was
preserved with its execute-api endpoint disabled. Its externally managed
`staging` stage had AutoDeploy off, no deployment and no tags. These are recorded
observations, not fresh AWS checks in this review.

The owner reported the October 28 synthetic-access update `UPDATE_COMPLETE` at
10:34:44 PM EDT. Complete post-update IAM readback was blocked by expired
sessions at that checkpoint. The later overnight owner exports and metadata
matched its complete reviewed 15-statement baseline. Their actual observation
times remain recorded; they do not refresh the afternoon live baseline.
Earlier testing windows are not authorization for a future run.

Only the original denied T01 consumed a Lambda attempt. The consumed latch and
nine evidence files retain all ten recorded hashes. No new live run namespace
exists. Both optional ownership tests remain SKIPPED.

This local completion review delivered:

- An independently audited October 30 access proposal and isolated controller.
  The original controller releases, manifest, payloads and evidence are intact.
- A fix for duplicate AI follow-up work after concurrent unchanged answers or a
  cancellation. A failed conditional job close now returns `REVISION_CONFLICT`
  before enqueueing. This does not make case patch/job close one transaction.
- A value-free release scanner and exact dependency/font notices. A separate
  local frontend package contains the notices; all 53 original package members
  are byte-identical, with only 12 notice files added. The old ZIP is preserved.
- A deferred AI infrastructure and security inventory, including rollback,
  encryption, service-region and explanation-safety gaps. AI stays disabled.
- An independently reviewed web auth fix for late refresh/sign-in, logout and
  account-switch races. Six new suite regressions, three independent browser
  scenarios and the production-build CSP smoke passed with mocked services.
  Browser suite total is now 220 (209 main + 11 core), with zero failures,
  skips or flaky results. This does not prove actual Cognito authentication.

The latest **local-only** frontend package is
`.staging/accelerated-completion-review-20261029/frontend-core-package/frontend.zip`:
723,745 bytes, 65 files, SHA-256
`8072f765bf5a4e608bf56ee57e9c87e0280e32eb8d9c08e4ccdbd247c850313d`.
Its complete inventory, notices, actual API/Cognito/Ohio public bindings and
jobs-disabled setting independently passed the artifact gate. The earlier
723,577-byte `8608ed92…` package and 711,808-byte `14b94f0d…` package remain
unchanged. The latter lacks the twelve required notice files. The new package
supersedes both for any future separately approved release and is not published.
The local production artifact also passed strict script CSP without unsafe-eval
using mocked services. Actual Amplify header delivery remains unverified.
See [the final web report](../.staging/accelerated-completion-review-20261029/web/FINAL-WEB-REPORT.md).

## Phase 1 — renew access for the selected window

**Latest content review — October 29:** all requested existing access-stack and
role content checks match the reviewed baseline. The owner supplied complete
current template/trust/policy exports, configuration observations and verbatim
DescribeStacks/GetRole metadata, including the exact last change-set ARN,
rollback flags, immutable role ID and path. These remain owner-reported Console
evidence, not direct account API reads by that content review. The owner then
clarified estimated inspection windows (exact times unknown): DescribeStacks
00:58–01:05 EDT and GetRole 01:17–01:23 EDT on October 29. Using the earliest
bounds, their 30-minute cutoffs are 01:28 and 01:47 EDT. Those newer metadata
estimates do not refresh older policy exports. All content checks remain PASS;
one consolidated read-only source snapshot is pending for freshness.

After the deployer session was renewed, independent October 29 reads verified
its exact identity at 01:28 EDT, the core/API/ValidateTemplate checks at about
01:29 EDT, and private bucket/encryption/ownership/exact-key absence at 01:33
EDT. Core status remains UPDATE_COMPLETE with 40 resources, endpoint disabled,
external stage inactive and zero deployments. These records retain their actual
times and will be refreshed if stale before writing. No upload or new change
set has been attempted. Existing preparation approval remains recorded;
execution and Lambda tests remain separately approved steps.

Proposed window: **Friday October 30, 2026, 6–8 PM EDT**, or
**2026-10-30T22:00:00Z inclusive to 2026-10-31T00:00:00Z exclusive**.
The role session maximum remains 3600 seconds; the permission window does not
create a two-hour session.

Reuse `actionbridge-dental-staging-synthetic-test-access` and its existing
`actionbridge-dental-staging-synthetic-tester` role. The complete proposal changes
only 15 date values from the expected baseline: Allow expirations, explicit
before-start/at-expiry Denies, trust dates, description, expiry tag, metadata and
outputs. All actions, six exact function resources (three unqualified plus their
`:$LATEST` ARNs), principals, MFA/TLS, region limits and other safeguards remain.

The proposed template is 14,173 bytes, SHA-256
`83d03af9ce1b836e3b424a4d3e58195244e0782cb1d1773c6c9531e9e32a67f8`.
Expected change set: **zero additions, one SyntheticTestRole modification, zero
removals, Replacement False**. No direct IAM editing or additional role is needed.
The October 29 independent review reconfirmed the complete fifteen-leaf diff,
unchanged policy/trust action/resource/principal arrays and all protected
controller/T01 hashes. Saved complete owner exports equal the expected original;
**fresh full live comparison is still pending**, so no application is recommended
from resource count alone. See
[the independent review](../.staging/accelerated-completion-review-20261029/final-independent-review/REVIEW.json).

The approved preparation scope is limited to fresh baseline/identity checks, AWS server-side
validation, exactly one checksum-verified private S3 upload with no overwrite or
retry, and one owner-Console review-only UPDATE change set. The exact upload and
review scope is recorded in
`.staging/completion-review-20261028/phase1-access/NEXT-ACCESS-PREPARATION.FOR-APPROVAL.json`.
Stop if the live template or policy differs from the expected baseline.

After the complete actual change set passes independent review, request separate
approval for execution of its exact ARN. Then verify live IAM and backend/API
state. The new controller intentionally has no change-set binding and fails
closed. Bind only the actual reviewed/executed ARN in a separately audited local
release. No test execution is authorized by access preparation or execution.

## Phase 2 — prove the core backend

Request separate approval for exactly **20 new attempts**, **21 cumulative** and
**three cumulative Health attempts**. New caps are Health 2, Cases 11 and
Calculations 7. T21 and T22 remain SKIPPED; do not create accounts or alter
allowlists to enable them.

Before dispatch: verify actual identities, fresh successful tester login and
subsequent STS evidence, live policy/time bounds, `UPDATE_COMPLETE`, disabled API,
inactive external stage, function/artifact pins, the immutable manifest and all
original evidence. Run AWS CLI authentication/reads serially, preserving existing
profiles. Use the unchanged 20-minute admission and three-minute dispatch
margins. No automatic renewal, deadline extension, retry, reset or resumption.

Record an attempt durably before every synchronous dispatch. Stop immediately
after an unexpected response or uncertain outcome. Verify request IDs,
FunctionError, revisions, ledger/transaction outcomes, fictional records and
seven-day TTL evidence. Required arithmetic remains **120000 patient cents** and
**72500 conditional alternative cents**. Do not manually delete records.

Passing direct Lambda tests proves neither real Cognito sign-in nor API Gateway
JWT/signature, HTTP or browser behavior. Those remain NOT TESTED until Phase 3.

## Phase 3 — connect and release the synthetic core website

After backend tests pass, prepare one bounded approval proposal covering the
required API/Cognito configuration, controlled test requests, exact hosting
origin and existing Amplify staging app. Use existing approved synthetic accounts
where available; account creation or allowlist changes require their own stated
approval. Preserve other accounts, APIs and production infrastructure.

Verify the 13 protected routes and public health route, real login/refresh/logout,
missing/invalid/expired/wrong-issuer/wrong-audience JWT rejection, ownership,
revision conflicts, errors and exact-origin CORS. The saved core currently allows
localhost origins; the actual Amplify HTTPS origin needs an approved update.
Define a bounded HTTP write budget and synthetic records first, including how it
differs from jobs/upload/speech quotas: core cases, strategies and comparisons
have no matching admission quota. Do not raise quotas or delete old data.

The current web flow uses Cognito USER_PASSWORD_AUTH, REFRESH_TOKEN_AUTH and
RevokeToken with a public client. Hosted UI/PKCE callbacks are not prerequisites
for this implemented flow. Preserve existing MFA; unsupported challenges must
fail closed. Observe real revocation responses, and document that an issued JWT
can remain valid at API Gateway until expiry. A JWT with an edited claim and an
invalid signature does not independently prove issuer/audience rejection.
Unavailable authentic negative-token or second-owner cases remain NOT TESTED.

An actual HTTP test needs separately approved endpoint activation and a deployment
snapshot attached to the external stage. Keep AutoDeploy false. Public endpoint
activation makes the service Internet reachable, so approve it explicitly after
security preflight. The fallback is disabling the endpoint; verify supported
stage/snapshot recovery operations before proposing any additional rollback.

Saved deployer IAM is API Gateway GET-only. Its execution ceiling omits the
/deployments paths and its CloudFormation resource-type filter omits
AWS::ApiGatewayV2::Deployment. Do not assume existing deployment authority
permits snapshot creation/attachment. Prepare an expressly approved owner path
or narrowly reviewed workflow for only l52iwors8c. Do not import or return the
external stage to CloudFormation ownership. Testing from the already allowed
localhost origin can precede hosting; CORS does not block non-browser callers.

The separate proposed HTTP budget is 64 API requests, including four committing
operations, two deliberate same-key replays and three rejected write-intent
tests, plus at most four Cognito operations. Expected persistent effect is
eight items under one new fictional case with seven-day TTL. This is additional
API-triggered Lambda usage, **outside the direct 20-new/21-cumulative scope**.
Freeze a distinct HTTP manifest/ledger and count browser GET retries. Never
retry uncertain writes or run the 220 mocked suite against AWS. Full accounting,
pass criteria and the staged approval package are in
[the controlled HTTP/publication proposal](../.staging/accelerated-completion-review-20261029/web/CORE-HTTP-AND-PUBLICATION.PROPOSED.md).

Use the existing Amplify app, not a new hosting service. Verify its actual app,
branch, headers/CSP, SPA rewrites, public environment bindings and exact origin.
Exercise create/edit/calculate/save/reopen/compare, ledger and session recovery
against the real backend; live mode must never fall back to mocks. Keep worker,
upload, voice/background and live AI features visibly disabled. Publish only
after these checks and publication-rights clearance, with explicit approval and
a reviewed hosting rollback.
Reuse the recorded existing app `d26l7o8g7xduis`; refresh its actual staging
branch/domain/configuration before release. The saved app contains SPA fallback
but no CustomHeaders/CSP. A localhost CSP smoke is not proof of AWS delivery.
Stopping a hosting job alone does not withdraw an already published artifact.

## Phase 4 — complete the intended AI features

The historical full template has 23 deferred backend resources: two functions,
two log groups, two queues, a private bucket, an event-source mapping, seven
routes, one integration and seven Lambda permissions. Two runtime roles and
their boundaries are retained in the saved owner access template; freshly
verify them rather than creating replacement roles. The count is an inventory,
not deployment approval.

Do not deploy that historical template verbatim: it still manages a stage with
AutoDeploy true. Carry forward the external-stage exclusion and completed core
repairs. Review the new Jobs/Worker encryption contexts, grants and runtime
boundaries; completed KMS permissions currently protect the three core functions
and do not establish permission for the deferred functions.

Prove mapping create/read/delete/read-after-delete rollback behavior and keep it
disabled until worker activation is approved. Set a safe nonempty-bucket
retention/rollback plan. Review quotas, concurrency, leases, DLQ, SDK retries,
costs, TTL/log retention and upload/Transcribe/Textract cleanup. Obtain explicit
budget and infrastructure approvals before deployment or service calls.
Explicitly set mapping Enabled=false: omission defaults to enabled. Preserve
the private upload bucket/PAB/SSE-S3 and queue-managed encryption; add/review an
enforceable bucket TLS policy, absent from the saved 23-resource inventory.
A corrected resource count may therefore change. Saved Jobs/Worker boundaries
have no KMS Allow; core KMS success does not prove those new encryption paths.

Resolve service geography before activation: Polly source targets us-east-1,
and the saved Nova inference profile spans us-east-1/us-east-2/us-west-2. This
needs an explicit decision against the recorded Ohio-region requirement.
Complete adversarial financial/clinical output tests: dollar-sign checks and
prompts do not prove that worded amounts, guarantees or urgency claims are safe.
AI interprets/explains; only the deterministic engine calculates, and dentists
decide timing. Real AI integrations remain unverified.

**Completed local repair:** the earlier eight-scenario audit reproduced five
unsafe accepted explanations. The optional explanation now accepts only one
strict JSON selection of an existing engine scenario; application-owned text
renders financial roles, differences and dentist/conditional caveats. Raw model
prose, amounts, extra fields, unknown scenarios and tool/mixed blocks are
rejected to the existing fallback. Intake closing prose is also discarded in
favor of the existing deterministic count summary. No public contract,
financial fixture, controller or frozen core/frontend artifact changed.
Twenty-eight new adversarial regressions passed; strict root typecheck and
**613 tests across 49 files passed**. This supersedes the verified pre-fix
585-test count. A separate independent review passed 29 mocked probes and
verified the three frozen core artifacts/source maps and T01 evidence unchanged.
Those probes are not added again to the application-suite count.
It does not establish real Bedrock adherence, extraction
accuracy, service costs, privacy or AI infrastructure readiness. Preserve the
original pre-fix probe as historical evidence. See
[the repair report](../.staging/accelerated-completion-review-20261029/ai-security/local-explanation-repair/REPAIR-AND-OFFLINE-VERIFICATION.md).

## Phase 5 — release clearance and cleanup

Preserve original authors, contributors, notices and Git history. The local
security audit found historical shared demo-account credentials; do not probe
them. Obtain private confirmation from the responsible administrator that the
password was revoked/rotated and sessions invalidated, or the account disabled.
This is not evidence of exposed AWS keys and does not authorize unrelated IAM
changes. Record status/time only, never credentials.
The fresh value-free scan covered 529 current text candidates and 1,133
historical text blobs across 85 reachable commits. Ten historical shared-account
blocks remain; no new credential class was found by those heuristics. This
does not prove revocation, inspect every archive or clear publication rights.

Confirm permission to publish/redistribute the modified code, website and brand.
There is no established repository-wide license; the existing Expo notice does
not license all contributors' work. Historical media/design archive rights also
remain unresolved. The new notices package passes its artifact gate, which is
not a substitute for these rights or live application verification.

After release checks, propose separate cleanup/revocation for the expired test
access and temporary helper stack/grant. Protect the external staging stage and
consumed marker. Verify what CloudFormation would delete before approval. No
manual data deletion, marker reset or automatic cloud cleanup is authorized.

Declare the synthetic core website functional only after bounded direct tests,
real Cognito/JWT/CORS checks, authoritative browser save/reopen/edit/compare and
financial/ledger results, secure hosted HTTPS headers/deep links, verified
retention/encryption, and credential/rights clearance. Live mode must not fall
back to mocks; unfinished AI/upload/voice stays visibly disabled. This core
milestone is separate from completion of the intended AI features.

## Actual verification results and limits

| Local verification | Result |
|---|---|
| `npm run check` | Original 585/48 PASS; then 613/49 after AI guard repair; current strict check + 619/50 PASS after six paid-SDK retry regressions |
| Browser suites | 220 mocked Chrome tests PASS; three independent auth scenarios and one production-CSP smoke separately PASS |
| Independent deferred-AI repair review | 29 mocked probes PASS; frozen core artifacts and original evidence unchanged |
| Infrastructure/security suites | 367 + 15 = 382 offline tests PASS; claimed 549 not established |
| Separate mobile project typecheck | PASS under Node 22.23.4 |
| New isolated controller with mocked AWS only | 126 tests PASS |
| Independent controller/template audit | 72 checks plus 7 UUID checks PASS |
| Proposed policy/trust evaluation | 118 policy and 10 trust cases PASS |
| CloudFormation local lint | 0 errors; 6 unchanged W3037 sign-in action-catalog warnings |
| Release scanner/notice gate | 15 tests PASS; final local ZIP PASS |
| Web typecheck/build | PASS; existing Rollup/chunk-size advisories remain |
| Preservation and whitespace checks | Original evidence/releases unchanged; PASS |
| AWS server validation of the exact candidate | PASS during subsequently approved read-only preparation |
| Latest recorded backend/API metadata | October 29 approximately 14:29 EDT: UPDATE_COMPLETE/normal rollback, preserved API endpoint disabled/localhost CORS, table ACTIVE/KMS enabled; stage/snapshots and full resource inventory still require refresh |
| Synthetic-access IAM/stack content | Live deployer/tester trust and session duration verified through ListRoles; saved complete owner exports/metadata PASS; fresh full inline-policy/stack comparison PENDING |
| Live functional tests | NOT RUN |

The original local review made no AWS calls. Subsequent approved preparation
performed read-only checks and server template validation, then stopped at the
access-stack read denial. No Lambda attempts, uploads, change sets, deployments,
activation, publication or cloud cleanup occurred. This roadmap does not claim
the application is fully tested or released. All remaining cloud actions need
their explicit approvals above.
