# ActionBridge Dental — Finish Roadmap
**Date:** October 29, 2026  
**Repository:** `~/Desktop/action-bridge-dental-visual`  
**Goal:** Close actual unfinished work, verify the core web product end to end, and complete the intended AI features without rebuilding finished work or weakening AWS controls.

## 0. What “finished” means

**Core staging website DONE:** Real Cognito authentication and protected API routes work; a fictional case can be created, revised, saved and reopened; deterministic dental insurance/treatment costs and two-plan comparisons show correct figures and missing-information caveats; charts and PDF export agree with engine outputs; cross-user isolation and failures are handled; the website is available at the verified Amplify staging HTTPS URL; there is an approved rollback path and retained evidence.

**Complete AI application DONE:** In addition to the core, the deferred AI infrastructure and real Bedrock/Polly/document-job workflows are deployed, encrypted, authorized and independently tested for revision safety, privacy, invalid inputs, model claims, retries/idempotency and rollback. Local mock tests are not live proof.

**Release DONE:** Historical exposed credentials are confirmed revoked/rotated, third-party assets have verified rights or replacements, existing collaborator authorizations and Git attribution are preserved, no secrets or patient data are published, release documentation accurately labels supported/unsupported dental-insurance rules, and final owner sign-off is recorded.

The priority is **a working, verified core staging website first**. Full live AI is a separate release gate. Work toward both today, but do not claim success or set an arbitrary time estimate when the live evidence does not support it.

## 1. Verified or reported baseline — do not rebuild

| Area | Best available evidence (October 29 reports) | Remaining proof |
|---|---|---|
| Application code | **613 application tests** passed after 28 AI safety regressions; local sign-out/account-switch fixes and model-claim guards reported | Check current commit/worktree and final targeted regression only if files changed |
| Browser UI | **220 mocked Playwright scenarios** reported passing | Genuine Cognito/API/browser end-to-end flow still missing |
| Infrastructure/security | **367 infra + 15 security = 382 offline checks** reported; Gemini's 549 claim not substantiated | Real AWS state and deployment behavior |
| Frontend artifact | Unpublished `frontend.zip`, **723,745 bytes**, SHA-256 `8072f765bf5a4e608bf56ee57e9c87e0280e32eb8d9c08e4ccdbd247c850313d` | Artifact versus current source and real served build |
| Core backend | `actionbridge-dental-staging` reported `UPDATE_COMPLETE`, **40 resources**; latest developer-session reads reconfirmed stack, KMS-encrypted cases table | Live Lambda workflow and persistence behavior |
| API | `l52iwors8c` preserved; execute-API endpoint **disabled**; CORS currently localhost-only; external `staging` stage inactive/no attached deployment | Reviewed activation path, actual JWT/CORS/HTTP tests |
| Test ledger | T01 already consumed; original T01 ledger and nine evidence files preserved | Approved new run under strict attempt accounting |
| AI | Local job duplicate-prevention and explanation safety work reported | **23 deferred cloud resources**, KMS/IAM and real model workflow |

Treat this as **reported evidence**, not a fresh, direct inspection of the Mac or AWS. Read the local source reports and verify discrepancies; do not rewrite success claims into live proof.

## 2. Feature inventory and scope lock

The earlier feature plan was **one dental treatment compared under Plan A versus Plan B**, built by extending the existing deterministic insurance engine, not creating a new platform. Existing/reported web functions to trace and smoke test, not reimplement:

- PPO-style treatment estimation (six supported procedures), deductible, coverage rates, annual maximum and insurer/patient portions, using **integer cents and basis points**.
- Plan A / Plan B comparison on the **same confirmed treatment**, the patient's responsibility and comparable difference only when both results are complete; equal-cost case and `needs_information` when data is missing.
- Existing treatment-timing/cash comparison, case create/edit/save/reopen, revision locking, ledger/history, saved comparisons and user-scoped access.
- Accessible desktop/mobile-width web UI, chart/table equivalents, PDF export of authoritative server-calculated figures, assumptions and disclaimers.
- Cognito login/logout/account switching, JWT validation and secure API error/retry handling.
- AI document/assistant/job features only as **separately gated** cloud release; no model-generated financial or clinical claims.

**Not v1:** direct insurer integrations, premiums as a full plan-price model, waiting periods, exclusions, frequency restrictions, benefits enrollment, payments, clinical scheduling, new extraction architecture, or mobile-app expansion. Do not silently invent these features or claim them supported. Use **fictional test cases only**, never actual patient information.

**Rights:** Student-contributor authorization to work on/redistribute was already reported. Do **not** re-ask those contributors by default. Still verify third-party images/assets, license notices and historical exposed credentials before any public publication. Preserve original Git history and authorship.

## 3. Critical path: workstreams in dependency order

### Phase A — One decisive local gap audit (start immediately; no AWS writes)
**Owner:** Codex. **Status:** Ready locally.

