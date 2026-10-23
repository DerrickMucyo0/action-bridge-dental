# ActionBridge Dental web

Responsive React + TypeScript site for the original ActionBridge Dental application, extended by Derrick Mucyo with a two-plan insurance comparison workflow. The site uses the existing Cognito sign-in, typed API client and benefits estimator. Production comparison figures come from the backend for the case revision on screen; test mocks remain confined to automated tests. See the [project README](../README.md) for original-team credit and contribution boundaries.

The comparison's live HTTPS/Cognito and DynamoDB integration remain unverified. The [Ticket 13 QA report](../docs/PLAN_COMPARISON_QA.md) records the completed local checks and their limits.

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

This root script builds the shared contracts and engine and starts Vite at **http://127.0.0.1:5173/**. When dependencies are already installed, no reinstall is needed. Choose **Sign in** and use an account provided privately by the team administrator. A first sign-in may ask for a new password. A configured HTTPS API, Cognito client and permitted browser origin are required for interactive backend operations; these commands do not provision them.

### Settings (public, not secrets)

| Variable                 | Value                                                           |
| ------------------------ | --------------------------------------------------------------- |
| `VITE_API_BASE_URL`      | Stack output `ApiBaseUrl` (https, includes the stage, no `/v1`) |
| `VITE_COGNITO_CLIENT_ID` | Stack output `UserPoolClientId`                                 |
| `VITE_COGNITO_REGION`    | `us-east-2`                                                     |

These are embedded in the built site. They are the same values as the mobile app's `EXPO_PUBLIC_*` settings. A missing or malformed value shows a configuration error on the sign-in page, never sample data.

The API accepts browser calls only from configured origins in the stack's `WebOrigins` parameter (CORS), including the configured Vercel site, `http://localhost:5173` and `http://127.0.0.1:5173`. Any origin change requires an authorized infrastructure update; it is outside this documentation task.

## Journey

Landing page at `/` for signed-out visitors → **Sign in** (`/sign-in`; returns you to the page you asked for) → Home → **composer** (speak, type, attach up to three pages or take a photo — all as a draft) → **Analyse** once → assistant: "Here's what I understood" (each item quotes the words or document it came from) and grouped questions with "I don't know" → facts review (every value labeled with its source) → options (server results) → details → review and save (one idempotency key per Save, safe to retry) → My plan and Activity (server ledger). "Try a sample case" and "Enter details step by step" are also available.

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

These are automated demonstrations: the browser follows the test and normally closes afterward. Add the existing Playwright `--ui` option instead of `--headed` to select, rerun and inspect tests in its UI. The print tests intercept `window.print()` or generate a Chromium PDF in the test process; they do not demonstrate an OS print dialog. The test server uses port **5174**, which must be free. Missing Playwright browser binaries must be provisioned separately before running these commands; no browser installation is part of Ticket 14.

## Code layout

- `src/config.ts`: public settings.
- `src/services/api.ts`: typed API client (every response validated against `@actionbridge/contracts`) and S3 upload.
- `src/services/cognito.ts`: sign-in, first-sign-in password, refresh and revoke.
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
```

Use these package build steps to validate an existing checkout without reinstalling dependencies. The root `build:web` and web-local `build:web` convenience scripts invoke `npm ci`; they are unnecessary for this validation.

Browser coverage includes the original sign-in, sample, document composer, confirmed facts, self-pay, treatment-timing and strategy-saving workflow; independent insurance plans; save/reopen; print export; failed requests; and accessibility/layout checks. Despite its name, `live-app.spec.ts` also uses mocked transport.

The documented **Ticket 13 QA run on 2026-10-22**, baseline **`89663c6`**, recorded **487 root regression tests passed** and **85 browser tests passed**. These are historical results from [the QA report](../docs/PLAN_COMPARISON_QA.md), not tests rerun for Ticket 14. The root `npm run check` covers shared-package/backend TypeScript and package, backend and mobile-logic tests; it does not replace web checks or the separate mobile application typecheck.

### Verification limits

- Live HTTPS/Cognito integration and live DynamoDB saving/retrieval remain unverified. Local tests use intercepted transport, in-memory storage or stubbed DynamoDB clients.
- `npm run dev:api` uses HTTP and demo-header authentication; this frontend requires HTTPS and Cognito. Do not bypass authentication or relax transport checks to connect them.
- A browser viewport test is not a physical-device test. Accessible-name and axe checks are not a real screen-reader session.
- Native printing, OS PDF destinations and Safari/mobile behavior require separate manual checks.
- The original application workflow and historical deployment notes below are retained; they do not establish a newly verified comparison deployment.

## Original deployment configuration (Vercel)

Vercel builds from the **repository root** (`vercel.json`): `npm ci && npm run build:web`, output `web/dist`. In the Vercel project, set the three `VITE_*` variables above under Settings → Environment Variables, then redeploy. Pushes to `main` deploy production; other branches get preview URLs. Preview URLs are not in the API's CORS list unless added to `WebOrigins`.

This describes the existing setup, not an instruction to deploy during Ticket 14. No comparison deployment or live integration is claimed; cloud or publication work needs separate authorization and settled redistribution rights.

The current landing and sign-in headers use an original CSS visual in
`src/components/welcome-visual.tsx`. The welcome photograph has been removed from
the working tree; the existing attribution records below are retained for history
review. Historical image cleanup is still pending.

The product and estimate sections use four original, decorative React/CSS
illustrations in `src/components/landing-illustrations.tsx` and its CSS file.
They are built from new geometric shapes, without copying or tracing the former
screenshots, and contain no calculated amounts. The current
`public/assets/landing/s1.jpg`, `s2.jpg`, `s3.jpg`, and `s5.jpg` files have been
removed. Copies in the legacy mockup directory and Git history remain unchanged
and still require a separate publication review.

## Asset attribution

- Login photo (tooth and mirror): shared with the mobile app (`mobile/assets/images/welcome.jpg`), served from `public/assets/welcome.jpg`. Source and license still to be recorded before release.
- Dental room: Ozkan Guner, Unsplash, photo `1643916800611-1302e8d27c38`. `public/assets/dental-room.jpg`.
- Plus Jakarta Sans: `@fontsource/plus-jakarta-sans`, SIL Open Font License.
- Icons: Lucide, ISC license.
