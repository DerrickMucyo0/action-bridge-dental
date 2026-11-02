# One owner setup for staging deployment access

**Activation complete:** the access stack is CREATE_COMPLETE; its fourteen logical
resources and live IAM documents were checked. CLI profile
`actionbridge-staging-deployer` is bound to the developer-assumed MFA role session
and defaults to us-east-2. Exact STS identity and role ID passed. Existing IAM
policy replacements, application deployment, publication and traffic remain
unapproved. Fresh results: `.staging/delegated-access-final-review/activation-verification-20261027.json`.

Use GetBranch for the exact `staging` target. Actual AWS ListBranches authorization
uses `apps/<id>/branches/*`, which the reviewed resource Deny excludes despite the
authorization-reference table listing app scope. No IAM broadening was performed;
GetBranch confirmed the staging branch absent. Other branch inventory is unverified.
Access-stack termination protection is currently off; the deployer's explicit
DeleteStack Deny and retained owner ceilings remain in place. This setting was
reported without alteration.

**Current approval: owner creation of the reviewed access stack only**, followed
by read-only role verification. Seven new policy names must first be confirmed
unused. Existing IAM policy replacements, deployments, publication and traffic
remain unapproved. Target is account 631367363628, Ohio (`us-east-2`).

Review the single upload file:
`.staging/delegated-access-final-review/access-stack.json`.
Its exact resource inventory and source hashes are in the adjacent `review.json`.

The proposed setup creates 14 resources: six IAM roles (one deployer and the five
reserved Lambda roles), seven managed policies (four deployer policies and three
owner-controlled execution ceilings), and one **empty** static Amplify app.
There are no Lambda functions, tables, queues, hosting branches, builds, files,
Git connections, access keys, or application deployments in this setup.
Existing runtime boundary policies are referenced unchanged, not recreated.

**Requested authorization**

- Create only `actionbridge-dental-staging-access` from that exact template.
- Attach the three independent Deny ceilings to the existing CloudFormation role.
  Fresh AWS reads confirm five attachments and no inline policies; eight after
  setup remains within the documented role-policy quota. Reserved Lambda and
  deployer role names are absent. New policy-name collisions need an owner check.
- Give `actionbridge-dental-staging-deployer` MFA-protected access to the exact
  staging stack, its existing execution role, diagnostics, conditional artifact
  uploads, and only the new Amplify app's `staging` branch.
- Permit version updates only to existing `identity-02`, `identity-03` and
  `guardrails-02`; the other policies, runtime trust/identity/boundaries, deployer
  permissions and access stack remain owner-controlled.
- The previously reviewed tagging files remain prepared under
  `.staging/core-forward-deployment-review/policies-http-stage-tagging/`.
  **Their application is not included in the current creation-only approval.**
- This does **not** authorize backend execution, traffic, website publication,
  AI calls, version deletion, manual resource cleanup, skipping or forcing rollback.
  Runtime costs and publication will receive a separate consolidated proposal.

**One setup procedure, after explicit approval and fresh preflight**

1. In your existing MFA-protected account-owner AWS Console, select account
   **631367363628 / Ohio**. First search customer-managed policy names
   and confirm no `actionbridge-dental-staging-owner-ceiling-1/2/3` or
   `actionbridge-dental-staging-deployer-1/2/3/4` exists. Then:
   CloudFormation → Create stack → With new resources →
   Upload a template file → choose the file above. Stack name:
   **`actionbridge-dental-staging-access`**. Leave the optional execution role empty:
   the restricted application execution role cannot provision its own access setup.
   Enable termination protection, retain normal rollback, acknowledge named IAM
   resources. Next must validate the template successfully; the developer cannot
   call AWS ValidateTemplate. Review the **14-resource** list, then create this
   access stack only, after final authorization covers this procedure and the
   Console's template-only S3 upload/storage.
   Stop on unexpected errors or preexisting reserved names; do not delete/retry.
