# API rollback recovery — completed historical record

Recovery A completed at **2026-10-26 19:29:56 UTC**, with all 42 additions and the partial stage cleaned up. Do not repeat the recovery actions below. Current work is the [core forward stage-tagging repair](CORE_FORWARD_REPAIR.md). Target: **631367363628 / us-east-2 / actionbridge-dental-staging**, preserved API **l52iwors8c**.

## Exact recovery-only policy corrections (A)

Only two existing managed policies change:

| Policy | Exact correction |
|---|---|
| `actionbridge-dental-staging-cfn-identity-03` | Append Ohio-only Allow for `apigateway:DELETE` on `arn:aws:apigateway:us-east-2::/apis/l52iwors8c/cors`; append a DELETE `NotResource` Deny allowing only the already-approved API children plus `/cors`, excluding the API itself. |
| `actionbridge-dental-staging-cfn-guardrails-02` | Remove `apigateway:DELETE` from `/Statement/7/Action`; that deletion guard now resides in identity-03. GET/PATCH/POST/PUT and their restrictions remain unchanged. |

Prepared replacements and exact diffs: `.staging/api-recovery-review/policies-A/`. The effective change is **only exact CORS DELETE gained, API-self DELETE explicitly denied**. Unrelated APIs, other Regions, production, IAM/boundary restrictions and mapping permissions remain protected. The other three policy documents are byte-identical. Sizes: **4,041 / 6,054** compact characters, below 6,144. Saved current exports match the pinned originals; direct live policy-content reads remain unavailable to the developer.

## Stage tagging is a separate forward-deployment issue

The generic IAM reference maps the HTTP API `TagResource` operation to HTTP verbs.
The full Ohio CloudFormation provider schema lists literal
`apigateway:TagResource`, matching the denial text, but the official IAM action
catalog omits that name. The identity-only proposal was withdrawn; see the
blocked authorization review in [CORE_FORWARD_REPAIR.md](CORE_FORWARD_REPAIR.md).
The older encoded-tag HTTP-verb draft in `.staging/api-forward-tagging-review/`
remains superseded and must not be applied.

Primary references: [V2 IAM mapping](https://docs.aws.amazon.com/service-authorization/latest/reference/list_apigatewayv2.html), [Tags ARN](https://docs.aws.amazon.com/apigateway/latest/developerguide/arn-format-reference.html), [CORS deletion](https://docs.aws.amazon.com/apigatewayv2/latest/api-reference/apis-apiid-cors.html).

## Resources and charges

All **42 created resources** were reconciled: table, JWT authorizer, three functions, three roles, three log groups, 14 permissions, three integrations and 14 routes. The failed stage may require cleanup too. CloudFormation chooses reverse-dependency ordering: stage/permissions/logs, routes, integrations/authorizer, functions, roles, then table. This is not a manual deletion list.

Normal rollback can delete the staging table **and any rows**, and created logs. Preserve the existing API, artifact bucket/ZIPs, external boundary policies and Cognito users. Function Active status does not imply continuously running compute; DynamoDB/log/artifact storage and any request usage can still incur charges. No account-bill estimate is claimed. Detailed inventory, dependencies, evidence timestamps and pricing references are in `.staging/api-recovery-review/created-resources-and-cleanup.json`.

## Verification and exact owner actions

**232 infrastructure/security tests pass**, plus 576 API contexts, 197 core contexts, 42 role-cleanup contexts and 74 known cleanup requests covering all 42 created resources. Explicit Deny precedence, API-self protection and wrong-Region/unrelated-resource denial pass. Core/bootstrap CloudFormation lint passes. These are bounded local evaluations; missing `lambda:Principal` during RemovePermission remains denied and unobserved, not silently granted.

1. **Next owner action: review and approve A only.** No live policy changes have been made. After approval, apply identity-03 first (activating the restrictive DELETE guard), then guardrails-02; retain prior versions. Verify both resulting documents/default versions and unchanged execution-role attachments before recovery.
2. Obtain **separate approval** for owner MFA Console **Continue update rollback** on this exact stack. It authorizes CloudFormation's normal cleanup of this failed attempt, not a new deployment. The prepared API request is `.staging/api-recovery-review/continue-update-rollback-request.json`: existing role retained, no `ResourcesToSkip`, force options or role replacement. Developer execution restrictions remain binding.
3. Monitor read-only through `UPDATE_ROLLBACK_COMPLETE`, including cleanup. Inspect warnings/failed or skipped events and reconcile every created resource; terminal status alone is insufficient. Confirm API l52iwors8c preserved/disabled and CORS restored to the original baseline. Stop on any new failure; no automatic retry, skipping or manual deletion.

[AWS recovery behavior](https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_ContinueUpdateRollback.html). No new change set, deployment, application traffic, application setup or CloudTrail collection is needed for this recovery review.
