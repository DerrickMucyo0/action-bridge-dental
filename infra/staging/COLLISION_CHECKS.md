# Collision reads for the existing developer user

Target **631367363628 / us-east-2**, existing IAM user **actionbridge-developer**.
This preparation did not log in, contact account APIs, grant permissions, create
resources, deploy, change Vercel or change Git history. Public AWS documentation
was consulted. All local validation uses mocks, never real AWS responses.

## First human action: administrator review and grant

Have the account owner use an **already authorized non-root administrator** in
account `631367363628` to review
[collision-read-policy.json](collision-read-policy.json). It is a proposed
additional read grant, not an execution/deployment policy or permissions boundary.

After approving its scope, the administrator can grant it in the AWS console:

1. Verify the console account is `631367363628` and the session is not root.
2. Open **IAM → Policies → Create policy → JSON**. Paste the exact local
   `collision-read-policy.json`, review the console's policy-validation findings
   and choose Next. Resolve errors without broadening the scope automatically.
3. Name the customer-managed policy
   **ActionBridgeDentalStagingCollisionReadOnly**, review and create it. If that
   policy name already exists, inspect it and stop for a separate review; do not
   silently replace an existing policy/version.
4. Open **IAM → Users → actionbridge-developer → Permissions → Add permissions
   → Attach policies directly**. Select only this approved customer-managed
   policy, review, then add permissions. Do not create/reset users, create access
   keys, change a boundary or attach administrator/service-full-access policies.

Use a **customer-managed policy**, not an inline user policy: the draft fits the
6,144-character managed-policy limit and exceeds the 2,048-character aggregate
inline-user limit. These console actions are future owner actions, not actions
performed by this preparation. [AWS policy creation](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_create-console.html),
[IAM quotas](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_iam-quotas.html).

Existing effective permissions, boundaries, SCPs, resource policies and session
restrictions remain authoritative. This additive grant does not make all the
user's existing permissions read-only and cannot override a deny. Any remaining
AccessDenied is UNKNOWN; never attach broader policies just to clear the report.

## Review of all 32 planned checks

The original [collision-checks.py](collision-checks.py) still **prints only**.
The separately gated [run-collision-checks.py](run-collision-checks.py) executes
the same fixed operations, with private identity verification and safer list
response projections. It never accepts commands from a report or arbitrary file.

| Planned read | Checks | IAM grant and scope |
| --- | ---: | --- |
| STS caller identity | 1 | No IAM permission required; privately verifies account and exact existing developer ARN, never prints UserId |
| Region coverage metadata | 1 | ec2:DescribeRegions, Resource '*', called through Ohio; lists Region availability, not resources in other Regions |
| Proposed stack | 1 | cloudformation:DescribeStacks on the one named Ohio stack ARN |
| Function configurations | 5 | lambda:GetFunctionConfiguration on exactly the five named staging functions |
| Log-group names | 5 | logs:DescribeLogGroups, Resource '*', Ohio endpoint only |
| Table | 1 | dynamodb:DescribeTable on the exact staging table |
| Queue URLs | 2 | sqs:GetQueueUrl on the exact two Ohio queues |
| Bucket HEADs | 2 | s3:ListBucket on the two exact bucket names, with the request's expected owner fixed to the target account |
| Reserved IAM role path | 1 | iam:ListRoles, Resource '*'; path filtering is a request/output constraint, not an IAM scope |
| Exact runtime/execution role names | 6 | iam:GetRole for those six names at the root or any IAM path in this account |
| Proposed boundary policy ARNs | 5 | iam:GetPolicy on the five exact root-path policy ARNs |
| HTTP/WebSocket and REST API collections | 2 | apigateway:GET on Ohio `/apis` and `/restapis` collection ARNs only |
| **Total** | **32** | **11 distinct IAM actions; STS needs no grant and both API versions share GET** |

Every Allow is bound to
`arn:aws:iam::631367363628:user/actionbridge-developer`. Regional requests have
`aws:RequestedRegion=us-east-2`. IAM is global; S3 HEAD may redirect to a bucket's
actual Region, so those narrowly scoped statements intentionally omit the Region
condition. No resource reads in other Regions are added to complete the wider
account inventory. This is not a complete inventory grant.

Unavoidable scope limits for administrator review:

- IAM ListRoles can expose account-wide role metadata/trust; IAM has no supported
  permission condition corresponding to this command's path-prefix filter.
- DescribeLogGroups and API collection reads permit broader Ohio metadata than
  the returned exact-name projections. API collections cannot be scoped to a
  future generated API ID for a name search.
