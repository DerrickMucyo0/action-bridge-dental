import { expect, test, type Locator, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { comparePlans } from '@actionbridge/benefits-engine';
import {
  PlanComparisonRequestSchema,
  PlanComparisonResultSchema,
  type ComparisonPlan,
  type PlanComparisonRequest,
  type PlanComparisonResult,
  type SourceFact,
} from '@actionbridge/contracts';
import fixture from '../../docs/fixtures/dental-regression.json' with { type: 'json' };
import type { ComparisonTestProps } from './plan-comparison-harness';

declare global {
  interface Window {
    fictionalPrintCalls: number;
  }
}

/** Fictional inputs only. Calculations run in Playwright's Node process, never React. */
function syntheticRequest(): PlanComparisonRequest {
  const plan = (planId: string, label: string): ComparisonPlan =>
    ({
      planId,
      label,
      policy: structuredClone(fixture.policy),
      planYears: structuredClone(fixture.planYears),
      procedureFacts: Object.fromEntries(
        fixture.procedures.map((procedure) => [
          procedure.id,
          {
            category: procedure.category,
            network: procedure.network,
            allowedCents: procedure.allowedCents,
            contractualWriteoffCents: procedure.contractualWriteoffCents,
          },
        ]),
      ),
      sourceFacts: [],
    }) as ComparisonPlan;
  return PlanComparisonRequestSchema.parse({
    caseId: 'synthetic-report-case',
    expectedRevision: fixture.caseRevision,
    currency: fixture.currency,
    treatment: {
      procedures: fixture.procedures.map((procedure) => {
        const {
          category,
          network,
          allowedCents,
          contractualWriteoffCents,
          proposedDate,
          ...shared
        } = procedure;
        return shared;
      }),
      schedule: fixture.procedures.map((procedure) => ({
        procedureId: procedure.id,
        date: procedure.proposedDate,
      })),
      sourceFacts: [],
    },
    planA: plan('synthetic-plan-a', 'Fictional Alpha'),
    planB: plan('synthetic-plan-b', 'Fictional Beta'),
  });
}

const syntheticResult = (
  request: PlanComparisonRequest,
): PlanComparisonResult =>
  PlanComparisonResultSchema.parse(comparePlans(request));

function sourceFact(overrides: Partial<SourceFact> = {}): SourceFact {
  return {
    id: 'fictional-source-fact',
    fieldPath: 'procedureFacts.crown-1.allowedCents',
    value: 100000,
    sourceId: 'fictional-private-source-id',
    location: {
      page: 2,
      section: 'Fictional benefit summary',
      snippet: 'Fictional private source quote',
    },
    origin: 'document_extracted',
    extractionStatus: 'low_confidence',
    userConfirmed: false,
    insurerVerification: { status: 'not_verified' },
    conflict: true,
    recordedAt: '2026-10-01T12:00:00Z',
    ...overrides,
  };
}

const exportButton = (page: Page) =>
  page.getByRole('button', { name: 'Print / Save as PDF', exact: true });
const report = (page: Page) =>
  page.getByRole('article', {
    name: 'Insurance plan comparison report',
    exact: true,
  });
const planReport = (page: Page, side: 'Plan A' | 'Plan B', label: string) =>
  report(page).getByRole('region', { name: `${side} · ${label}`, exact: true });

async function show(page: Page, props: ComparisonTestProps) {
  await page.clock.setFixedTime(new Date('2026-10-22T15:30:00Z'));
  await page.addInitScript(() => {
    window.fictionalPrintCalls = 0;
    window.print = () => {
      window.fictionalPrintCalls += 1;
    };
  });
  await page.goto('/tests/plan-comparison-harness.html');
  await expect(
    page.getByRole('heading', { name: 'Synthetic component test' }),
  ).toBeVisible();
  await page.evaluate((next) => window.renderPlanComparisonTest(next), props);
}

async function printReport(page: Page) {
  await expect(exportButton(page)).toBeVisible();
  await exportButton(page).click();
  await expect
    .poll(() => page.evaluate(() => window.fictionalPrintCalls))
    .toBe(1);
  await page.emulateMedia({ media: 'print' });
  await expect(report(page)).toBeVisible();
  return report(page);
}

async function expectTotals(region: Locator, amounts: string[]) {
  const list = region.locator('.comparison-report-totals');
  await expect(list.getByRole('term')).toHaveText([
    'Estimated patient cost',
    'Estimated insurer payment',
    'Contractual write-off',
    'Dentist fees',
  ]);
  await expect(list.getByRole('definition')).toHaveText(amounts);
}

test('report prints authoritative independent plan totals, exact cents, treatment, schedule and export metadata', async ({
  page,
}) => {
  const request = syntheticRequest();
  request.planB.procedureFacts['crown-1']!.allowedCents = 79975;
  request.planB.procedureFacts['crown-1']!.contractualWriteoffCents = 20025;
  await show(page, {
    request,
    state: { status: 'ready', result: syntheticResult(request) },
  });
  await expect(report(page)).toHaveCount(0);
  const printed = await printReport(page);
  await expect(printed).toContainText('ActionBridge Dental');
  await expect(printed).toContainText('Export date');
  await expect(printed).toContainText('October 22, 2026');
  await expect(printed).toContainText('UTC');
  await expect(
    printed
      .locator('.comparison-report-meta div')
      .filter({ hasText: 'Case revision' })
      .getByRole('definition'),
  ).toHaveText('1');
  await expect(printed).toContainText('USD');
  const shared = printed.getByRole('table', {
    name: 'Shared treatment and schedule (USD)',
    exact: true,
  });
  for (const [label, date] of [
    ['Filling one', 'Nov 10, 2026'],
    ['Filling two', 'Nov 11, 2026'],
    ['Crown', 'Nov 12, 2026'],
  ]) {
    await expect(
      shared.getByRole('row').filter({ hasText: label }),
    ).toContainText(date!);
  }
  const a = planReport(page, 'Plan A', 'Fictional Alpha');
  const b = planReport(page, 'Plan B', 'Fictional Beta');
  await expectTotals(a, ['$1,200 USD', '$300 USD', '$0 USD', '$1,500 USD']);
  await expectTotals(b, [
    '$999.75 USD',
    '$300 USD',
    '$200.25 USD',
    '$1,500 USD',
  ]);
  await expect(b.getByRole('table')).toHaveAccessibleName(
    'Plan B treatment cost estimates (USD)',
  );
  await expect(b.getByRole('row').filter({ hasText: 'Crown' })).toContainText(
    '$799.75',
  );
  await expect(b.getByRole('row').filter({ hasText: 'Crown' })).toContainText(
    '$200.25',
  );
  await expect(printed).toContainText('NOT INSURER CONFIRMATION');
  await expect(printed).toContainText(/not.*guarantee.*insurer/i);
  await expect(printed).toContainText(
    /Contractual write-offs.*reductions in the dentist fee/i,
  );
  await expect(printed.getByRole('button')).toHaveCount(0);
  await expect(
    page.getByRole('heading', { name: 'Synthetic component test' }),
  ).toBeHidden();
});

test('report retains assumptions, synthetic labels and independent provenance caveats without copying private source metadata', async ({
  page,
}) => {
  const request = syntheticRequest();
  request.treatment.schedule.find(
    (entry) => entry.procedureId === 'crown-1',
  )!.date = '2027-01-01';
  request.treatment.sourceFacts = [
    sourceFact({
      id: 'fictional-treatment-source',
      fieldPath: 'procedures.crown-1.timingSource',
      origin: 'synthetic',
      extractionStatus: 'not_applicable',
      conflict: false,
      userConfirmed: true,
    }),
  ];
  request.planA.sourceFacts = [sourceFact()];
  request.planB.sourceFacts = [
    sourceFact({
      id: 'fictional-user-source',
      origin: 'user_entered',
      extractionStatus: 'not_applicable',
      conflict: false,
      userConfirmed: true,
      location: null,
    }),
  ];
  await show(page, {
    request,
    state: { status: 'ready', result: syntheticResult(request) },
  });
  const printed = await printReport(page);
  await expect(printed).toContainText(/Synthetic sample/i);
  await expect(printed).toContainText(/unchanged/i);
  await expect(printed).toContainText(/conditional/i);
  await expect(planReport(page, 'Plan A', 'Fictional Alpha')).toContainText(
    'From your document',
  );
  await expect(planReport(page, 'Plan A', 'Fictional Alpha')).toContainText(
    /not been confirmed|unconfirmed/i,
  );
  await expect(planReport(page, 'Plan A', 'Fictional Alpha')).toContainText(
    /conflict/i,
  );
  await expect(planReport(page, 'Plan A', 'Fictional Alpha')).toContainText(
    /low confidence/i,
  );
  await expect(planReport(page, 'Plan B', 'Fictional Beta')).toContainText(
    'Provided by you',
  );
  await expect(printed).toContainText(/not been verified/i);
  await expect(printed).not.toContainText('fictional-private-source-id');
  await expect(printed).not.toContainText('Fictional private source quote');
  await expect(printed).toContainText(/premiums.*enrollment/i);
  await expect(printed).toContainText(/dentist.*timing/i);
});

test('zero and equal outcomes print known zero amounts without declaring a winner', async ({
  page,
}) => {
  const request = syntheticRequest();
  for (const procedure of request.treatment.procedures) {
    procedure.providerChargeCents = 0;
    for (const plan of [request.planA, request.planB])
      plan.procedureFacts[procedure.id]!.allowedCents = 0;
  }
  await show(page, {
    request,
    state: { status: 'ready', result: syntheticResult(request) },
  });
  const printed = await printReport(page);
  for (const [side, label] of [
    ['Plan A', 'Fictional Alpha'],
    ['Plan B', 'Fictional Beta'],
  ] as const) {
    await expectTotals(planReport(page, side, label), [
      '$0 USD',
      '$0 USD',
      '$0 USD',
      '$0 USD',
    ]);
  }
  await expect(printed).toContainText(/same estimated patient cost|equal/i);
  await expect(printed).not.toContainText(/winner|best plan|NaN|Infinity/);
});

for (const state of ['missing', 'unsupported'] as const) {
  test(`${state} plan prints its limitations while preserving the complete other plan without invented amounts`, async ({
    page,
  }) => {
    const request = syntheticRequest();
    if (state === 'missing')
      request.planB.procedureFacts['crown-1']!.allowedCents = null;
    else
      request.planB.policy!.waitingPeriods = [
        {
          id: 'fictional-wait',
          description: 'Fictional waiting period',
          categoryIds: ['major'],
        },
      ];
    await show(page, {
      request,
      state: { status: 'ready', result: syntheticResult(request) },
    });
    const printed = await printReport(page);
    const b = planReport(page, 'Plan B', 'Fictional Beta');
    await expectTotals(planReport(page, 'Plan A', 'Fictional Alpha'), [
      '$1,200 USD',
      '$300 USD',
      '$0 USD',
      '$1,500 USD',
    ]);
    await expect(b).toContainText(
      state === 'missing' ? 'Needs information' : 'Unsupported plan rules',
    );
    await expect(b).toContainText(
      state === 'missing' ? /allowed amount/i : /waiting periods/i,
    );
    await expect(b.getByRole('table')).toHaveCount(0);
    await expect(b.getByRole('definition')).toHaveCount(0);
    await expect(b).not.toContainText(/\$0|\$1,200/);
    await expect(printed).toContainText(/difference.*unavailable/i);
    await expect(printed).toContainText('NOT INSURER CONFIRMATION');
  });
}

for (const invalid of [
  'stale revision',
  'changed plan',
  'changed treatment',
  'changed schedule',
  'fractional amount',
  'missing request',
  'loading',
  'error',
] as const) {
  test(`${invalid} cannot expose an export action or a report through native printing`, async ({
    page,
  }) => {
    const request = syntheticRequest();
    const result = syntheticResult(request);
    let props: ComparisonTestProps = {
      request,
      state: { status: 'ready', result },
    };
    if (invalid === 'stale revision') request.expectedRevision += 1;
    if (invalid === 'changed plan')
      request.planB.planId = 'different-fictional-plan';
    if (invalid === 'changed treatment')
      request.treatment.procedures[0]!.label = 'Changed fictional treatment';
    if (invalid === 'changed schedule')
      request.treatment.schedule[0]!.date = '2026-11-11';
    if (
      invalid === 'fractional amount' &&
      result.planA.estimate.status === 'estimated'
    )
      result.planA.estimate.totals.patientPaysCents = 10.5;
    if (invalid === 'missing request')
      props = { request: null, state: { status: 'ready', result } };
    if (invalid === 'loading')
      props = { request, state: { status: 'loading' } };
    if (invalid === 'error')
      props = {
        request,
        state: { status: 'error', message: 'Fictional service failure' },
      };
    await show(page, props);
    await expect(exportButton(page)).toHaveCount(0);
    await page.evaluate(() => window.dispatchEvent(new Event('beforeprint')));
    await page.emulateMedia({ media: 'print' });
    await expect(report(page)).toHaveCount(0);
  });
}

test('printing preserves local privacy and cancellation leaves the comparison usable', async ({
  page,
}) => {
  const request = syntheticRequest();
  await show(page, {
    request,
    state: { status: 'ready', result: syntheticResult(request) },
  });
  await expect(exportButton(page)).toBeVisible();
  await page.waitForLoadState('networkidle');
  const requests: string[] = [];
  const popups: Page[] = [];
  const downloads: string[] = [];
  page.on('request', (next) => requests.push(`${next.method()} ${next.url()}`));
  page.on('popup', (popup) => popups.push(popup));
  page.on('download', (download) =>
    downloads.push(download.suggestedFilename()),
  );
  await printReport(page);
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  );
  expect(requests).toEqual([]);
  expect(popups).toEqual([]);
  expect(downloads).toEqual([]);
  await page.evaluate(() => window.dispatchEvent(new Event('afterprint')));
  await page.emulateMedia({ media: 'screen' });
  await expect(report(page)).toHaveCount(0);
  await expect(exportButton(page)).toBeVisible();
  await expect(
    page.getByRole('region', { name: 'Plan comparison results', exact: true }),
  ).toContainText('$1,200');
});