2. When it reaches `CREATE_COMPLETE`, use a separate Console session signed in as
   **`actionbridge-developer` with its own MFA**, then open the stack output
   `SwitchRoleURL`. A root Console session cannot switch roles. In your terminal:

   ```sh
   aws login --profile actionbridge-staging-deployer --region us-east-2
   ```

   Select the **deployer role session**, never root or the plain developer user.
   Passwords and MFA codes stay in your browser. Reply “delegated role signed in.”
   This role has a **one-hour maximum session**, possibly shorter if the original
   Console session expires sooner. Later MFA sign-in renewal is still necessary.
   Do not manually configure source_profile, role_arn or access keys: aws login
   writes its own login_session profile setting for the selected role session.
   I test it with `aws sts get-caller-identity --profile actionbridge-staging-deployer
   --region us-east-2`: account must equal 631367363628, and ARN must start with
   `arn:aws:sts::631367363628:assumed-role/actionbridge-dental-staging-deployer/`.
   The read-only verifier rejects root, the plain developer user, and other roles.
   Keep all authenticated CLI calls serial, including independent reads: parallel
   aws-login refreshes caused a real shared-cache failure during this review.
   The verifier now uses a local process lock as well as serial calls. Future
   deployment/IAM commands must follow the same rule; no concurrent CLI clients.
3. I run the prepared read-only verifier and AWS policy validation/simulation.
   Stop before any existing-policy replacement; it requires separate approval.
   The verifier must freshly confirm original policy documents, expected defaults
   **v4 / v2**, retained versions and at least one free version slot before either
   update. October 26 screenshots are historical evidence. If anything differs,
   stop without changing policies or deleting versions. Then I return one scoped
   deployment/cost and publication proposal, rather than asking about each API call.

Fresh capacity checks are **essential before the existing policy replacements**,
but not before this bootstrap: the access stack does not create a version of, or
change the documents of, either existing policy. It creates new policies and adds
Deny-only ceilings. The new role supplies the missing read permissions, avoiding
another temporary IAM grant or a manual JSON-export procedure. Runtime role trust
is Lambda-only; no functions are created. All live boundary/identity documents must
match before any function deployment or policy replacement.

**Architecture change and safeguards**

Application candidates use the owner-managed runtime roles. The revised core
review must therefore show **40 additions, one HttpApi modification with
Replacement False, and zero removals**. The previous 43-addition request is not
reused. API `l52iwors8c`, Cognito users, uploaded Lambda ZIPs, and Git history are
unchanged. Original application templates remain intact beside the new candidates.

The executor cannot mutate any IAM role or its own ceilings, even if an editable
policy gains an Allow. The deployer has an explicit action allowlist ceiling and
resource Denies, including against grants directly to role sessions. Application
change sets require a non-IAM resource-type filter. Explicit imports are denied;
the newer automatic-import flag has no documented equivalent IAM condition. The
local request validator therefore requires ImportExistingResources=false, exact
reviewed template equality, no Capabilities and no imports/previous-template use.
Review rejects adoption/import actions. API-root deletion remains denied.
API endpoint settings, authentication configuration and Lambda permission
SourceArn/SourceAccount are template-review safeguards, not IAM-enforced body
conditions. All must pass before any separately authorized execution/traffic.
Mapping writes are confined to the worker; reads after deletion need no function
context. Initial mapping tagging uses a staging ownership marker and only normal
non-import CloudFormation creation. Its provider behavior still needs verification
before the separate AI phase; core contains no mapping or background processing.

IAM has no additional service charge. An empty Amplify app has no deployed bytes
or build minutes; future hosting/storage/transfer are billable usage. Console
template upload can create/use a template S3 bucket and incur normal S3 costs.
Retained IAM roles/ceilings and the empty app can survive access-stack creation
failure or deletion. A failed bootstrap does not promise exact restoration of
prior IAM; stop for read-only inventory without deleting or repeating creation.
Owner cleanup, if desired, is separate. No policy versions are silently pruned.

**Current verification limits**

Tool access and developer login are restored. Fresh AWS reads confirm account,
stack UPDATE_ROLLBACK_COMPLETE, preserved API physical ID, five existing execution
policy attachments, no inline policy, absent reserved role names, and all five
boundary ARNs/default v1. Developer access still denies managed-policy documents,
the two version lists, new policy-name metadata and AWS ValidateTemplate. The
name-collision and Console validation checks in step 1 are mandatory. Fresh
existing-policy version/capacity checks move to step 3; none is claimed complete.
After setup, `verify-delegated-access.py` reads back every live policy/ceiling and
boundary before any IAM replacement/deployment; it refuses root, writes and retries.
Browser tests also need a permitted localhost server; this sandbox denied its port.

Sources: [AWS CLI role login](https://docs.aws.amazon.com/cli/latest/reference/login/),
[Console role switching](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_switch-role-console.html),
[sign-in actions](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/SignInLocalDevelopmentAccess.html),
[CloudFormation authorization](https://docs.aws.amazon.com/service-authorization/latest/reference/list_cloudformation.html),
[Amplify authorization](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amplify.html),
[Amplify pricing](https://aws.amazon.com/amplify/pricing/).
