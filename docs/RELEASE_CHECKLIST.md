# Insurance plan comparison release checklist

Ticket 15 local preparation, October 22, 2026. Reviewed baseline: `01d2ae8` on
`feat/insurance-plan-comparison`. This checklist does not authorize publication or
deployment. The repository has not been pushed or deployed during this work.

## Rights, attribution and publication approval

- [x] Original-developer written approval is reported as received by Derrick Mucyo.
      Keep the approval privately; do not commit correspondence or personal details.
- [ ] Before publication, confirm the recorded approval covers public redistribution
      of this modified version and any other relevant rights holders' contributions.
- [ ] Resolve the image provenance and permissions listed below.
- [x] Preserve original Git history, author identities, credits and existing notices.
      The original ActionBridge application and Derrick's comparison contribution
      remain distinguished in the [root README](../README.md).
- [ ] Retain applicable dependency and asset notices in the published source and
      distribution. [mobile/LICENSE](../mobile/LICENSE) is an existing notice; it
      does not establish a project-wide license for all ActionBridge code or assets.
- [ ] Obtain separate authorization for the actual repository publication. Do not
      add a project-wide license without the rights holders' authorization.

## Credential review: publication is blocked

The review reports paths and categories only. Credential values are intentionally
excluded from this checklist and its validation output.

| Finding                                                                                                                                                      | Required follow-up before publication                                                                                                                                                                                         |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The current tracked `docs/EVIDENCE.md`, line 5, still contains shared sign-in credentials. The current root README no longer contains that credential block. | Sanitize the evidence document in a separate cleanup; use private access instructions instead. Never reproduce the values in a diff, issue, report or screenshot.                                                             |
| Reachable Git history retains credential-bearing versions of `README.md`, `docs/EVIDENCE.md` and the deleted `docs/JUDGING.md`.                              | The administrator must confirm revocation or rotation of the exposed credentials and review remaining account/session access. Removing values from the latest files or adding ignore rules does not remove historical copies. |

- [ ] Complete the current-document cleanup and administrator rotation/revocation
      confirmation. Do not test the exposed credentials or contact cloud services
      to check whether they still work.
- [ ] Review the final publication candidate and retained history again without
      printing secrets. Keep original history and attribution; no history rewrite
      is authorized by this ticket. Any unresolved historical exposure blocks
      publication until the owner agrees a safe approach.
- [x] Reviewed 494 committed files, 135 locally reachable commits, 930 unique blobs
      and commit messages. Of those blobs, 903 were text; 27 binary images/thumbnails
      were not inspected with OCR. No cloud credentials were required or used.
- [x] Existing ignore rules exclude dependencies, build output, local environment
      files and test artifacts. Example environment files and public configuration
      identifiers are not proof of credential exposure; review new values before
      committing them.

Heuristic checks did not find additional AWS access-key, private-key, provider-token,
JWT, URL-embedded credential or npm-token patterns. Mock/test values and an explicitly
fictional legacy prototype login were distinguished from the confirmed exposure.
No dedicated secret scanner, binary/archival inspection, unreachable-history,
reflog, remote or ignored-local-file review was performed. This is not a guarantee
that every secret or personal detail has been found, nor a test of credential validity.

## Image rights and provenance

Current working-tree update: the welcome photograph has been replaced by original
CSS dental artwork on web and a native UI bridge visual on mobile, and both
`welcome.jpg` files have been removed.
The records below and earlier QA results are retained as historical evidence.
Historical welcome-image removal is still required before publishing retained Git
history; the other image-rights questions below remain open.

Current landing-page update: the four `web/public/assets/landing/` placements
(`s1.jpg`, `s2.jpg`, `s3.jpg`, and `s5.jpg`) now use static, decorative UI previews
from `web/src/components/landing-illustrations.tsx` and its CSS file. These use
the app's visual language without copying or tracing the former screenshots.
The four public JPEGs have been removed from the working tree. Their copies in
the unused legacy web mockup archive have also been removed; Git history still
contains copies with publication rights unverified. The table below retains the
earlier provenance findings.

