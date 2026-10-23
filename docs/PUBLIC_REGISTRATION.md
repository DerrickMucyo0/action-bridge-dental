# Public registration and deployment preparation

This feature adds email/password self-registration and code confirmation to the existing web Cognito flow. It uses the same user pool, public client and API architecture as sign-in. No AWS resources, Vercel settings or production deployments were changed by implementing this branch. Local tests intercept Cognito transport; they do not prove live email delivery or a deployed integration. Keep staging and demo data synthetic.

## Existing architecture and security boundaries

- The browser calls the regional Cognito user-pools HTTPS endpoint directly for `SignUp`, `ConfirmSignUp`, `ResendConfirmationCode`, `InitiateAuth`, password recovery and token lifecycle operations. There is no application signup database or privileged signup Lambda. Passwords and verification codes are transient form/request values; they must not be written to storage or logs. Confirm password stays in the form and is not sent to Cognito.
- `infra/template.yaml` creates an email-username pool, a shared public mobile/web client (`GenerateSecret: false`) and a JWT authorizer. Deployed functions use `AUTH_MODE=jwt`; `/health` is the only unauthenticated application route. Registration returns no application session; confirmation must complete before ordinary sign-in. [AWS confirmation behavior](https://docs.aws.amazon.com/cognito/latest/developerguide/signing-up-users-in-your-app.html).
- API Gateway validates the configured Cognito issuer and client audience before Lambda receives claims. `backend/src/shared/auth.ts` derives ownership from the validated `sub` as `user:<sub>` and ignores the demo header in JWT mode. Browser-supplied owner IDs are not authority. The existing access token stays in memory and the refresh token in tab-scoped `sessionStorage`; browser script access remains an existing XSS-sensitive boundary.
- Cases, ledger entries, saved strategies and saved Plan A/Plan B comparisons use owner-scoped DynamoDB partitions. Agent jobs use an owner-scoped key, and upload slots require case ownership and derive S3 keys from that owner. Existing backend tests cover missing authorizer claims and cross-user reads/writes/comparison operations. These local tests exercise application authorization; they do not cryptographically validate live API Gateway tokens.
- Public registration assigns no Cognito group, IAM role, admin attribute or extra application privilege. Existing least-privilege Lambda policies, revision checks, deterministic estimates, comparison functionality, contributors and licenses are unchanged. Keep privileged group assignment and Cognito administrative operations outside the browser.

## Required Cognito configuration

The local template adds `EnableSelfRegistration`, string values `false`/`true`, default **`false`**. With the default, `AllowAdminCreateUserOnly` stays `true`. Only an explicitly reviewed stage deployment with `EnableSelfRegistration=true` permits public signup and selects `VerificationMessageTemplate.DefaultEmailOption=CONFIRM_WITH_CODE`. Merely shipping the frontend does not enable the pool.

A separately authorized operator must inspect the actual target pool/client and its drift before preparing a change set. The repository's template is evidence of intended configuration, not a read of the deployed account. Required settings:

| Setting | Required value / review |
| --- | --- |
| Pool and Region | Existing intended pool and its actual Region; the documented deployment is `us-east-2`. Use a separate staging pool for synthetic release tests. |
| Self-service signup | `AdminCreateUserConfig.AllowAdminCreateUserOnly=false` only in the approved target stage. |
| Sign-in identifier | Preserve existing `UsernameAttributes: [email]`; do not replace the pool or change existing users to implement this feature. |
| Verification | `AutoVerifiedAttributes: [email]`; email verification **code**, not link. No auto-confirm/auto-verify pre-signup trigger or privileged confirmation bypass. Review existing triggers for drift. |
| Required attributes | Email is sufficient; inspect live required attributes because the form sends only email as a user attribute. Additional required attributes need an explicit product change. |
| Password policy | At least 12 characters, upper and lowercase letters, and a number; symbols optional in this template. Confirm the deployed policy matches the form; stricter pool rules are authoritative. |
| Recovery | `AccountRecoverySetting` uses `verified_email` priority 1. Existing admin-created accounts need a genuinely verified delivery address for self-service reset. |
| App client | Reuse the current **public, no-secret** client used by web/mobile. Retain `ALLOW_USER_PASSWORD_AUTH`, `ALLOW_REFRESH_TOKEN_AUTH`, token revocation and `PreventUserExistenceErrors=ENABLED`; retain SRP and OAuth/PKCE settings for existing consumers. |
| API authorizer | Issuer must identify the same user pool. Audience must include the client used by the browser. The checked-in audience contains only `UserPoolClient`; choosing a separate public client requires an explicitly reviewed audience update. |
| OAuth callbacks | Existing `AuthCallbackUrls` and logout URLs belong to managed-login/PKCE consumers. The direct JSON signup/confirmation form requires no web callback, hosted-UI domain change or client secret. |

Do not add AWS access keys, a client secret or `SECRET_HASH` to a `VITE_*` variable. A browser app with a secret-bearing client needs a separately approved public client; it cannot safely hide that secret. Review the AWS [admin-create-only setting](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-cognito-userpool-admincreateuserconfig.html) and [verification template](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-cognito-userpool-verificationmessagetemplate.html).

`PreventUserExistenceErrors` does **not** conceal duplicate signup for this email-as-username pool: Cognito can return `UsernameExistsException` to direct callers. UI wording alone cannot prevent enumeration. Preserve generic sign-in/recovery messages; do not promise full email-address privacy or silently migrate identity configuration. [AWS error-disclosure behavior](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pool-managing-errors.html).

## Delivery, rate limits and abuse controls

Cognito confirmation codes expire after 24 hours; password-reset codes after one hour. AWS currently documents at most five `ResendConfirmationCode` requests and fifteen `ConfirmSignUp` requests per user per hour; account/Region API quotas and risk-based delivery controls also apply. A browser resend countdown is a convenience, not a security limit: refreshes, other tabs and direct calls can bypass it. Handle service throttling without automatic repeated sends or revealing raw exceptions. [Cognito quotas](https://docs.aws.amazon.com/cognito/latest/developerguide/quotas.html).

The existing application API keeps burst 20 / sustained 10 requests per second stage throttling. It does not protect direct Cognito calls. Before public launch, review Cognito quotas, message volume, costs, logs/alerts and the target pool's server-enforced abuse controls. A Cognito-associated AWS WAF ACL can apply rate-based rules to the user-pools endpoints; a Vercel-only firewall does not cover those calls. Test rules on staging first. WAF CAPTCHA is interactive only with managed login; direct user-pools API calls can instead receive `ForbiddenException`. No WAF resources are provisioned by this branch. [Cognito/WAF behavior](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-waf.html).

The template leaves Cognito's existing email delivery configuration unchanged. Default Cognito email has a small daily delivery quota and is unsuitable for typical public volume. If using SES, verify the sender identity/domain, authorized Cognito sending permissions and supported SES Region, check quotas, bounce/suppression handling and delivery monitoring. SES sandbox permits only verified recipients or mailbox simulator addresses; arbitrary public recipients require SES production access. Confirm receipt and resend/reset delivery using controlled synthetic test accounts before rollout. [Cognito email and SES settings](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-email.html).

## Required Vercel configuration

Inspect the intended Vercel project's Git provider/repository, owner, Root Directory, Production Branch, environment scopes and deployment automation. Neither checked-in `vercel.json` proves an existing project is connected to this GitHub repository. Do not reconnect projects or change settings as part of implementation.

For a reviewed deployment use:

| Project setting | Value |
| --- | --- |
| Root Directory | Repository root (`.`), so shared `packages/` are available. |
| Framework | Other / no preset; root `vercel.json` supplies build settings. |
| Node.js | 22.x, at least repository-required 22.13. |
| Install / build | `npm ci` / `npm run build:web`. The build script also installs web dependencies and builds shared packages. |
| Output | `web/dist`; preserve SPA rewrite to `/index.html` and existing response headers. |
| Preview branch | `feat/public-self-registration`, with approved **staging** service values. |

`web/vercel.json` is a separate legacy root layout with output `dist`; do not mix it with repository-root settings. Root builds are the supported choice because the web package imports sibling shared packages. [Vercel build settings](https://vercel.com/docs/builds/configure-a-build).

Set these three public, build-time variables for the intended environment (branch-specific Preview values for testing):

| Variable | Value |
| --- | --- |
| `VITE_API_BASE_URL` | Staging `ApiBaseUrl`, HTTPS with stage, without `/v1`. |
| `VITE_COGNITO_CLIENT_ID` | Staging public `UserPoolClientId`, also accepted by that API's JWT audience. |
| `VITE_COGNITO_REGION` | Region of that pool, normally `us-east-2`. |

Rebuild after variable changes; do not copy production values into previews by default. Do not supply AWS credentials to this static site. [Vercel environment scopes](https://vercel.com/docs/environment-variables).

Add only the exact approved preview browser origin to **staging** `WebOrigins` for API/S3 CORS. Do not use `*` or relax authentication. CORS is not authorization. Preview URLs can vary; use a reviewed stable preview alias or update the exact allowed origin through the normal staging configuration review.

A connected Vercel project can deploy a push or merge to its configured Production Branch automatically, often `main`; the checked-in CI workflow runs checks, not a deployment. Verify the actual branch mapping before pushing. Keep this feature off the production branch and do not promote a preview until live staging tests and release approval are complete. [Vercel Git deployment behavior](https://vercel.com/docs/git).

## Recorded local verification — 2026-10-23

Verified on `feat/public-self-registration`, based on `7f22993336e6f10e164a3621664c77e94a6e70d7`, using Node 22.23.4. These results describe this implementation pass, not live cloud verification.

| Check | Actual result |
| --- | --- |
| `npm run check` | Passed: 43 Vitest files, **487 tests**, shared-package/backend TypeScript and shared builds. Includes mobile logic; not the separate mobile app typecheck. |
| `npm --prefix web run typecheck` | Passed. |
| `npm --prefix web run build` | Passed: TypeScript and Vite production bundle. Existing Zod annotation and bundle-size advisory warnings remain. |
| Full Playwright suite | Passed: **131 tests** in 3.5 minutes: 85 original workflows/comparison/save/print cases, 18 registration cases and 28 Cognito transport cases. |
| Infrastructure audit | YAML/intrinsic syntax, both opt-in branches and default-template semantic equivalence passed. JWT configuration, ownership mode, IAM, CORS, recovery/password policy and application throttles are preserved. No CloudFormation deployment or live validation was performed. |
| Formatting and diff | Changed authentication code/tests passed Prettier; `git diff --check` passed. Credits/license records and calculation/backend/mobile sources were unchanged. |

The local browser run extended `web/playwright.config.ts` with a temporary external configuration selecting the already-installed Google Chrome 2 executable and temporary artifact paths. The normal repository test configuration is unchanged; CI installs Playwright Chromium. API/Cognito transport was intercepted, backend storage was local/stubbed, and fixtures were fictional. The 42-test focused run is an overlapping subset of the final 131-test suite, not additional coverage. Empty registration forms were also visually inspected at 1440px and 360px. The existing Vercel connection and live AWS settings remain unverified.

CI now installs the locked mobile dependencies before `npm run check`, because the mobile logic tests resolve `expo/tsconfig.base`. No dependency versions or lockfiles were changed.

Changed files: `.github/workflows/ci.yml`, `README.md`, `infra/template.yaml`, `web/README.md`, `web/src/features/auth/sign-in-page.tsx`, `web/src/features/auth/public-account-form.tsx`, `web/src/services/cognito.ts`, `web/src/state/auth.tsx`, `web/tests/cognito-client.spec.ts`, `web/tests/public-registration.spec.ts`, and this document.

## Verification and production checklist

1. Review the diff and contributor/license records. Run `npm run check`, `npm --prefix web run typecheck`, `npm --prefix web run build` and `npm --prefix web test` with the installed test browser. Preserve all Plan A/Plan B, saving, export and original-journey regression coverage. Record actual results with the commit under review.
2. Obtain separate authorization for staging infrastructure/configuration and preview deployment. Review the change set to ensure the existing pool/client are updated in place and no data resources are replaced. Keep production unchanged and demo accounts/data separate.
3. On that staging pool, exercise a new controlled email, invalid email, policy failure, password mismatch, duplicate signup, incorrect/expired code, resend/cooldown/service throttling, confirmation, and sign-in before/after confirmation. Verify no tokens are issued before confirmation and no password/code/token appears in storage, application logs or error text. Use only synthetic dental data.
4. Test existing-user login, admin-created first-password challenge, forgot-password/code reset, refresh and sign-out/revocation against staging. Verify bad/expired/wrong-pool tokens are rejected by the actual API, and two confirmed users cannot read, edit, calculate, save or reopen each other's cases/comparisons or obtain each other's jobs/upload slots. A missing token must fail protected endpoints; `/health` remains public.
5. Test the actual Preview origin, direct `/sign-in?mode=create` and `/sign-in?mode=verify` reloads, mobile-width layout, keyboard navigation and a screen reader. Confirm Cognito messages arrive and WAF/quota failures show a safe, actionable response.
6. Before public rollout, review email production access/quotas, service rate limits, Cognito abuse controls and monitoring. Approve operational ownership, rollback and incident handling. Public login does not establish insurance eligibility or authorize real patient-data processing. Existing `dev`/`demo` stages and deletion/retention settings remain synthetic-data infrastructure; any real patient-data release needs its own approved data-handling and durability review.
7. Only after staging evidence and separate release authorization: review the exact production pool/client, origin, Vercel repository/branch mapping and production public values; approve the Cognito opt-in and deployment order; build/deploy the reviewed commit and smoke-test with controlled accounts. Do not blindly promote a preview built with staging values. Rollback closes new registrations with the reviewed pool setting and restores the previous reviewed frontend; it must retain existing accounts/data and existing sign-in.

Implementation and local tests alone do not mark this production-ready. This checklist describes future authorized operations; it does not record them as completed.
