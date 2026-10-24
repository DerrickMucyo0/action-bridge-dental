# ActionBridge Dental appearance restoration

Local review on 2026-10-23. Working branch: `feat/restore-original-look`, starting
at `d749d09`. Reference: `~/Desktop/action-bridge-dental`, read only.

Open the [interactive before/after review](index.html), or the
[desktop comparison](comparison-desktop.png) and
[mobile comparison](comparison-mobile.png). The review includes the landing
hero, full landing page, product previews, estimate preview, sign-in and dashboard.

## Exact application changes

| File                                                      | Change                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| --------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `web/src/landing.css`                                     | Restored reference hero background `#edf3f5`, full-width media, gradient overlays, text width, padding, CTA placement and entrance animation. Restored phone/tablet hero height `94svh` with a `720px` minimum, desktop height `100svh` with a `640px` minimum, and the original 720px/1180px hero breakpoints. Restored the pale sign-in aside, dark wordmark/tagline and reference shade. Kept the newer password-requirements styles and decorative preview hooks. Added CSS dental artwork, with responsive tooth/mirror placement. |
| `web/src/components/welcome-visual.tsx`                   | Replaced the dark bridge/arch composition with new decorative CSS tooth, mirror, light, window, surface and shadow shapes. No photographic asset or external image request.                                                                                                                                                                                                                                                                                                                                                             |
| `web/src/features/landing/landing-page.tsx`               | Moved the hero media outside the content column and restored the reference overlay. Text, navigation, registration links and remaining sections are unchanged.                                                                                                                                                                                                                                                                                                                                                                          |
| `web/src/features/auth/sign-in-page.tsx`                  | Added exactly one decorative `aria-hidden` shade element. No account behavior changed.                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `web/src/components/landing-illustrations.tsx` and `.css` | Replaced four abstract compositions with static promotional UI previews: voice input, document review, treatment input and estimate progress. Used the existing dark green palette, brand geometry, orb and controls. Preserved phone dimensions, arrangement, shadows and exports. Previews are marked `UI PREVIEW`, hidden from assistive technology, have no interactive controls, and contain no amounts or patient data.                                                                                                           |

The reference and working project already had identical dashboard, shell,
navigation, logo, favicon, shared buttons/cards, app stylesheet, font imports,
landing section grids and most public-page styles. Those were retained. Public
pages use Geist; the app uses Plus Jakarta Sans. Neither font, dependency list,
lockfile nor brand asset changed.

The final desktop and mobile dashboard PNGs are byte-for-byte identical across
reference, before and after. Landing heading bounds, font and color match the
reference at both capture sizes. See [comparison evidence](comparison-evidence.json)
and the adjacent layout-metrics JSON files. This does not imply identical hero
imagery; the excluded images are detailed below.

## Functionality preserved

Public registration, email confirmation/resend, password recovery, first-sign-in
password changes, session refresh/revocation, independent Plan A/Plan B inputs,
server estimates, saved comparisons, treatment strategies, print/PDF reports,
revision checks and backend security remain in place.

The API/Cognito services, auth and case state, comparison implementation, contracts,
calculator, backend, infrastructure, mobile source and shared numerical fixtures
have no changes from the starting working tree. Authentication has only the shade
element described above. Production mock behavior was not added.

## Differences that cannot be restored identically

- The welcome tooth/mirror photograph has no verified source/license in the
  existing attribution records. It remains excluded. New CSS dental artwork
  preserves its broad subject and pale blue visual balance, but cannot reproduce
  the photographic detail, lighting, reflections or exact colors.
