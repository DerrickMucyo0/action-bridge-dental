# ActionBridge Dental web

Responsive React + TypeScript site for the original ActionBridge Dental application, extended by Derrick Mucyo with a two-plan insurance comparison workflow. The site uses the existing Cognito sign-in, typed API client and benefits estimator. Production comparison figures come from the backend for the case revision on screen; test mocks remain confined to automated tests. See the [project README](../README.md) for original-team credit and contribution boundaries.

The comparison's live HTTPS/Cognito and DynamoDB integration remain unverified. The [comparison QA report](../docs/PLAN_COMPARISON_QA.md) records the completed local checks and their limits.

## Run locally

Requires **Node 22.13 or newer** and npm. First-time dependency setup, from the repository root:

```bash
npm ci
npm --prefix web ci
npm run build
cp web/.env.example web/.env.local
```

On Windows PowerShell, use `npm.cmd` if needed and `Copy-Item web/.env.example web/.env.local` for the copy step. Fill in the three existing public settings below, then run:

```bash
npm run dev:web
```

This root script builds the shared contracts and engine and starts Vite at **http://127.0.0.1:5173/**. When dependencies are already installed, no reinstall is needed. Choose **Create account** to register and confirm your email on a stage with public registration enabled, or **Sign in** with an existing account. Admin-created accounts may still ask for a new password on first sign-in. A configured HTTPS API, Cognito client and permitted browser origin are required for interactive backend operations; these commands do not provision them.

### Settings (public, not secrets)

| Variable                 | Value                                                           |
| ------------------------ | --------------------------------------------------------------- |
| `VITE_API_BASE_URL`      | Stack output `ApiBaseUrl` (https, includes the stage, no `/v1`) |
| `VITE_COGNITO_CLIENT_ID` | Stack output `UserPoolClientId`                                 |
| `VITE_COGNITO_REGION`    | `us-east-2`                                                     |

These are embedded in the built site. They are the same values as the mobile app's `EXPO_PUBLIC_*` settings. A missing or malformed value shows a configuration error on the sign-in page, never sample data.

For the **core staging backend**, set `VITE_BACKGROUND_JOBS_ENABLED=false`
before building. This disables assistant jobs, document/photo uploads, recording,
transcription and speech before credential lookup or network requests. Home and
deep links offer manual entry instead; case edits, estimates, comparisons and
strategy saves remain available. The core backend also omits those routes and
functions; the frontend flag is a usability gate, not an authorization boundary.
The preview landing page explains these limits before sign-in and directs Get
started to existing-account sign-in. This does not change Cognito registration
settings or grant account access.
Existing full backends keep their behavior when the flag is unset or `true`.
Any other configured value is an error. Local mocked assistant flows stay enabled
in the main browser-test configuration.

The checked-in `.env.staging.example` contains the four reviewed public core-staging
settings, including the required `false` flag. Review it before copying values to
an existing local environment; do not overwrite that environment blindly. The
configured API is currently kept inactive, and building with these values does
not activate it or publish the site. Independent staging hosting is planned for
AWS Amplify Hosting and requires separate publication approval.

The isolated core staging API takes its CORS origins from `StagingWebOrigins`;
the original full template uses `WebOrigins` for its other environments. Before
publishing an Amplify branch, separately approve only its exact HTTPS origin in
the staging parameter. Do not infer permission from an existing Vercel or local
origin. CORS changes require an approved infrastructure update; they do not
replace Cognito authentication or the disabled-endpoint guard.

## Account registration

`/sign-in?mode=create` accepts email, password and password confirmation, then asks for the email verification code. Cognito controls account creation, confirmation, resend limits and password recovery; unconfirmed users must verify before signing in. Existing sign-in, first-sign-in password changes and forgot-password routes remain available. Registration does not create an admin account or grant access to another user's cases.

Self-registration remains **disabled by default in the infrastructure template**. The feature needs a separately reviewed Cognito configuration and staging verification; this branch does not change an AWS user pool or deploy the site. See [public registration and production deployment checklist](../docs/PUBLIC_REGISTRATION.md) for the required Cognito settings, email-delivery limits, Vercel configuration and release checks.

## Journey

Landing page at `/` for signed-out visitors → **Sign in** (`/sign-in`; returns you to the page you asked for) → Home → **composer** (speak, type, attach up to three pages or take a photo — all as a draft) → **Analyse** once → assistant: "Here's what I understood" (each item quotes the words or document it came from) and grouped questions with "I don't know" → facts review (every value labeled with its source) → options (server results) → details → review and save (one idempotency key per Save, safe to retry) → My plan and Activity (server ledger). "Try a sample case" and "Enter details step by step" are also available.

