# HTTP stage-tagging policies — combined review passed, unapplied

Recovery A is complete. Do not repeat recovery, IAM setup, uploads or application setup.
Target: **631367363628 / us-east-2 / actionbridge-dental-staging**, API **l52iwors8c**.

**The previous identity-only replacement remains withdrawn.** Its PASS was a bounded
string-matching result, not proof that IAM recognizes or enforces its literal
`apigateway:TagResource` and `apigateway:UntagResource` actions. Both are absent
from the current official IAM Actions catalog. The Ohio CloudFormation provider
schema lists them, creating a source conflict; provider metadata alone does not
establish authorization. AWS-side ValidatePolicy remains denied to the developer.
The owner has now reported zero Console validation findings for both recognized
HTTP counterproposals and discarded those drafts without saving.

The documented tagging API uses HTTP verbs on an exact encoded Tags ARN:

`arn:aws:apigateway:us-east-2::/tags/arn%3Aaws%3Aapigateway%3Aus-east-2%3A%3A%2Fapis%2Fl52iwors8c%2Fstages%2Fstaging`

The replacements remove the conflicting Denies only for that exact tag ARN:
identity-03's tenth statement gains this NotResource exception and a new Ohio-only
HTTP Allow; guardrails-02 gains the matching HTTP exception. The first nine
identity statements remain unchanged. Two identical-scope Lambda Denies are
merged without changing permissions so guardrails-02 fits its quota. API-root
DELETE, other APIs/Regions, boundaries and CORS cleanup remain protected.

Final files for owner approval are in
`.staging/core-forward-deployment-review/policies-http-stage-tagging/`.
Only identity-03 and guardrails-02 change; their bytes exactly match the owner's
Console-validated drafts. Identity-03 has 11 statements / 4,474 compact characters;
guardrails-02 has 14 / 5,788. Three other policy files remain byte-identical.
Actual tagged CreateStage runtime authorization remains unproven; this review is
not a deployment-readiness or execution approval.

Verification includes 10 new HTTP policy tests, 870 combined API scope/precedence
contexts, 197 unchanged core contexts and independent 924 API / 540 Lambda parity
checks. The helper rejects action-catalog, original-policy, validated-byte and
owner-validation-evidence drift. Fresh live reads confirm exactly the five
reviewed execution-role policy attachments, no inline policy or execution-role
boundary. AWS SimulateCustomPolicy was denied; no server simulation is claimed.
All checks use the complete five-policy bundle, not isolated new Allows.

Minimum next owner actions, requiring separate approval before live application:

1. Explicitly accept the narrow tenth-statement amendment and both final files.
   In the existing authorized MFA Console, create a new identity-03 default version
   first and verify its JSON and retained versions; then do the same for
   guardrails-02. Preserve every prior version; stop if capacity is unavailable.
2. Save both default JSON exports for exact comparison. Only after verification
   should a new same-stack UPDATE change set be separately approved. Require
   43 additions, one HttpApi modification, zero removals and Replacement:false;
   execution and traffic remain separately gated.

Primary references: [IAM action/operation mappings](https://docs.aws.amazon.com/service-authorization/latest/reference/list_apigatewayv2.html),
[tag endpoint](https://docs.aws.amazon.com/apigatewayv2/latest/api-reference/tags-resource-arn.html),
[AWS programmatic catalog](https://servicereference.us-east-1.amazonaws.com/v1/apigateway/apigateway.json).
Local preparation made no live IAM change, new change set, upload, deployment or application request.