- The four promotional JPGs (`s1.jpg`, `s2.jpg`, `s3.jpg`, `s5.jpg`) also have
  unresolved provenance. Their layouts remain, with newly composed decorative
  previews rather than the original screen images. Their exact graphics and text
  therefore differ. See [existing rights records](../RELEASE_CHECKLIST.md#image-rights-and-provenance).
- The current account forms retain functional verification/recovery/registration
  content and accessible heading focus. Those additions occupy space absent from
  the old account page; removing them would violate the preservation requirement.
- Screenshots cover local Chrome desktop/phone viewports. They do not establish
  identical Safari rendering, physical-device behavior, live Cognito/email
  delivery, live API/DynamoDB operation or every OS print dialog.

No removed photograph or credential was restored. The original reference source
was never edited or run in place. Its source was copied to an isolated temporary
preview; public assets were read through a reference-only symlink. Reference
screenshots and browser traces containing its images are kept outside the working
project in `/private/tmp/actionbridge-appearance/`. Only before/after screenshots
of the working project and numerical reference layout metrics are included here.
Temporary reference evidence can disappear when the system clears temporary files.

## Verification

Environment: Node 22.23.4; local Google Chrome 156.0.8078.48 via Playwright.
All browser requests to Cognito/API use existing intercepted test transport and
fictional data. No account was registered and no live service was changed.

| Check                            | Result                                                                                                                                             |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Root `npm run check`             | Passed: strict package/backend typecheck and 583 tests across 48 suites.                                                                           |
| Web `npm run typecheck`          | Passed.                                                                                                                                            |
| Web `npm run build`              | Passed after the final artwork adjustments.                                                                                                        |
| Full Playwright suite            | Passed: 163 tests, including registration, recovery, comparison, saved plans and print/PDF coverage (mocked transport).                            |
| Additional public landing checks | Passed at 360×640, 768×900, 1024×768 and 1180×650: no horizontal overflow, visible/contained CTA, menu/anchor behavior and axe accessibility scan. |
| Capture checks                   | Desktop/mobile reference, before and after captured successfully; sign-in axe and font/overflow assertions passed.                                 |
| Formatting                       | Changed TypeScript/CSS and Playwright files pass Prettier; `git diff --check` passes.                                                              |
| Source/diff review               | Only presentation, capture tooling, evidence and asset documentation changed.                                                                      |

The first root run passed 500 loaded tests but could not load 19 mobile suites
because Expo dependencies were absent. After restoring the installed dependencies
from the reference's matching mobile lockfile, the complete 583-test run passed.
The reference dependency tree was read only.

Capture setup initially encountered shared trace-output collisions, blocked font
URLs in the isolated previews, and an unloaded optional mobile font weight. These
were corrected with separate temporary output directories, narrowly allowed local
font paths in the temporary preview configurations, and explicit font loading in
the capture harness. No application logic was changed to resolve these issues.

The build emits existing dependency annotation and bundle-size advisories. These
do not prevent a successful build. The restoration was initially left uncommitted.
The user subsequently authorized a local commit only. No push, merge, deployment
or AWS modification was performed.

## Evidence and reproduction

`before/` contains the working project before edits; `after/` contains the final
working project. Desktop captures use 1440×900 and mobile captures use 390×844,
device scale 1, reduced motion and locally served fonts. Full-page captures may
be taller. `metrics-*.json` records heading bounds/font/color; reference metrics
are stored separately without reference imagery.

From an environment with Node ≥22.13, dependencies and Playwright Chromium:

```bash
npm run check
npm --prefix web run typecheck
npm --prefix web run build
npm --prefix web test
APPEARANCE_PHASE=after npm --prefix web test -- --config=playwright.appearance.config.ts
```

Set `PLAYWRIGHT_CHANNEL=chrome` for the installed Chrome alternative used here.
`APPEARANCE_BASE_URL` can target an already running isolated snapshot server;
`APPEARANCE_OUTPUT_DIR` can select an evidence directory. The appearance config
otherwise starts the working app with fixed fictional public test settings.
Reference captures default outside the working project.

The test tooling changes are `web/playwright.config.ts` (optional browser channel),
`web/playwright.appearance.config.ts` (capture/responsive runner),
`web/tests/appearance.spec.ts` (screenshots, font/overflow and sign-in accessibility
checks), and `web/tests/landing-responsive.spec.ts` (public hero/navigation checks).
`web/README.md` and `docs/RELEASE_CHECKLIST.md` now describe the current artwork;
historical attribution, contributor and license records are retained.

## Local commit review

The authorized local commit contains 47 files: eight design/documentation files,
four browser-test/configuration files, and 35 screenshot/report artifacts. All were
reviewed. New-feature and security implementations remain unchanged. No secrets or
unauthorized photographs were found in these changes; reference imagery and traces
remain outside the project. The original web source matches the pre-edit isolated
snapshot. `git diff --check` passed before staging and is checked again on the
staged changes before committing.

Complete changed-file manifest:

```text
docs/RELEASE_CHECKLIST.md
docs/visual-restoration/README.md
docs/visual-restoration/after/dashboard-desktop.png
docs/visual-restoration/after/dashboard-mobile.png
docs/visual-restoration/after/estimate-desktop.png
docs/visual-restoration/after/estimate-mobile.png
docs/visual-restoration/after/landing-desktop.png
docs/visual-restoration/after/landing-full-desktop.png
docs/visual-restoration/after/landing-full-mobile.png
docs/visual-restoration/after/landing-mobile.png
docs/visual-restoration/after/metrics-desktop.json
docs/visual-restoration/after/metrics-mobile.json
docs/visual-restoration/after/product-desktop.png
docs/visual-restoration/after/product-mobile.png
docs/visual-restoration/after/sign-in-desktop.png
docs/visual-restoration/after/sign-in-mobile.png
docs/visual-restoration/before/dashboard-desktop.png
docs/visual-restoration/before/dashboard-mobile.png
docs/visual-restoration/before/estimate-desktop.png
docs/visual-restoration/before/estimate-mobile.png
docs/visual-restoration/before/landing-desktop.png
docs/visual-restoration/before/landing-full-desktop.png
docs/visual-restoration/before/landing-full-mobile.png
docs/visual-restoration/before/landing-mobile.png
docs/visual-restoration/before/metrics-desktop.json
docs/visual-restoration/before/metrics-mobile.json
docs/visual-restoration/before/product-desktop.png
docs/visual-restoration/before/product-mobile.png
docs/visual-restoration/before/sign-in-desktop.png
docs/visual-restoration/before/sign-in-mobile.png
docs/visual-restoration/comparison-desktop.png
docs/visual-restoration/comparison-evidence.json
docs/visual-restoration/comparison-mobile.png
docs/visual-restoration/index.html
docs/visual-restoration/reference-metrics-desktop.json
docs/visual-restoration/reference-metrics-mobile.json
web/README.md
web/playwright.appearance.config.ts
web/playwright.config.ts
web/src/components/landing-illustrations.css
web/src/components/landing-illustrations.tsx
web/src/components/welcome-visual.tsx
web/src/features/auth/sign-in-page.tsx
web/src/features/landing/landing-page.tsx
web/src/landing.css
web/tests/appearance.spec.ts
web/tests/landing-responsive.spec.ts
```