- **Assistant recovery:** after a failed analysis, enter details manually in the same saved case without starting another analysis. Confirmed facts stay available, unknown values stay unknown, and a case changed elsewhere must be reloaded before saving. Retry is offered only while the server's attempt limit allows it.
- **Stopping an analysis:** Stop waits for the server's response and shows its actual state, including completion that raced cancellation. Pending Stop requests cannot be duplicated. Failures leave the analysis visible for an explicit retry, and older polls or responses after navigation cannot overwrite the current page.
- **Voice:** the browser records WebM/Ogg (Opus) or MP4, uploads it to a private, time-limited S3 slot, and Amazon Transcribe returns words you can edit. The microphone is on only while recording.
- **Documents and photos:** PDF, JPEG or PNG, one page each, up to 5 MB. Files go straight to private storage and are deleted after the server reads them.
- **Sessions:** the access token stays in memory. The refresh token and email are kept in `sessionStorage` (this tab only) so a reload doesn't sign you out. Nothing goes to `localStorage` except the IDs of cases you opened and a display-name preference.

### Compare two insurance plans

Open a case, review its facts, then choose **Compare insurance plans** (`/plan-comparison`). Enter Plan A and Plan B independently; **Use current plan for Plan A** explicitly imports only that plan. Each plan has its own policy rules, benefit periods, deductibles, maximums, categories, network status, allowed amounts and write-offs. Unknown facts remain unknown. Both plans use the same confirmed treatment and schedule.

Compare sends the selected case ID, revision, unchanged treatment/schedule and candidate plan facts to `POST /v1/cases/{caseId}/plan-comparison` through the existing authenticated client. Shared TypeScript/Zod contracts validate requests and responses. The comparison engine calls the existing estimator separately for each plan; React formats returned integer-cent amounts. Complete, missing-information and unsupported states are shown independently. Patient-cost differences appear only when the server returns a comparable difference. Cost breakdowns show patient payments, insurer payments and contractual write-offs with readable text equivalents. Premiums and enrollment decisions are excluded.

Editing either plan clears results. A stale revision requires **Reload treatment**, which clears the drafts so you can review the updated treatment before comparing again.

After comparing, check the explicit consent box and choose **Save comparison**. The browser posts only comparison inputs and consent to `POST /v1/cases/{caseId}/plan-comparisons`; the server checks ownership and revision, recomputes the outputs, and stores an immutable snapshot. A retry reuses the same idempotency key. Missing-information and unsupported results can be saved with their original status. The panel lists up to 20 snapshots for the current treatment version and reopens their independent plan inputs and authoritative results using authenticated, revision-checked GET requests. Saving never updates the source case or its existing saved treatment strategy. Editing clears the save confirmation and consent, and ignores responses belonging to an older draft.

For manual testing, the configured HTTPS API must already provide that endpoint and accept the existing Cognito login and browser origin. Use fictional cases only. `npm run dev:api` is an HTTP server with demo-header authentication and is incompatible with this web client's HTTPS/Cognito configuration; do not disable authentication to connect them. No deployment or live AWS verification is part of this integration.

### Print / Save as PDF

For a validated result matching the current request, select **Print / Save as PDF**. In the browser's print dialog, choose **Save as PDF**, review the pages, optionally disable browser headers and footers, and save. This is native browser printing, not a downloadable PDF generated by the server. The report includes the export date, common treatment, independent returned amounts, currency, assumptions, provenance caveats and **NOT INSURER CONFIRMATION** warning. Missing and unsupported results retain their caveats. Reopened current-revision comparisons use the same report. Printing sends no report data to a PDF service and does not save a comparison to the backend.

The PDF destination and page layout depend on the browser and operating system. Automated Chromium checks do not verify every native print dialog or device.

See the [demo walkthrough](../docs/demo/README.md) for the original document/timing journey and the comparison steps.

## Demonstrate without AWS credentials

Use the existing browser tests with installed dependencies and an installed Playwright Chromium browser. They serve the real React application and intercept API/Cognito requests through `tests/mock-api.ts`; the Node test process uses the real benefits engine. The Playwright configuration supplies fictional public test settings. No real login, AWS credentials or deployed backend is needed, and no production mock mode is enabled.

From the repository root:

```bash
npm run build
npm --prefix web test -- plan-comparison-api.spec.ts --headed --workers=1 --grep "renders both real engine estimates"
npm --prefix web test -- saved-plan-comparison.spec.ts --headed --workers=1 --grep "saves inputs only"
npm --prefix web test -- plan-comparison-export.spec.ts --headed --workers=1 --grep "report prints authoritative"
```

These are automated demonstrations: the browser follows the test and normally closes afterward. Add the existing Playwright `--ui` option instead of `--headed` to select, rerun and inspect tests in its UI. The print tests intercept `window.print()` or generate a Chromium PDF in the test process; they do not demonstrate an OS print dialog. The test server uses port **5174**, which must be free. Missing Playwright browser binaries must be provisioned separately before running these commands.

## Code layout

