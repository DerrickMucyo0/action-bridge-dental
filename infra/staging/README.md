# Independent staging preparation — local drafts only

**Current forward repair:** use [CORE_FORWARD_REPAIR.md](CORE_FORWARD_REPAIR.md).
Recovery A is complete at UPDATE_ROLLBACK_COMPLETE. The identity-only literal
stage-tagging proposal remains withdrawn. The two recognized HTTP replacements
have passed owner-reported Console validation and combined policy review;
live application is unapproved and tagged CreateStage remains runtime-unproven.
No new change set or deployment is authorized. Completed prerequisites and
recovery must not be repeated. The setup instructions below are historical. Earlier IAM failure analysis remains in
[FAILED_UPDATE_REPAIR.md](FAILED_UPDATE_REPAIR.md).

Target: **631367363628 / us-east-2 / actionbridge-dental-staging**.
No AWS login/API call, resource or IAM change, deployment, Cognito/Vercel change,
commit or push was performed. Existing application code, shared dev/demo template,
website design, Git history and unrelated local work are preserved.

The owner reports 153 resources, mostly default networking, with no obvious
production application infrastructure. **The inventory is incomplete.** Other
Regions, services, IAM and resource policies still need scoped review. The original
website's backend is in teammate account `195469705669`.

## Historical initial setup action — already completed

The print-only plan has already been reviewed. The next human action is for an
authorized non-root administrator in `631367363628` to review
[collision-read-policy.json](collision-read-policy.json), then grant the approved
customer-managed policy to the existing `actionbridge-developer` user.
Follow [COLLISION_CHECKS.md](COLLISION_CHECKS.md) for the console steps, precise
scope exceptions and the separately gated runner.

The original plan remains print-only:

```bash
python3 infra/staging/collision-checks.py --profile YOUR_AUTHORIZED_ADMIN_PROFILE
```

This prints 32 read-only checks and executes none. Do not pipe it into a shell.
An authorized administrator reviews/runs the individual reads, starting with the
account/non-root check, and records collision findings privately. Denied,
incomplete or ambiguous results mean unknown. No new inventory finding is
claimed by local preparation.

The separate [run-collision-checks.py](run-collision-checks.py) is offline by
default and requires both explicit execution/approval flags and successful
authentication as the exact existing developer user before resource reads. It
reports AVAILABLE, COLLISION and UNKNOWN, including errors. S3 failures, SQS
missing/access ambiguity and missing root-path policy ARNs remain UNKNOWN.
No real execution was performed during local validation.

Follow [RUNBOOK.md](RUNBOOK.md) for the complete ordered owner checklist,
approval gates, local checks and future deployment steps.

## Prepared files

- [resources.json](resources.json): exact staging function, role, boundary,
  table, bucket, queue, API and log selectors.
- [collision-read-policy.json](collision-read-policy.json): eleven read-only
  actions covering the 32 checks, bound to the existing developer identity with
  only the necessary metadata/global exceptions. This is an additional grant,
  not a permissions boundary or deployment permission.
- [generated/bootstrap.yaml](generated/bootstrap.yaml): one empty HTTP API,
  endpoint disabled, no stage/routes/identity resources.
- [generated/backend.yaml](generated/backend.yaml): offline-expanded 69-resource
  backend, five named roles with distinct boundaries, zero Cognito resources.
  This is a same-stack UPDATE after bootstrap and requires
  `CAPABILITY_NAMED_IAM`. Both phases retain `HttpApi`, its name and
  `ProtocolType: HTTP` and a disabled endpoint; routes, integrations and authorizer
  are explicit child resources. API replacement is forbidden during review.
- Five `generated/actionbridge-dental-staging-*-boundary.json` files: independent
  role-specific ceilings with explicit action/resource/context denials.
- [generated/bootstrap-execution-policy.json](generated/bootstrap-execution-policy.json):
  constrained API creation/read draft. No existing-API writes.
- [build-execution-policy.py](build-execution-policy.py): generates an offline
  backend identity/guardrail policy review bundle only after a reviewed API ID is
  supplied. It validates syntax, not ownership. Parts fit managed-policy limits;
  they are not a single execution permissions boundary.
- [change-set-preparer-policy.json](change-set-preparer-policy.json): exact stack,
  execution role and two review change-set names; artifact prefix only; explicit
  execution, direct-stack and import denials. No SAM-transform permission is
  needed for the generated plain CloudFormation templates.
- [preflight-read-policy.json](preflight-read-policy.json): existing scoped reads
  plus the five proposed boundaries. It is not an account-inventory grant.
- [cloudformation-trust.json](cloudformation-trust.json): unchanged service-only
  trust. See [execution-role-review.md](execution-role-review.md) before IAM approval.
- [build-templates.py](build-templates.py), [build-boundaries.py](build-boundaries.py)
  and [package-artifacts.py](package-artifacts.py): offline generation and local ZIP
  preparation. These generators do not execute AWS or open identity parameters.

## Private identity configuration

The two test users are already confirmed. Preserve them. The local
`.staging/parameters.json` is Git-ignored, untracked and untouched, with mode
`0600` inside a `0700` directory. Only Git status/ignore rules and file metadata
were checked; no private tester IDs or parameter values were read or displayed.

The previously supplied public identity candidates remain pool
`us-east-2_GErUtH894` and client `7uotveip0c7k931lv2te275fjg`. Their owning account,
client membership, public-client/no-secret settings and direct sign-in flows
require authorized verification. A working login on the original website does
not establish ownership in the target account. No pool/client/user creation,
confirmation or reset is part of this work.

The existing [set-approved-testers.py](set-approved-testers.py) remains unchanged
and was not run. There is no need to replace your approved users. Keep their
subjects out of chat, logs, command arguments and browser environment variables.

The generated backend accepts the legacy common-boundary parameter for private
file compatibility but ignores it: the five fixed boundary ARNs are authoritative.
Do not deploy the generic source template using the earlier single-template
CREATE instructions. Use the separately reviewed bootstrap CREATE/backend UPDATE
process in the runbook.

## Remaining gates

Exact-name collision findings; production-resource exclusions; administrator
review/provisioning of all five boundaries and execution policies; artifact bucket
approval; intended identity ownership/settings; current Nova profile destinations
and access; synthetic-only spend/retention controls; review and separate approval
of each exact change-set execution. Neither the incomplete inventory nor passing
local tests authorizes deployment. No account access was attempted to resolve
these gates.
