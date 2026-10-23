# Demo kit (fictional data only)

Everything here is **sample data**: a fictional dental office, plan and patient. Never use real names, member IDs or health details in a demo.

## Insurance Plan Comparison walkthrough

The comparison addition extends the original ActionBridge document and treatment-timing workflow below. It compares two insurance plans against the **same confirmed treatment and schedule**. It does not choose coverage, include premiums, or recommend changing clinical timing.

### Choose the demonstration environment

- **Interactive application:** requires an authorized Cognito account, the configured HTTPS API, and a selected case with confirmed treatment facts. Saving and reopening also require working authenticated storage. Obtain access privately from the project owner. This path remains unverified end to end for the new comparison feature.
- **Cloud-free demonstration:** use the existing Playwright browser tests below. They run the React application locally with fictional data and intercept API/Cognito requests using `mockBackend`; financial responses use the existing engine in the Node test process. These are automated demonstrations, not a standalone offline application or proof of live authentication/storage.

The local development API uses HTTP/demo authentication, while the frontend requires HTTPS/Cognito. Starting both development servers does not establish a compatible authenticated demo. Do not bypass authentication or substitute mock results in the application to make them connect. See the [web setup and test instructions](../../web/README.md).

### Six-step comparison demo

1. **Open the interface.** In a configured authenticated application, sign in and select a fictional case with confirmed procedures and dates. Open **Compare insurance plans** (`/plan-comparison`). Check the common treatment, schedule and case revision before continuing. In browser tests, **Try a sample case** creates the fictional case through the mocked API.
2. **Enter independent plans.** Use **Use current plan** for Plan A only when its confirmed facts are the intended baseline. Give Plan B its own label and enter its categories, network status, allowed amounts, write-offs, policy rules and benefit-year balances independently. Unknown values stay unknown; do not fill them with guesses. For the reproducible fictional example below, use the recipe recorded in the QA report.
3. **Compare returned costs.** Select **Compare plans**. Review patient estimates, insurer payments, contractual write-offs and line items for each plan. Check the assumptions, source caveats, synthetic labels and USD currency. Write-offs reduce the dentist fee; they are not insurer payments. A cost difference appears only when both results are complete and comparable. These estimates are **not insurer confirmation**.
4. **Demonstrate missing information.** Clear Plan B's crown allowed amount and compare again. Plan B should request the missing fact, while Plan A retains its independently computed result. No Plan B estimate or cost difference is invented. Restore the known fictional fact and compare again. Unsupported rules similarly remain explicit rather than becoming a dollar estimate.
5. **Save and reopen.** Read the saving notice, provide the explicit consent, and select **Save comparison**. Reload the application, return to the comparison interface for the same case, and choose the matching **Open saved comparison** entry. Check the restored labels, independent inputs and returned figures. The server checks ownership and the current case revision and recomputes results before saving. Saving does not submit an insurance claim or payment. A stale revision requires reloading and comparing the updated facts.
6. **Print or save a PDF.** With a validated result matching the current inputs, select **Print / Save as PDF**. In the browser's print dialog, choose **Save as PDF**, review every page, optionally disable browser headers/footers, and save locally. The report includes export date, treatment dates, returned amounts, sources, assumptions, missing/unsupported caveats and **NOT INSURER CONFIRMATION**. Destination names and availability vary by browser/device. Editing inputs hides outdated results and the print action until a current result is available.

### Reproducible fictional comparison

