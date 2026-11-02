# Current v2 export diagnosis: identity-03 is incomplete

Target: account `631367363628`, Region `us-east-2`, existing stack
`actionbridge-dental-staging`, preserved API `l52iwors8c`.

This is a **local-only diagnosis and unapplied proposal**. No AWS call, IAM
change, deployment, change set, deletion, upload or application request is part
of this correction. Original exports and earlier review bundles are preserved.

## Findings from the owner-saved documents

| Saved document | Content comparison |
| --- | --- |
| `.staging/live-policy-review/guardrails-01-v2.json` | Exactly the intended repaired guardrail: 14 statements, 5,989 compact characters |
| `.staging/live-policy-review/identity-03-v2.json` | Exactly the original identity-03: three statements, 1,013 compact characters; all five repair additions are missing |

Comparison parses JSON, ignoring whitespace and object-key order. The files are
distinct and are not swapped. The guardrail contains the expected five-role
restrictions; identity-03 contains the original exact-API permissions and regional
denials. Plain policy JSON does not itself prove the originating AWS policy ARN,
version ID, default-version flag or attachment. The current-v2 provenance is the
owner's supplied context, supported by the known content fingerprints.

The complete replacement already exists in the previously reviewed minimal
bundle. It has eight statements and 3,262 compact characters. Its first three
statements are identical to the saved identity-03 v2 document.

## Why the two actions fail

The new attempt's first failure was `HealthFunctionRole` / `iam:GetRole` at
11:11:18 p.m. EDT on October 25, 2026. AWS reported **no identity-based policy
allows the action**. Three later `iam:DetachRolePolicy` failures occurred during
rollback. These are different from the previous attempt's explicit guardrail
denials.

The repaired guardrail exempts five exact root-path aliases from its global
outside-resource denial. An exemption from Deny is not an Allow.

The existing identity-01 read and cleanup grants apply to the intended
path-qualified role, for example:

```text
arn:aws:iam::631367363628:role/actionbridge/staging/actionbridge-dental-staging/actionbridge-dental-staging-health-role
```

The missing-role request context reproduced in the tests uses the distinct alias:

```text
arn:aws:iam::631367363628:role/actionbridge-dental-staging-health-role
```

`iam:GetRole` is spelled correctly in identity-01, but that grant's resource does
not match this alias. The saved identity-03 v2 has no IAM Allow statements, so
there is no grant to fill the gap. Its `NotAction: [iam:*, s3:*]` regional Deny
also does not grant either action.

The existing scoped-role `DetachRolePolicy` grants additionally require the paired
`iam:PermissionsBoundary` and approved `iam:PolicyARN`. A missing-role alias has
neither the matching role path nor the boundary context. With the separate alias
cleanup Allows omitted, the local combined policy returns `implicitDeny` for
the approved detachment too. The action names, account, intended path and paired
boundary ARNs are unchanged; the required alias statements are absent.

The precise ARN evaluated by AWS is not present in the error text. The alias
context is an inference consistent with the saved policies, absence checks and
both recorded errors; the local tests are not an AWS IAM simulation.

## Smallest safe correction

**Update only `actionbridge-dental-staging-cfn-identity-03`. Do not change
guardrails-01 or the other three attached parts.**

The local one-policy proposal is in `.staging/identity-03-correction-review/`:

- `identity-03.json`: the complete previously reviewed eight-statement policy.
- `identity-03.diff`: normalized JSON diff against the saved current v2 export.
- `changes.json`: exact five statement additions at `/Statement/3` through `/Statement/7`.
- `review.json`: source/replacement hashes, scope, and evaluations of the saved documents.

The five additions are:

1. Allow `iam:GetRole` on the five exact reserved root aliases.
2. Allow `iam:DetachRolePolicy` on the four nonworker aliases only for
   `AWSLambdaBasicExecutionRole`, with absent permissions-boundary context.
3. Allow the same worker cleanup for Basic execution and SQS execution policies.
4. Explicitly deny every other operation on these aliases.
5. Explicitly deny alias detachment whenever a boundary is present.

Keep both protective Deny additions. Adding only the three Allows would omit
the planned protection against future supplemental broad Allows. Existing path
creation and policy operations still require their paired boundaries. Boundary
removal/version changes, unrelated roles and production API access remain denied.

The prior bounded cleanup tradeoff is unchanged: absent boundary context cannot
distinguish a missing role from an existing unbounded root role using one of the
exact reserved names. Only allowlisted managed policies can be detached. Recheck
all five names before any separately approved retry; do not adopt or delete a
conflicting role.

## Local verification results

**171 infrastructure/security tests passed**, including nine new v2-mismatch
regressions. The saved exports were also evaluated directly in 11 lookup/cleanup
cases: five root-alias GetRole requests and six allowlisted detach requests
(including both worker policies). Each changes from `implicitDeny` to `allowed`
with only identity-03 replaced. Existing scoped-role operations stay allowed, and
wrong policies, bounded aliases, unrelated roles and boundary-policy mutations
stay denied.

```bash
PYTHONDONTWRITEBYTECODE=1 AWS_EC2_METADATA_DISABLED=true AWS_DEFAULT_REGION=us-east-2 \
  /private/tmp/actionbridge-policy-verify-4udkoo6u/bin/python -m unittest discover -s infra/tests
```

Template, boundary and bootstrap consistency checks, cfn-lint on all three
templates, and whitespace checks also passed. The correction leaves application
code, CloudFormation templates, uploaded artifacts and the four other policy
documents unchanged. The evaluator covers the policy operators under test; it
does not replace verification of the actual applied IAM document and request
context before a future deployment.

## Owner review action

Review and approve the **identity-03-only** correction. On any later separately
authorized application, create a new default version of that existing managed
policy using the complete eight-statement JSON and retain prior versions. Verify
the resulting document contents, not just the new version label. No additional
policy attachment, guardrails-01 update or deployment is needed for this review.
