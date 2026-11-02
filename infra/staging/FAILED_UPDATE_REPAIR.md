# Staging UPDATE failure: local IAM repair for owner review

**Later v2 export finding:** guardrails-01 contains the intended repair, but
identity-03 still contains its original three statements. See
[LIVE_V2_POLICY_DIAGNOSIS.md](LIVE_V2_POLICY_DIAGNOSIS.md) for the current,
identity-03-only correction. The two-policy proposal below records the earlier
review and must not be reapplied blindly.

Target: account **631367363628**, Region **us-east-2**, existing stack
**actionbridge-dental-staging**, API **l52iwors8c**.

This repair is **unapplied**. The diagnostic calls were read-only. No live IAM
policy, resource, change set, Cognito user, deployment, artifact object or Git
history was changed. The existing five uploaded Lambda ZIPs are reused.

## Confirmed events and current resources

The complete event history was retrieved: **34 events, one complete API page**,
including the earlier bootstrap and the failed UPDATE. The failure started at
9:13 p.m. EDT on October 25, 2026 (01:13 UTC October 26). Rollback finished at
9:20 p.m. EDT with `UPDATE_ROLLBACK_COMPLETE` and the warning that a resource
could not be deleted.

| Event | Finding |
| --- | --- |
| HealthFunctionRole CREATE_FAILED | `iam:GetRole`, explicit denial naming `actionbridge-dental-staging-cfn-guardrails-01` |
| HealthFunctionRole DELETE_FAILED | `iam:DetachRolePolicy`, same named policy; three attempts |
| CasesTable, UploadBucket, JobDeadLetterQueue CREATE_FAILED | Each says `Resource creation cancelled`; these are not independent permission errors |
| CasesTable, UploadBucket, JobDeadLetterQueue cleanup | Each subsequently reached DELETE_COMPLETE |

Fresh exact-name reads found **all five runtime roles absent**, including
`actionbridge-dental-staging-health-role` (`GetRole: NoSuchEntity`). The five
functions and staging table are absent, and all five exact log-group searches
are empty. CloudFormation now lists only the existing HttpApi. Its physical ID
is still `l52iwors8c`, and its default endpoint is still disabled.

The two queue lookups return `NonExistentQueue`; the upload bucket HEAD returns
404. Those responses alone do not establish globally available names or resolve
all access ambiguity. The dead-letter queue and upload bucket additionally have
successful CloudFormation deletion events. Do not adopt any name that later
exists. No manual cleanup is warranted by the role checks.

Private, sanitized evidence is in:

- `.staging/failed-update-readonly-20261026T012948595926Z.json`
- `.staging/failed-update-artifacts-reverified.json`

## Exact local policy defect

In the original generated `guardrails-01.json`, **`/Statement/5`** is
`Deny iam:*` with `NotResource` containing only the five intended, path-qualified
runtime-role ARNs. The original `identity-01.json` likewise grants role reads and
cleanup only against those path-qualified ARNs (`/Statement/10`; managed-policy
detach grants are in `/Statement/1,3,5,7,9`).

IAM role calls take `RoleName`, without a Path argument. Authorization for a role
that is not yet visible or is already absent can use its root-path alias, outside
that `NotResource` list. The local policy model reproduces both recorded denials
for that request context. Adding an Allow alone leaves the explicit Deny active.
The events identify the policy name, not its statement index or evaluated ARN;
the missing-role ARN explanation is an inference from those events, the generated
documents and the fresh absence checks. It is not a captured CloudTrail request.

The role-specific boundary guards (`/Statement/7,9,11,13,15` in the original
guardrail) are **retained**. AWS supports boundary conditions on the existing-role
policy/trust operations. They must not be broadly removed because those APIs lack
a PermissionsBoundary request argument. Tagging remains separately scoped.
[IAM authorization reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_iam.html)

Live execution-policy documents are unreadable to the developer (`iam:GetPolicy`
denied), so an owner must compare the actual default versions with the preserved
local baseline before authorizing any replacement.

## Proposed permission changes

The owner proposal is the **five-part minimal bundle** at
`.staging/execution-repair-minimal-l52iwors8c/`, not the freshly partitioned
reference bundle at `.staging/execution-repair-l52iwors8c/`. All original files in
`.staging/execution-review-l52iwors8c/` remain unchanged.