1. Read `AGENTS.md`, `docs/COMPLETION_ROADMAP.md`, `docs/DECISIONS.md`, existing `.staging` reports and test receipts. Identify current branch, dirty files, frontend ZIP and code hashes; do not reset worktrees or erase historical evidence.
2. Create **one** feature-by-feature matrix: `present in code`, `mock-tested`, `real AWS-tested`, `ready to release`, and `blocking issue`. Map each to actual source files/tests. Mark unsupported items explicitly.
3. Rerun only necessary **targeted** local checks after the recent auth/AI fixes, plus final build/artifact check; do not repeat hundreds of tests without a change or evidence requirement.
4. Fix only verified local bugs, with regression tests. Keep code changes small. Distinguish production blockers from cosmetic improvements. Document the 549-versus-382 test-count discrepancy.

**Exit:** A single sorted blocker list, all high-impact local defects fixed or clearly blocked, no unknown extra features.

### Phase B — Restore trustworthy AWS identity and collect one fresh baseline
**Owner:** Codex + user only for MFA/browser owner action. **Status:** Authentication work in progress.

1. Use existing authorized developer identity for permitted read-only information; existing deployer role must resolve to the correct **assumed-role ARN** before deployer-only calls.
2. The browser CLI login has offered the underlying `actionbridge-developer` user and requested overwriting the deployer role profile. **Never accept that overwrite.** The existing user normally uses password plus a six-digit MFA code. Codex reported `iam:ListMFADevices` denied; do not assume the device is absent, ask for MFA codes or modify IAM. Use supported MFA-protected role assumption with authorized owner readback if required.
3. Independently verify STS account/ARN and current statuses: backend stack, Lambda names, DynamoDB table, API disabled/stage, testing access stack and expiration, Cognito identity, CORS and Amplify application/branch. Treat an AccessDenied or expired session as **unknown**, not proof of absence.
4. Batch expiring reads immediately before the action that requires them. Reuse stable IAM/trust/export evidence; no recurring screenshot loops.

**Exit:** Exact expected identities, fresh safety state and a written list of any truly unavailable owner-only fields.

### Phase C — Narrow renewal of the EXISTING synthetic-test role
**Owner:** Codex prepares; user authorizes separate AWS gates. **Status:** Blocked for execution pending current review and approval.

1. Only update the existing `actionbridge-dental-staging-synthetic-test-access` role through a fully reviewed exact template/change set; **no broader trust, IAM, KMS or resource privileges**.
2. A previous **October 30, 6–8 PM EDT** window was proposed, not a permanent requirement. To test on October 29, propose a genuinely future, feasible window with its own reviewed deadline/margins; never reuse expired dates or quietly extend them.
3. Reconcile live and proposal trust, 3600-second session, MFA/TLS, region, six function/$LATEST resource ARNs and explicit before/after expiry denial.
4. **Separate gates:** (a) private S3 template upload and review-only change-set creation; (b) exact change-set execution and read-back verification; (c) exact limited synthetic run. Do not infer execution approval from preparation approval.

**Exit:** Verified role conditions are currently valid and controller/change-set binding matches exact reviewed ARN. Otherwise remain NO-GO.

### Phase D — Live backend synthetic tests
**Owner:** Codex within separately approved test scope. **Status:** Not executed in revised run.

1. Preserve original T01 and **all nine evidence files** unchanged.
2. Enforce **20 new attempts / 21 cumulative attempts / 3 cumulative Health attempts**. Both optional tests **SKIPPED**. Identify new attempt IDs distinctly from consumed T01, avoid duplicate reservations and honor stop-on-uncertainty. No unintended Lambda DryRun/invocation.
3. Test real Health, Cases and Calculations functions, persistence/reopen, revision conflicts, user isolation, ledger and saved plan comparisons; confirm pinned fictional test figures, including **120000 baseline cents**, **72500 alternative cents** and **47500 difference** where those are the actual fixtures.
4. Stop immediately on access mismatch, unexpected resource behavior, error, quota accounting discrepancy or unreviewed mutation. Record evidence and rollback state, not retries by default.

**Exit:** Approved test set passed with actual AWS response evidence and no ledger violations. If failed, report exact test and minimal fix; do not proceed to API activation.

### Phase E — Real HTTP authentication and core staging site
**Owner:** Codex prepares; owner approves API/stage/hosting operations separately. **Status:** No live verification or publication.