- `src/config.ts`: public settings.
- `src/services/api.ts`: typed API client (every response validated against `@actionbridge/contracts`) and S3 upload.
- `src/services/cognito.ts`: registration, email confirmation/resend, sign-in, password recovery, first-sign-in password, refresh and revoke.
- `src/state/auth.tsx`: session and the API client.
- `src/state/case-store.tsx`: current case, edits (PATCH with expected revision), results per revision, saved plan.
- `src/state/use-job.ts`: assistant job polling.
- `src/domain/`: pure helpers: edits → PATCH with sources (`edits.ts`), source labels (`provenance.ts`), assistant answers, composer rules, self-pay quotes, the labeled sample case.
- `src/features/`: pages by flow (`intake` composer, `assistant`, `case`, `options`, `plan`, `saved`, `account`, `plan-comparison`).
- `src/features/plan-comparison/`: independent plan forms, validated results, cost breakdowns, saved-comparison restoration and the print report.

## Verify

With dependencies and Playwright Chromium already installed, from the repository root:

```bash
npm run build
npm --prefix web run typecheck
npm --prefix web run build
npm --prefix web test -- plan-comparison.spec.ts plan-comparison-api.spec.ts saved-plan-comparison.spec.ts plan-comparison-export.spec.ts live-app.spec.ts
npm --prefix web test -- --config playwright.core.config.ts
```

Use these package build steps to validate an existing checkout without reinstalling dependencies. The root `build:web` and web-local `build:web` convenience scripts invoke `npm ci`; they are unnecessary for this validation.

Browser coverage includes the original sign-in, sample, document composer, confirmed facts, self-pay, treatment-timing and strategy-saving workflow; independent insurance plans; save/reopen; print export; failed requests; and accessibility/layout checks. Despite its name, `live-app.spec.ts` also uses mocked transport.

The documented **QA run on 2026-10-22**, baseline **`89663c6`**, recorded **487 root regression tests passed** and **85 browser tests passed**. These are historical results from [the QA report](../docs/PLAN_COMPARISON_QA.md). The root `npm run check` covers shared-package/backend TypeScript and package, backend and mobile-logic tests; it does not replace web checks or the separate mobile application typecheck.

### Verification limits

- Live HTTPS/Cognito integration and live DynamoDB saving/retrieval remain unverified. Local tests use intercepted transport, in-memory storage or stubbed DynamoDB clients.
- `npm run dev:api` uses HTTP and demo-header authentication; this frontend requires HTTPS and Cognito. Do not bypass authentication or relax transport checks to connect them.
- A browser viewport test is not a physical-device test. Accessible-name and axe checks are not a real screen-reader session.
- Native printing, OS PDF destinations and Safari/mobile behavior require separate manual checks.
- The original application workflow and historical deployment notes below are retained; they do not establish a newly verified comparison deployment.

## Original deployment configuration (Vercel)

The checked-in **repository-root** `vercel.json` specifies install `npm ci`, build `npm run build:web`, output `web/dist`, SPA rewrites and security headers. Use the repository root as the Vercel Root Directory; shared packages live outside `web/`. A separate legacy `web/vercel.json` targets output `dist` and is not the recommended root configuration.

This checkout does not establish which repository, branch or environment an existing Vercel project is connected to. Verify its Git integration and Production Branch before any push. A connected project can automatically publish a push to its configured production branch (often `main`); keep this feature branch in Preview with staging API/Cognito values. Configure the three public `VITE_*` variables for that Preview branch, and build again after changing them. Add only the exact approved preview origin to staging `WebOrigins`. See the [deployment checklist](../docs/PUBLIC_REGISTRATION.md) before changing live configuration or publishing.

Comparison deployment and live integration remain unverified. Publication requires the rights holders' authorization.

The landing hero and sign-in panel restore the reference layout and pale blue
palette using a new CSS dental still life in `src/components/welcome-visual.tsx`.
See the [appearance review](../docs/visual-restoration/README.md) for before/after
screenshots and verification. The welcome photograph has been removed from
the working tree; the existing attribution records below are retained for history
review. Historical image cleanup is still pending.

The product and estimate sections use four static, decorative UI previews in
`src/components/landing-illustrations.tsx` and its CSS file. They use the existing
app's dark green palette, branding, orb and controls, without copying or tracing
the former screenshots, and contain no calculated amounts. The current
`public/assets/landing/s1.jpg`, `s2.jpg`, `s3.jpg`, and `s5.jpg` files have been
removed. The unused `ActionBridge landing page mockups (2)/` and
`../App mockups in progress/` archives and the standalone
`../mobile/assets/Glossy Molar and Dental Instruments.png` have also been removed
from the working tree. The canonical `../mobile/actionbridge-dental-v3/` design
archive and existing attribution records are retained. Copies in Git history
still require separate cleanup before publication; working-tree removal does not
remove historical images.

## Asset attribution

- Login photo (tooth and mirror): shared with the mobile app (`mobile/assets/images/welcome.jpg`), served from `public/assets/welcome.jpg`. Source and license still to be recorded before release.
- Dental room: Ozkan Guner, Unsplash, photo `1643916800611-1302e8d27c38`. `public/assets/dental-room.jpg`.
- Plus Jakarta Sans: `@fontsource/plus-jakarta-sans`, SIL Open Font License.
- Icons: Lucide, ISC license.