Only `guardrails-01.json` and `identity-03.json` change. The other three policy
documents remain byte-for-byte identical. No new managed-policy attachment is
needed. Exact replacement JSON, unified diffs, baseline hashes and compact sizes
are recorded together in the minimal bundle.

| Target/request | Proposed behavior |
| --- | --- |
| Exact five root aliases: GetRole | Allow read for creation stabilization and cleanup |
| Exact five root aliases: DetachRolePolicy | Allow only the already-approved managed policy ARN, with absent boundary context |
| Worker alias policy list | Basic execution policy plus the SQS execution policy |
| Other four alias policy lists | Basic execution policy only |
| Alias detachment with any boundary present | Explicit Deny |
| Any other alias operation, including create, attach, inline policy, trust, tags, delete or PassRole | Explicit Deny |
| Intended path-qualified roles | Existing exact-role, paired-boundary, policy-allowlist and Lambda-only PassRole restrictions retained |
| Other roles, protected boundaries and execution role | Existing explicit denials retained |
| Existing API, other services and production resources | Unchanged selectors and restrictions |

The guardrail's global exclusion is corrected, rather than overridden. Equivalent
managed-policy denials are grouped to fit the existing policy-size limits. The
required alias-mutation Deny supplements are in **identity-03**, which is mandatory
alongside both guardrail documents. It already contained Deny statements before
this repair; its filename does not mean it contains only Allows.

## Bounded cleanup risk that needs owner acceptance

`Null: {"iam:PermissionsBoundary": "true"}` checks key absence, **not resource
existence**. An existing unbounded root role with one of these exact reserved
names has the same relevant context as a missing role. Consequently, the cleanup
exception could detach the allowlisted logging policy (or worker SQS policy) from
such a role. It cannot create, attach, pass, change trust, change inline policies,
remove a boundary, or delete that root role.

This distinction is an inference from AWS's documented
[Null-condition semantics](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements_condition_operators.html#Conditions_Null).
No IAM condition in this proposal proves that a role is nonexistent. All five
names were freshly verified absent; recheck them immediately before any future,
separately approved retry and stop if any name exists. A residual name must be
reconciled, not adopted or deleted automatically.

Boundary removal remains denied. IAM's documented DeleteRole prerequisites are
inline/managed-policy and instance-profile cleanup, not a new boundary-removal
grant. [DeleteRole API](https://docs.aws.amazon.com/IAM/latest/APIReference/API_DeleteRole.html)

Local policy-decision tests do not certify AWS provider behavior, effective SCPs,
session policies, IAM propagation or other deployment actions that this early
failure never reached. The five existing artifact objects were rechecked for
size, full SHA-256 and SSE-S3; no rebuild or upload is needed.

## Fresh local verification

**72 tests passed** with the installed Python and no new dependencies:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=infra/tests python3 -m unittest \
  test_staging_artifacts test_staging_boundaries test_staging_execution \
  test_staging_policies test_staging_role_lifecycle test_staging_execution_repair
```

The request-context matrix runs against both the corrected generator and the
exact five-part owner proposal. It covers the original explicit-deny failure,
creation, rollback detachment, missing/wrong boundary and policy values, protected
root roles, unrelated paths/accounts, PassRole, policy/boundary mutation, and API
scope. Tests also verify policy-size limits, unchanged bytes, rejection of baseline
drift and symlinks, exclusive output, and exact reconstruction from the recorded
JSON patches. Unknown condition operators fail the local evaluator.

The five runtime-boundary drafts and bootstrap policy consistency checks also
passed. No application code or CloudFormation template changed in this repair;
application and template suites were not rerun.

## One next owner action

**Review the two proposed policy replacements and their diffs against the actual
default policy versions, including the bounded cleanup exception, and approve or
reject an IAM-only correction.** Do not apply them or retry deployment as part of
that review. This task has not authorized any live policy change.

If application is separately approved later, the safe order is identity-03 first
(install the alias restrictions while the old global exclusion still fails
closed), then guardrails-01. Keep all other parts and attachments intact. A future
change set and its execution each require separate approval and fresh verification
of 42 additions, one in-place HttpApi change, zero removals and the existing API ID.