1. Verify Cognito user pool, public app client, issuer/audience, callback/logout URLs, hosted or application sign-in, session expiry/logout/account switching; test invalid/missing/other-user JWT rejection.
2. Prepare the **minimum** owner-approved activation plan for existing API `l52iwors8c`: currently disabled endpoint, externally managed `staging` stage, `AutoDeploy:false`, no attached deployment. Preserve existing API ID and external stage ownership; do not create/overwrite a stage or snapshot with an unbounded permission. IAM may not restrict `CreateStage` request fields: if a fixed-request helper is needed, it and its temporary resources need their own review and setup approval.
3. Verify exact full Amplify staging **HTTPS origin**, not just app ID `d26l7o8g7xduis`; add precisely scoped CORS origin only after review. Verify JWT authorizer, routes, response headers, TLS, diagnostics and rollback.
4. Once test traffic is explicitly approved, run real **fictional-data** browser workflows: sign in, create case, edit/save/reopen, compare two plans, view equal/missing cases, ledger/chart/PDF, refresh, sign out, cross-user denial, retry and network errors.
5. Only then approve exact build hash, deployment branch and **Amplify publication**. Perform post-publication smoke tests, record website URL and rollback method; keep unfinished AI affordances disabled or clearly unavailable.

**Exit:** Core **staging** site is independently verified. Do not call mocked Playwright runs a live website test. Public repo and broader production launch require release gate below.

### Phase F — Intended live AI (separate release)
**Owner:** Codex prepares/local tests; AWS execution separately approved. **Status:** 23 resources deferred.

1. Inventory and reconcile the **23 deferred resources** (worker/jobs/queues/storage/routes/logging) against real template, roles and exact deployment plan. Do not deploy the historical template unchanged.
2. Decide and document Bedrock inference profile (`us.amazon.nova-2-lite-v1:0`), US cross-region routing, Polly `us-east-1`, permitted data destinations, costs/budgets, and privacy/retention controls. Seek explicit owner decision if any choice carries meaningful cost or data transfer.
3. Review KMS key policy and `CeilingNoUnlistedActions`, role boundaries and resource-specific `Encrypt/Decrypt/DescribeKey` dependencies, SQS DLQ/retry/idempotency, secure S3 bucket TLS/encryption/lifecycle, job worker and Lambda permissions, stage mapping changes and rollback. Preserve unrelated resources.
4. Execute only reviewed change sets through authorized roles. Verify real job lifecycle, upload, processing, failure/retry, stale-revision suppression, duplicate prevention, data deletion/expiry and model-safety evaluations without patient data.
5. Prove generated prose cannot change calculated financial/clinical claims; server/engine outputs remain authoritative.

**Exit:** Real AWS AI functionality and safety tests pass, with observed costs/rollback and release evidence. Otherwise correctly label AI **NOT LIVE**.

### Phase G — Release and handoff
**Owner:** Codex prepares, user signs off on publication/cleanup. **Status:** Outstanding.

- Verify historical demo credentials are revoked/rotated and not in build/archive/history; inspect `.env` and packaged assets without exposing secrets.
- Confirm third-party image/asset rights or replace unresolved items (including previously flagged welcome imagery). Preserve known student contributor permissions and Git history; do not solicit the same consent again without a concrete new issue.
- Final supported-features matrix, known exclusions, accessible UX, deployment/rollback docs, precise Git credit, privacy note and demo script; no patient data.
- Public repository and production publication each receive specific approval. Any CloudFormation/IAM cleanup or role removal is a **separate** destructive action.

**Exit:** Auditable final release with site URL, tested workflows, known non-goals, security and owner sign-off.

## 4. Today's execution rules (reduce friction)

1. **Immediately:** finish Phase A and any independent local work in Phase F/G while resolving Phase B. Do not pause all local work on AWS authentication.
2. **After access works:** use a single fresh AWS baseline and present **one next approval request**, with action, resource IDs, exact artifact/hash, expected diff, potential impact, rollback and stop conditions.
3. Complete Phases C→D→E only after their successive approval and verification gates. Do not combine a preparation approval with execution or traffic authorization.
4. In parallel, prepare all AI cloud changes locally, but do not silently mix them into the core staging stack.
5. User should be asked only for MFA/owner tasks that Codex cannot safely perform; **never** ask for codes, passwords, tokens or repeated screenshots without a specific necessity.
6. **No false deadline claim:** Attempt maximum safe progress October 29. If live AI or the core launch cannot pass the required gates, show the *exact remaining blocker* and leave the system safe, rather than declaring a premature launch.

## 5. Codex reporting contract

Create/update `docs/FINAL_COMPLETION_TRACKER.md` (locally) and report a compact table for each phase with one of:

- `DONE — LIVE VERIFIED`
- `DONE — LOCAL ONLY`
- `READY — WAITING FOR EXACT APPROVAL`
- `BLOCKED — SPECIFIC ERROR/OWNER ACTION`
- `NOT STARTED`

Each row must have (1) concrete evidence/command/path, (2) remaining condition, (3) next action/owner, (4) exact approval gate if applicable. Publish **one** consolidated next-action request instead of unrelated questions and repetitive audits. Do not claim completed work without proof.

**Never perform:** AWS writes, CloudFormation change-set creation/execution, IAM modification, Lambda Invoke/DryRun, API activation, Amplify publication, model/resource deployments, secret rotation or cleanup without the appropriate explicit approval. Local code changes, offline tests, planning and existing authorized read-only reads may proceed.