- GetFunctionConfiguration permits all configuration fields for those five
  functions, including environment values internally. IAM cannot filter response
  fields. The runner projects only safe metadata and never prints environments.
- HeadBucket requires ListBucket, which also permits listing object keys in the
  two named buckets if otherwise authorized. The policy grants no GetObject or
  object writes. Its expected-owner argument is not a proof of bucket absence.
- No Cognito user lookup, model call, IAM mutation, PassRole, upload, deployment
  or resource creation is granted by this JSON.

## Running later, after approval and existing authentication

Use a trusted AWS CLI v2 installation and the **existing authenticated**
`actionbridge-developer` profile. The runner does not perform login, configure,
assume-role, MFA-code entry or credential creation. If credentials are missing or
expired, stop and use your separately approved authentication process privately.
Do not paste credentials, codes, tokens or private subjects into chat.

First review the offline behavior:

```bash
python3 infra/staging/run-collision-checks.py --profile actionbridge-developer
```

For an already approved/authenticated developer profile, verify the corrected
subprocess error path with **only identity verification and the health-function
read**, before running all 32 checks:

```bash
python3 infra/staging/run-collision-checks.py --profile actionbridge-developer \
  --check health --execute --approve-read-only-checks --diagnostic
```

This fixed selector cannot name arbitrary resources. It retains all approval,
identity, account, history and timeout guards. Diagnostic mode emits JSON lines
containing only `aws_error_code` (allowlisted code or null) and `classification`.
The first line represents authentication; the second represents the health
function. For a missing function, the second code is ResourceNotFoundException
with AVAILABLE. A denial or unrecognized response stays UNKNOWN. No raw stderr,
Message, Type, environment values, credentials or private IDs are displayed.

Only after the owner approves these reads and authentication is ready, the human
operator may explicitly opt in:

```bash
python3 infra/staging/run-collision-checks.py \
  --profile actionbridge-developer --execute --approve-read-only-checks
```

Both flags are required. The runner first verifies the authenticated account and
exact IAM user; root, assumed roles, another account/user or failed authentication
block all remaining checks. CLI credential providers can refresh existing trusted
credentials; the runner invokes no login command and supplies no interactive
input. It disables metadata fallback, paging, auto-prompt and configured endpoint
overrides, uses argument arrays without a shell and enforces finite timeouts.
Before starting an AWS subprocess it checks the local CLI configuration and
shared-profile settings for enabled/uncertain history and refuses unsafe or
unreadable settings. This includes the shared credentials file, whose profile
settings AWS CLI merges into its configuration during authentication.
This local check displays no configuration contents. Keep `cli_history` disabled:
CLI history can otherwise store full API responses before query projection.