The [QA capture recipe](../PLAN_COMPARISON_QA.md#screenshot-evidence) uses the existing three-procedure sample for Plan A and the same treatment dates for Plan B. For Plan B, use basic coverage for all three procedures, out-of-network status, 80% insurer payment, deductible-before-coinsurance, all listed services covered, nearest-cent (`half_up_to_cent`) rounding, and no waiting periods, exclusions or frequency restrictions. Basic services count toward the deductible and annual maximum. Its benefit year is 2026-01-01 through 2026-12-31, with a $2,000 maximum, $0 deductible, $0 already paid and $0 deductible met. Fillings have $250 allowed amounts and $0 write-offs each; the crown has an $800.25 allowed amount and $100 write-off. These values are fictional facts entered independently, not suggested defaults for real insurance.

The recorded QA run returned the following figures for that exact recipe; the demo should always display the actual response rather than hardcoding this table:

| Returned total (USD)  | Plan A |    Plan B |
| --------------------- | -----: | --------: |
| Patient estimate      | $1,200 |   $359.80 |
| Insurer payment       |   $300 | $1,040.20 |
| Contractual write-off |     $0 |      $100 |
| Dentist fees          | $1,500 |    $1,500 |

### Existing mocked browser demonstrations

Use Node **22.13+**, installed repository/web dependencies, built shared packages, and a locally available Playwright-compatible Chromium browser. From the repository root, run a focused headed test:

```bash
# Enter independent plans and display real engine results through mocked transport.
npm --prefix web test -- plan-comparison-api.spec.ts --headed --grep "renders both real engine estimates"

# Save with consent, reload/reopen, and print the restored comparison.
npm --prefix web test -- saved-plan-comparison.spec.ts --headed --grep "saves inputs only with consent"

# Show missing information without inventing the unavailable plan's amount.
npm --prefix web test -- plan-comparison.spec.ts --headed --grep "a missing plan fact does not hide the complete other plan"

# Inspect authoritative report content and print styling using existing export tests.
npm --prefix web test -- plan-comparison-export.spec.ts --headed
```

The tests control their own browser session and mock setup; manually opening the Vite URL does not attach those mocks. Export tests intercept the browser print action or generate Chromium PDF evidence; they do not demonstrate an operating-system print dialog. If Chromium is absent, browser setup must be completed separately; the commands above do not install a browser or dependencies. No AWS account or real sign-in is needed for these mocked demonstrations.

The [comparison QA report](../PLAN_COMPARISON_QA.md) records **487 root regression tests and 85 browser tests passed** on **2026-10-22**, against baseline **`89663c6`**. Those are historical results from that QA run. It also links authentic fictional screenshots. Live HTTPS/Cognito and DynamoDB integration remain unverified; Chromium, viewport and automated accessibility checks do not prove every browser, physical device or assistive technology works.

## Original document-upload and treatment-timing demo

The original team workflow and sample documents are retained below. Its 2026-10-04 live observations are historical evidence, not fresh verification of the comparison addition. Document extraction, voice processing, estimates and saving require the corresponding configured authenticated backend services. `check-demo-docs.mjs` calls the configured API and upload services; it is **not** a cloud-free check and is excluded from the mocked demonstrations above. Never commit its bearer token or use real patient records.

| File                            | What it is                                                                                                                                                    |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sample-treatment-estimate.pdf` | Dentist's estimate: 2 fillings and a crown, with fees, allowed amounts, write-offs, cash prices, planned dates, and the dentist's timing window for the crown |
| `sample-benefits-summary.pdf`   | Plan summary: benefit year, annual maximum, deductible, what the insurer already paid this year, and what the plan pays per service type                      |
| `generate-demo-docs.mjs`        | Recreates both PDFs (`node docs/demo/generate-demo-docs.mjs`)                                                                                                 |
| `check-demo-docs.mjs`           | Runs both PDFs through the live system and prints what is confirmed, asked and calculated                                                                     |

Each fact sits on one line, so the reader returns it whole and the assistant can quote it exactly.

## The numbers in the documents

- Fillings (tooth 14, tooth 15): $250 each, allowed $250, write-off $0, cash price $200, planned 2026-11-10 and 2026-11-11.
- Crown (tooth 30): $1,000, allowed $1,000, write-off $0, cash price $900, planned 2026-11-12. The dentist allows 2026-11-12 to 2027-01-15.
- Benefit year 2026-01-01 to 2026-12-31: annual maximum $800, already paid $500, deductible $50 (none met yet).
- Plan pays: preventive 100%, basic 80% after the deductible, major 50% after the deductible.

**Historical expected results (original live check, 2026-10-04, three runs in a row after that deploy):**

- Six confirmations quoted from the documents: coverage, benefit year, plan rules (including "after the deductible" and "the yearly maximum applies to basic and major"), and the three procedures, all in network, with the crown's timing window (November 12, 2026 to January 15, 2027).
- One question: _"Will your plan renew on January 1, 2027 with the same yearly maximum ($800) and deductible ($50)?"_ Answer **Yes, the same**.
- **You pay $1,200** doing everything now, or **$725 with the crown in January (save $475)**. Self-pay total **$1,300**.

## Original demo walkthrough (about 3 minutes; configured backend required)

1. **Sign in** with your demo account.
2. **Upload** both PDFs on the composer (or **Photo**: show the PDF on a second screen and photograph it).
3. Optionally **Speak** the voice script below; the transcript is added to the text box.
4. **Analyse.** Point out the live checklist: "Reading document 1 … Read 15 lines … Understanding your document".
5. **Is this right? · 1 of 6.** Each card shows the value, the exact quote from the document, and a one-line meaning. Choose **Yes**; on one card choose **Not right** to show nothing is used without consent, then change it back from the summary.
6. **Quick question(s)**, with the definition and "I don't know".
7. **Your estimate is ready:** $1,200. Open **options** → **Sources** (each number's origin) → **Self-pay** ($1,300 vs $1,200).
8. **Review and save** → **My plan**, reload the page, and it's still there.

To skip document extraction in a configured environment, Home → **Try a sample case** uses the fictional $1,200 vs $725 timing fixture. This still requires the authenticated API; it is not an offline fallback or a guarantee of immediate results. Use the mocked browser demonstrations above when cloud access is unavailable.

## Voice script (about 25 seconds)

> "I have dental insurance through work. My dentist recommends two fillings at two hundred fifty dollars each and a crown for one thousand dollars. My plan pays eighty percent for fillings and fifty percent for crowns after a fifty dollar deductible. The annual maximum is eight hundred dollars and insurance already paid five hundred this year. The dentist said the crown can wait until January fifteenth."

## Typed description (paste into the composer)

```
I have dental insurance. My benefit year runs 2026-01-01 to 2026-12-31. The annual maximum is $800 and insurance already paid $500 this year. My deductible is $50 and I haven't met it yet.
The plan pays 80% for basic services and 50% for major services, after the deductible. Both count toward the annual maximum.
My dentist recommends two fillings at $250 each and a crown at $1,000, all in network, and the allowed amounts equal the charges.
The fillings are planned for 2026-11-10 and 2026-11-11 and the crown for 2026-11-12. The dentist said the crown can be done any time up to 2027-01-15.
```

## Prompt for generating more test documents

Use this with any AI writing tool to create variations (keep it fictional):

> Create a fictional, clearly labeled SAMPLE dental treatment estimate and a matching SAMPLE dental plan benefits summary for a software demo. Use a made-up office, plan and patient ("SAMPLE PATIENT"); no real names, member IDs or health history. Write each fact on its own single line, in this style: "Crown, tooth 30 (D2740): fee $1,000.00, allowed $1,000.00, write-off $0.00, cash price $900.00, planned 2026-11-12". The estimate must include 2–4 procedures with CDT codes, fee, allowed amount, write-off, cash price and planned date (YYYY-MM-DD), whether the office is in network, and one sentence giving the dentist's safe timing window for one procedure (for example "The crown can safely be done any time between 2026-11-12 and 2027-01-15"). The benefits summary must include, on one line, the benefit year dates, the annual maximum and the annual deductible; on one line, how much the insurer already paid this year and how much of the deductible is met; one line per service type saying what percentage the plan pays and whether the deductible applies (preventive, basic, major); one line saying the annual maximum applies to basic and major services; and one line describing next year's benefit year dates and terms. Do not write sentences that mention limits only to say they don't apply (for example "No waiting periods apply"). Keep both documents to one page each.

## Notes

The assistant reads documents with AI, so wording on screen can vary between runs. For the same confirmed inputs and engine version, the deterministic calculator returns the same amounts. **Try a sample case** skips extraction but still uses the configured API; show an error honestly if a live service is unavailable. The original team's document-upload and dentist-permitted treatment-timing workflow remains separate from the new two-plan comparison.