test('native printing uses the same guarded report and never retains a report after inputs change', async ({
  page,
}) => {
  const request = syntheticRequest();
  await show(page, {
    request,
    state: { status: 'ready', result: syntheticResult(request) },
  });
  await expect(exportButton(page)).toBeVisible();
  await page.evaluate(() => window.dispatchEvent(new Event('beforeprint')));
  await page.emulateMedia({ media: 'print' });
  await expect(report(page)).toBeVisible();
  await page.evaluate(() =>
    window.renderPlanComparisonTest({
      request: null,
      state: { status: 'idle' },
    }),
  );
  await expect(report(page)).toHaveCount(0);
});

for (const width of [360, 1440]) {
  test(`export action and printed text are accessible at ${width}px and labels remain escaped text`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    const request = syntheticRequest();
    request.planB.label = '<img src=x onerror=alert(1)> Fictional Beta';
    await show(page, {
      request,
      state: { status: 'ready', result: syntheticResult(request) },
    });
    await expect(exportButton(page)).toBeVisible();
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    await exportButton(page).focus();
    await page.keyboard.press('Enter');
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            (window as Window & { fictionalPrintCalls: number })
              .fictionalPrintCalls,
        ),
      )
      .toBe(1);
    await page.emulateMedia({ media: 'print' });
    await expect(report(page)).toBeVisible();
    await expect(report(page)).toContainText(request.planB.label);
    await expect(report(page).locator('img, script, iframe')).toHaveCount(0);
    expect(
      (await new AxeBuilder({ page }).include('.comparison-report').analyze())
        .violations,
    ).toEqual([]);
    await expect(report(page).getByRole('table').first()).toHaveAccessibleName(
      'Shared treatment and schedule (USD)',
    );
  });
}