The runner displays only fixed labels, statuses and sanitized diagnostics. It
does not print raw AWS output, identity IDs, tokens, environment values or arbitrary
stderr. Every failure remains visible as a status with its exit/error category;
raw diagnostic text is deliberately withheld because it may contain private data.
Unexpected successful stderr is also treated as UNKNOWN. Do not enable AWS debug
logging or redirect unsanitized CLI responses into tracked files.
The runner leaves existing configuration unchanged. See
[AWS CLI data protection](https://docs.aws.amazon.com/cli/latest/userguide/data-protection.html)
for the optional history feature and its response retention.

## Interpreting the summary

- **AVAILABLE:** a valid completed read found no matching resource, or the caller/
  Region metadata check completed. Metadata rows do not declare a resource name
  free. Findings apply only at that time and scope, not to the entire account.
- **COLLISION:** a matching resource exists. Artifact buckets and previously
  approved prerequisites still require manual ownership/configuration review;
  the runner never automatically adopts them.
- **UNKNOWN:** permission/authentication/transport/throttling/timeout errors,
  malformed or incomplete responses, remaining pagination, and ambiguous absence.
  Nothing failed is converted into AVAILABLE or silently skipped.

S3 400/403/404 is always UNKNOWN, because bucket absence and denied access cannot
be distinguished. SQS missing-queue errors are UNKNOWN because they can also mean
insufficient access. GetPolicy NoSuchEntity proves only that root-path ARN is
absent; the policy name may exist under another IAM path, so those rows stay
UNKNOWN too. Successful complete API/log/role list reads can prove absence only
in their stated filter scope. [S3 HEAD behavior](https://docs.aws.amazon.com/AmazonS3/latest/API/API_HeadBucket.html),
[SQS errors](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/troubleshooting-api-errors.html).

Consequently a correctly granted, fully authenticated run can still contain
UNKNOWN rows. The administrator must resolve these with independent evidence;
no additional global listing permissions or resource creation are automatically
used to resolve them. Local tests do not establish live effective permissions.

The earlier prefix-only fix was incomplete: the exact reported first line already
matched it, but the CLI v2 default **enhanced** formatter appends a multiline
`Additional error details:` section with modeled fields such as Lambda's Type.
The old classifier applied a single-line whole-string match to **all captured
stderr**, rejecting this documented response as unrecognized. Arguments,
`shell=False`, separate stream capture and exit-code collection were correct.
`--output json` affects successful stdout, not error formatting. This failure
path is reproduced with real local subprocesses and a temporary fake AWS
executable; no real account response was fetched to diagnose it.

The child environment now requests `AWS_CLI_ERROR_FORMAT=json`. The runner parses
the complete JSON error document strictly, rejects duplicate/trailing/unsupported
documents and never prints its Message or Type. Older CLIs can ignore that
environment setting: compatibility parsing accepts legacy text and only the
bounded documented Lambda enhanced details section. Additional warning/error
lines are not silently discarded. A recognized safe code can be reported even
when an invalid envelope forces UNKNOWN.

An AVAILABLE absence still requires the requested service's documented code:
Lambda/DynamoDB ResourceNotFoundException, IAM GetRole NoSuchEntity, or
CloudFormation ValidationError plus the exact target stack's missing message.
CLI exit 254 alone, AccessDenied, network failures, unrecognized responses and
the ambiguous cases above remain UNKNOWN. JSON documents get their operation
context from the fixed trusted subprocess arguments, not an arbitrary error field.
No IAM grant is needed for this parser/transport fix. Live result counts remain
unverified; use the single-health command above first.

See [AWS structured error formats](https://docs.aws.amazon.com/cli/latest/userguide/cli-usage-error-format.html),
[AWS CLI return codes](https://docs.aws.amazon.com/cli/latest/userguide/cli-usage-returncodes.html),
[Lambda errors](https://docs.aws.amazon.com/lambda/latest/api/API_GetFunctionConfiguration.html),
[DynamoDB errors](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_DescribeTable.html)
and [IAM GetRole errors](https://docs.aws.amazon.com/IAM/latest/APIReference/API_GetRole.html).

Exit codes: **0** when all reads are AVAILABLE; **1** for collisions without
unknowns; **2** if any result is UNKNOWN or an execution/authentication gate fails.
No result authorizes IAM provisioning, bootstrap execution or backend deployment.
Keep the incomplete 153-resource inventory and the wider staging approval gates.

## Local validation

Tests mock every AWS subprocess and cover the opt-in gates, identity mismatch,
denials, ambiguous absence, pagination, timeouts, malformed output and diagnostic
redaction. Policy tests map every planned read to exact actions/resources, verify
principal/Region constraints, reject unrelated reads/writes and enforce the
managed-policy size limit. Local cfn-lint also checks the policy's IAM document
shape inside an unapplied temporary CloudFormation wrapper. This is not a live
IAM Access Analyzer or effective-permissions evaluation.

The earlier read-policy/runner validation passed **99 infrastructure tests**, including nine policy
scope tests and 26 mocked-runner tests; the prior 64 infrastructure tests still
pass. The policy is 4,896 compact characters. Pinned cfn-lint passed its temporary
IAM-document wrapper without warnings; the offline runner mode, local links and
`git diff --check` passed. No real AWS CLI call or actual local authentication
configuration/credentials file was read during validation. Existing staging
templates, boundary drafts, application code and unrelated work are unchanged.

The earlier CLI v2 prefix-only compatibility fix passed **107 infrastructure
tests**, including 34 runner tests (eight new regressions). Offline default mode
and `git diff --check` also passed. Validation used mocked AWS responses only;
no AWS calls, permission changes or private authentication/parameter reads were
performed. The existing approval, account, identity and CLI-history gates remain.

The subsequent complete-stderr fix passed **123 offline infrastructure tests**,
including eight real local subprocess tests and eight structured-error tests.
The subprocess tests use only a temporary fake AWS executable and synthetic
authentication files. One captures the actual multiline stderr/exit 254 and proves
the old whole-string match fails while the corrected classifier succeeds.
All three shared/bootstrap/backend templates passed SAM validation and pinned
cfn-lint without warnings; generator consistency, local links, offline mode and
`git diff --check` passed too. No AWS account calls, policy changes or private-file
reads were used. Only the runner, this handoff and two new test files changed.

```bash
AWS_EC2_METADATA_DISABLED=true AWS_DEFAULT_REGION=us-east-2 \
  /private/tmp/actionbridge-staging-infra-checks/bin/python -m unittest discover -s infra/tests -v
git diff --check
```