Current legacy-asset cleanup: the unused `web/ActionBridge landing page mockups (2)/`
and `App mockups in progress/` archives and the standalone
`mobile/assets/Glossy Molar and Dental Instruments.png` have been removed from the
working tree. The canonical `mobile/actionbridge-dental-v3/` design archive,
`web/public/brand.svg`, Expo graphics, QA screenshots, contributor credits and
licenses are retained. Historical image removal remains a separate task; this
cleanup does not resolve the brand mark's public-redistribution permission or
other outstanding publication approvals.

| Asset                                                                                | Current evidence and required decision                                                                                                                                                                                                                  |
| ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `web/public/assets/welcome.jpg` and the identical `mobile/assets/images/welcome.jpg` | The [web attribution notes](../web/README.md#asset-attribution) explicitly leave the source and license unresolved. Record the source, permitted redistribution/use and required credit, or replace/remove the image with authorization before release. |
| `web/public/assets/landing/s1.jpg`, `s2.jpg`, `s3.jpg`, `s5.jpg`                     | Used as ActionBridge screen imagery; source/ownership documentation was not found. Confirm their provenance and any embedded third-party content. This is an unresolved permission question, not a finding of infringement.                             |
| Historical `web/public/assets/dental-room.jpg` attribution                           | The web README records an Unsplash photographer credit, but that asset is absent from the current tree. Reconcile the historical note and verify rights before restoring or redistributing the image.                                                   |

Preserve existing photographer, font, icon and copyright notices. Original-developer
approval does not automatically settle third-party asset rights. Include legacy
prototype assets in the final publication review; the review does not certify a
complete third-party asset inventory.

## CI prepared locally

The [CI workflow](../.github/workflows/ci.yml) runs on pushes, ordinary pull requests
and manual dispatch. It uses Ubuntu 24.04, Node.js 22, a read-only repository token,
checkout without persisted credentials, a 20-minute job limit and cancellation of
superseded runs. It has no deployment step, AWS credentials, repository secrets or
privileged pull-request trigger.

The workflow uses the official [checkout](https://github.com/actions/checkout) and
[setup-node](https://github.com/actions/setup-node) actions. Review action updates
with the rest of the release changes.

| CI command, from the repository root unless noted                                   | Purpose                                                                                                                                                                   |
| ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `npm ci`                                                                            | Install existing root/workspace dependencies from the committed lockfile.                                                                                                 |
| `npm run check`                                                                     | Build shared packages, typecheck package tests/backend and run package, backend and mobile-logic regression tests. It does not typecheck the complete mobile application. |
| `npm --prefix web ci`                                                               | Install the existing web lockfile after shared package output is built.                                                                                                   |
| `npm --prefix web run typecheck`                                                    | Check React/web TypeScript.                                                                                                                                               |
| `npm --prefix web run build`                                                        | Check TypeScript and build the production website.                                                                                                                        |
| `npx --no-install playwright install --with-deps chromium`, working directory `web` | Provision the Chromium version required by the installed Playwright package on the clean runner.                                                                          |
| `npm --prefix web test`                                                             | Run all existing comparison and original-workflow browser tests, including accessibility and print checks, against mocked transport.                                      |

The browser tests use fictional fixtures and mock API, Cognito and upload requests.
They do not require a live backend or AWS account. Dependencies and a browser are
installed on the future clean CI runner; none were installed during local validation.
No new package or lockfile changes are needed.

## Ticket 15 local validation

These are new local checks of the CI's existing commands, separate from the
historical [Ticket 13 QA evidence](PLAN_COMPARISON_QA.md). Environment: macOS,
Node.js 22.23.4, already installed dependencies and Chrome 156.0.8078.47.

| Command/check                                                                                                                | Result                                                                                                                                                                       |
| ---------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `npm run check`                                                                                                              | Passed: shared-package build, package-test/backend TypeScript and 487 tests in 43 files.                                                                                     |
| `npm --prefix web run typecheck`                                                                                             | Passed, no TypeScript errors.                                                                                                                                                |
| `npm --prefix web run build`                                                                                                 | Passed, 1,750 modules. Existing Zod comment-annotation and 568.19 kB JavaScript chunk-size warnings remain.                                                                  |
| `node web/node_modules/@playwright/test/cli.js test --config=/private/tmp/actionbridge-plan-comparison.playwright.config.ts` | Passed: all 85 tests across 5 specs, including comparison, save/reopen, export, accessibility and the original workflow; 3.4 minutes.                                        |
| Standard-library Ruby YAML parse and workflow assertions                                                                     | Passed: triggers, read-only token, checkout credential setting, Node version, command order and existing package scripts. This is not GitHub-hosted execution or actionlint. |
| `web/node_modules/.bin/prettier --check .github/workflows/ci.yml docs/RELEASE_CHECKLIST.md`                                  | Passed for both new files.                                                                                                                                                   |
| Relative-link/anchor and referenced-image checks                                                                             | Passed: 7 local links/anchors, identical welcome images, existing landing screenshots and absent historical dental-room asset.                                               |
| `git diff --check` and `git diff --no-index --check /dev/null <new-file>` for each new file                                  | Passed, including whitespace checks for the untracked additions.                                                                                                             |

The temporary browser configuration extends the committed Playwright configuration,
uses the installed Chrome and starts Vite only on localhost. It preserves the
existing mocked API/Cognito settings and writes runner artifacts outside the
repository. CI instead uses Playwright's installed Chromium on Linux. Local checks
do not verify a clean dependency installation or execution on a GitHub runner.

Existing browser-runner color-environment warnings are nonfatal. No application,
authentication, infrastructure or calculation behavior was changed for CI.
No application tests failed in this run. The full mobile application typecheck,
clean installs and browser installation were not run locally.

## Remaining publication and deployment gates

- [ ] Review the complete diff, tracked-file list, ignore rules, commit authorship
      and value-free security findings before any publication. Do not stage private
      notes, environment files, tokens or real patient data.
- [x] Original remote is already named `upstream`; no `origin` is configured. Remote
      configuration was inspected without changing it.
- [ ] Only after explicit publication authorization and cleared blockers: have the
      owner create a separate empty repository, verify its destination and add the
      new `origin` deliberately. Preserve `upstream` and original history. Never
      force-push to another developer's repository.
- [ ] On the authorized repository, verify the first GitHub Actions run, including
      lockfile installation and Linux Chromium. Configure main-branch protection
      and require the `TypeScript, tests and build` check with reviewed pull requests
      where the repository settings support it. Repository settings were not changed.
- [ ] Review any hosting integration before connecting or pushing to the new
      repository. The existing [Vercel configuration notes](../web/README.md#original-deployment-configuration-vercel)
      describe branch-triggered deployments; a source publication is not deployment
      approval. No hosting integration was contacted or configured here.
- [ ] Keep demonstrations synthetic and clearly label estimates as **NOT INSURER
      CONFIRMATION**. The [mocked demo walkthrough](demo/README.md) is available
      without claiming a verified live comparison environment.
- [ ] Verify live HTTPS/Cognito transport, authorization and CORS in a separately
      authorized environment. The frontend's HTTPS/Cognito requirements remain
      incompatible with the local HTTP/demo-auth backend. Do not weaken authentication.
- [ ] Verify live DynamoDB ownership, revision guards and persistence separately;
      local adapter/SDK-command tests do not establish deployed integration.
- [ ] Keep native printing, representative devices/browsers and assistive-technology
      verification open as described in the QA report. Chromium tests do not prove
      behavior on every browser or operating system.
- [ ] Obtain explicit deployment approval, an agreed cost limit, appropriate
      credentials and a reviewed data-retention model before any cloud activity.
      A local synthetic demonstration remains sufficient for this preparation phase.

**Local preparation is distinct from release approval.** Credential remediation,
asset rights, final publication authorization and hosted CI verification remain
open; live cloud integration and deployment remain outside this ticket.