test('long reports retain all line items and source caveats in genuine multipage PDF output without clipped tables', async ({
  page,
}, testInfo) => {
  const request = syntheticRequest();
  const original = request.treatment.procedures[0]!;
  request.treatment.procedures = Array.from({ length: 6 }, (_, index) => ({
    ...original,
    id: `fictional-procedure-${index + 1}`,
    label: `Fictional treatment ${index + 1}: ${'long treatment label '.repeat(4)}`,
  }));
  request.treatment.schedule = request.treatment.procedures.map(
    (procedure) => ({ procedureId: procedure.id, date: '2026-11-10' }),
  );
  for (const plan of [request.planA, request.planB]) {
    plan.procedureFacts = Object.fromEntries(
      request.treatment.procedures.map((procedure) => [
        procedure.id,
        {
          category: 'basic',
          network: 'in',
          allowedCents: procedure.providerChargeCents,
          contractualWriteoffCents: 0,
        },
      ]),
    );
    plan.sourceFacts = Array.from({ length: 6 }, (_, index) =>
      sourceFact({
        id: `${plan.planId}-fact-${index + 1}`,
        fieldPath: `procedureFacts.fictional-procedure-${(index % 6) + 1}.allowedCents`,
      }),
    );
  }
  const result = syntheticResult(request);
  // Long, fictional server-provided assumptions exercise pagination; returned amounts stay unchanged.
  for (const plan of [result.planA, result.planB]) {
    if (plan.estimate.status === 'estimated') {
      for (let index = 0; index < 8; index += 1) {
        plan.estimate.assumptions.push({
          code: 'SYNTHETIC_INPUT',
          message: `Fictional report assumption ${index + 1}: ${'Confirm the quoted plan terms and treatment scope with the fictional insurer and dentist. '.repeat(2)}`,
        });
      }
    }
  }
  await show(page, {
    request,
    state: {
      status: 'ready',
      result: PlanComparisonResultSchema.parse(result),
    },
  });
  const printed = await printReport(page);
  await expect(
    printed
      .getByRole('table', {
        name: 'Shared treatment and schedule (USD)',
        exact: true,
      })
      .getByRole('row'),
  ).toHaveCount(7);
  for (const [side, label] of [
    ['Plan A', 'Fictional Alpha'],
    ['Plan B', 'Fictional Beta'],
  ] as const) {
    await expect(
      planReport(page, side, label).getByRole('table').getByRole('row'),
    ).toHaveCount(7);
    await expect(planReport(page, side, label)).toContainText(
      'Fictional treatment 6:',
    );
  }
  for (const table of await printed.getByRole('table').all()) {
    expect(
      await table.evaluate(
        (element) => element.scrollWidth <= element.clientWidth + 1,
      ),
    ).toBe(true);
    expect(
      await table
        .locator('thead')
        .evaluate((element) => getComputedStyle(element).display),
    ).toBe('table-header-group');
  }
  const clipped = await printed.locator('*').evaluateAll((elements) =>
    elements
      .filter((element) => {
        const style = getComputedStyle(element);
        return (
          ['hidden', 'clip'].includes(style.overflowY) &&
          element.scrollHeight > element.clientHeight + 1
        );
      })
      .map((element) => element.tagName),
  );
  expect(clipped).toEqual([]);
  const pdf = await page.pdf({
    path: testInfo.outputPath('fictional-comparison-report.pdf'),
    format: 'A4',
    printBackground: true,
    preferCSSPageSize: true,
  });
  expect(pdf.subarray(0, 5).toString()).toBe('%PDF-');
  expect(
    (pdf.toString('latin1').match(/\/Type\s*\/Page\b/g) ?? []).length,
  ).toBeGreaterThan(1);
});
