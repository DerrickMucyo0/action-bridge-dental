# Worker mapping cleanup correction — local proposal only

The third deployment created worker mapping `35d44f01-0d10-4bae-9a76-60cd087e6d5e`, then rollback failed to read/delete it. The errors identify resource `*` and `actionbridge-dental-staging-cfn-guardrails-02`. The original mapping `NotResource` guard explicitly denies that shape, even when the exact staging worker condition is present. An additional Allow cannot override this Deny.

[AWS documents mapping ARN permissions and the `lambda:FunctionArn` condition](https://docs.aws.amazon.com/service-authorization/latest/reference/list_lambda.html), with [function-based mapping scoping](https://docs.aws.amazon.com/lambda/latest/dg/lambda-api-permissions-ref.html). The local proposal changes exactly two JSON fields:

| Existing policy | JSON pointer | Proposed value |
|---|---|---|
| `identity-02` | `/Statement/4/Resource` | `"*"` (exact worker FunctionArn and Ohio conditions unchanged) |
| `guardrails-02` | `/Statement/9/Action` | `["lambda:UpdateEventSourceMapping"]` (Get/Delete removed from this resource-ARN Deny only) |

The wrong/missing FunctionArn explicit Deny remains for Create/Get/Update/Delete. Update still requires the original regional mapping ARN through its unchanged `NotResource` restriction. IAM roles, paired boundaries, API restrictions, business-data denials, and unrelated resources are untouched. The other three policy parts are copied byte-for-byte. Both replacement documents fit 6,144 characters; no additional attachments are needed.

Prepare the exclusive local review bundle with:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 infra/staging/prepare-mapping-repair.py
```

The default output `.staging/mapping-cleanup-correction-review/` contains the five policy parts, exact patches, unified diffs, hashes, and review metadata. It pins the reviewed post-V3 local baseline and never calls AWS. Compare current live `identity-02` and `guardrails-02` with those pinned originals before any separately approved policy update.

This is **not a verified live cleanup fix**: the failure message does not reveal whether AWS supplied `lambda:FunctionArn`. Requests without it remain explicitly denied. Broadening to an unconditional wildcard would expose unrelated mappings and is deliberately excluded. Do not declare another deployment ready while the missing-context cleanup behavior remains unresolved.

The owner confirmed zero mappings and zero exact-UUID matches in the Ohio Console; the possible leftover mapping is accounted for and no deletion is required. The saved current live `identity-02` and `guardrails-02` exports match the pinned originals exactly. The owner also reported the execution role's CloudTrail `AccessDenied` event at **October 26, 2026, 12:35:51 AM EDT**, with `requestParameters: null`. That null field is not proof that the IAM FunctionArn condition key was absent or present. These supplied facts are accepted; no further CloudTrail inquiry is required.

If an absent mapping's cleanup request has only resource `*` and no FunctionArn, the two proposed fields are insufficient. A known and an unrelated UUID then have the same documented IAM inputs: Lambda exposes no UUID condition key for distinguishing them. Preserve the explicit denial rather than adding `IfExists` or an unconditional wildcard write fallback. Owner review of the conditional proposal is separate from approval to apply it or deploy.

## Draft AWS support question — local only, not sent

For account `631367363628` in `us-east-2`, CloudFormation rollback of staging mapping `35d44f01-0d10-4bae-9a76-60cd087e6d5e` reported `lambda:GetEventSourceMapping` and `lambda:DeleteEventSourceMapping` authorization against resource `*`; the mapping is now absent. What supported resource/condition policy lets CloudFormation complete Get/Delete `NotFound` stabilization while limiting the execution role to the exact staging worker `arn:aws:lambda:us-east-2:631367363628:function:actionbridge-dental-staging-job-worker`? In particular, which authorization context is supplied for an absent UUID, and how can this be supported without an unconditional `DeleteEventSourceMapping` permission on `*`? The role must retain restrictions protecting unrelated mappings, IAM roles, boundaries, API resources, and production infrastructure.

Tests evaluate the observed resource `*` with the correct worker context (Allow), missing/different worker context and wrong Region (explicit Deny), Create restrictions, explicit-Deny precedence, Update ARN isolation, and indistinguishable known/unrelated missing UUIDs. They also check unrelated resources, immutable baseline drift, size limits, and exact output patches. These offline decision checks are a bounded model, not an AWS IAM simulator or proof of the provider's live request context.
