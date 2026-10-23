import { expect, test, type Locator, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { estimateCase } from '@actionbridge/benefits-engine';
import {
  DentalCaseInputSchema,
  PlanComparisonRequestSchema,
  PlanComparisonResultSchema,
  type ComparisonPlan,
  type PlanComparisonRequest,
  type PlanComparisonResult,
} from '@actionbridge/contracts';
import fixture from '../../docs/fixtures/dental-regression.json' with { type: 'json' };
import type { ComparisonTestProps } from './plan-comparison-harness';
import { mockBackend } from './mock-api';

/** All inputs and engine outputs in this file are fictional test data. */
function syntheticRequest(): PlanComparisonRequest {
  const source = DentalCaseInputSchema.parse({
    caseRevision: fixture.caseRevision,
    currency: fixture.currency,
    coverageMode: fixture.coverageMode,
    policy: fixture.policy,
    planYears: fixture.planYears,
    procedures: fixture.procedures,
  });
  const plan = (planId: string, label: string): ComparisonPlan => ({
    planId,
    label,
    policy: structuredClone(source.policy),
    planYears: structuredClone(source.planYears),
    procedureFacts: Object.fromEntries(
      source.procedures.map((procedure) => [
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
  });
  return PlanComparisonRequestSchema.parse({
    caseId: 'synthetic-case',
    expectedRevision: source.caseRevision,
    currency: source.currency,
    treatment: {
      procedures: source.procedures.map((procedure) => {
        const {
          category,
          network,
          allowedCents,
          contractualWriteoffCents,
          proposedDate,
          selfPayQuote,
          ...shared
        } = procedure;
        return shared;
      }),
      schedule: source.procedures.map((procedure) => ({
        procedureId: procedure.id,
        date: procedure.proposedDate,
      })),
      sourceFacts: [],
    },
    planA: plan('synthetic-plan-a', 'Fictional Alpha'),
    planB: plan('synthetic-plan-b', 'Fictional Beta'),
  });
}

/**
 * Run the existing estimator twice in Playwright's Node process, never in the browser.
 * The test supplies the reviewed fixture delta explicitly; the UI only renders this envelope.
 */
function syntheticResult(
  request: PlanComparisonRequest,
  reviewedDifferenceCents: number | null = 0,
): PlanComparisonResult {
  const estimate = (plan: ComparisonPlan) => {
    const input = DentalCaseInputSchema.parse({
      caseRevision: request.expectedRevision,
      currency: request.currency,
      coverageMode: 'insured',
      policy: plan.policy,
      planYears: plan.planYears,
      procedures: request.treatment.procedures.map((procedure) => ({
        ...procedure,
        ...plan.procedureFacts[procedure.id],
        proposedDate: request.treatment.schedule.find(
          (entry) => entry.procedureId === procedure.id,
        )!.date,
      })),
    });
    const result = estimateCase(input);
    if (result.status === 'invalid')
      throw new Error('Synthetic UI test input is contradictory.');
    return result;
  };
  const estimateA = estimate(request.planA);
  const estimateB = estimate(request.planB);
  return PlanComparisonResultSchema.parse({
    caseId: request.caseId,
    caseRevision: request.expectedRevision,
    currency: request.currency,
    engineVersion: estimateA.engineVersion,
    treatment: request.treatment,
    planA: {
      planId: request.planA.planId,
      label: request.planA.label,
      estimate: estimateA,
    },
    planB: {
      planId: request.planB.planId,
      label: request.planB.label,
      estimate: estimateB,
    },
    planBMinusPlanACents: reviewedDifferenceCents,
  });
}

async function showResults(page: Page, props: ComparisonTestProps) {
  await page.goto('/tests/plan-comparison-harness.html');
  await expect(
    page.getByRole('heading', { name: 'Synthetic component test' }),
  ).toBeVisible();
  await page.evaluate((next) => window.renderPlanComparisonTest(next), props);
  return page.getByRole('region', {
    name: 'Plan comparison results',
    exact: true,
  });
}

const breakdown = (region: Locator, side: 'Plan A' | 'Plan B') =>
  region.getByRole('figure', {
    name: `${side} cost breakdown · Fictional ${side === 'Plan A' ? 'Alpha' : 'Beta'}`,
    exact: true,
  });

/** The native definition list is the accessible equivalent of the decorative bar. */
async function expectBreakdown(
  region: Locator,
  side: 'Plan A' | 'Plan B',
  values: {
    patient: string;
    insurer: string;
    writeoff: string;
    fees: string;
  },
) {
  const figure = breakdown(region, side);
  await expect(figure).toBeVisible();
  await expect(
    figure.getByRole('heading', { name: 'Cost breakdown' }),
  ).toBeVisible();
  await expect(figure.getByRole('term')).toHaveText([
    'Estimated patient cost',
    'Estimated insurer payment',
    'Contractual write-off',
    'Dentist fees',
  ]);
  await expect(figure.getByRole('definition')).toHaveText([
    values.patient,
    values.insurer,
    values.writeoff,
    values.fees,
  ]);
  await expect(figure.locator('.comparison-cost-track')).toHaveAttribute(
    'aria-hidden',
    'true',
  );
  return figure;
}

async function openForm(page: Page) {
  const api = await mockBackend(page);
  await page.goto('/sign-in');
  await page.getByLabel('Email', { exact: true }).fill('jordan@example.com');
  await page.getByLabel('Password', { exact: true }).fill('A-long-password-1');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('button', { name: 'Try a sample case' }).click();
  await expect(
    page.getByRole('heading', { name: "Here is what we'll use" }),
  ).toBeVisible();
  await page
    .getByRole('button', { name: 'Compare insurance plans', exact: true })
    .click();
  await expect(
    page.getByRole('heading', {
      name: 'Compare insurance plans',
      exact: true,
      level: 2,
    }),
  ).toBeVisible();
  await expect(
    page.getByText('No saved comparisons for this treatment version.', {
      exact: true,
    }),
  ).toBeVisible();
  return api;
}

const planGroup = (page: Page, name: 'Plan A' | 'Plan B') =>
  page.getByRole('group', { name, exact: true });

async function openCrown(group: Locator) {
  const summary = group.locator('summary').filter({ hasText: /^Crown$/ });
  const open = await summary.evaluate(
    (element) => (element.parentElement as HTMLDetailsElement).open,
  );
  if (!open) await summary.click();
}

test('two-plan form shows shared treatment and keeps unknown insurance facts independent', async ({
  page,
}) => {
  const api = await openForm(page);
  const a = planGroup(page, 'Plan A');
  const b = planGroup(page, 'Plan B');
  await openCrown(a);
  await openCrown(b);
  await expect(page.getByText('Crown', { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/Nov 12, 2026/).first()).toBeVisible();
  await expect(page.getByText(/Synthetic sample/).first()).toBeVisible();
  for (const group of [a, b]) {
    await expect(group.getByLabel('Plan name', { exact: true })).toHaveValue(
      '',
    );
    await expect(
      group.getByLabel('Crown · Benefit category', { exact: true }),
    ).toHaveValue('unknown');
    await expect(
      group.getByLabel('Crown · Provider network', { exact: true }),
    ).toHaveValue('unknown');
    await expect(
      group.getByLabel('Crown · Allowed amount', { exact: true }),
    ).toHaveValue('');
    await expect(
      group.getByLabel('Crown · Dentist write-off', { exact: true }),
    ).toHaveValue('');
  }
  await a
    .getByRole('button', { name: 'Use current plan', exact: true })
    .click();
  await openCrown(a);
  await expect(
    a.getByLabel('Crown · Allowed amount', { exact: true }),
  ).toHaveValue('1000');
  await expect(
    a.getByLabel('Crown · Provider network', { exact: true }),
  ).toHaveValue('in');
  await expect(
    b.getByLabel('Crown · Allowed amount', { exact: true }),
  ).toHaveValue('');
  await expect(
    b.getByLabel('Crown · Provider network', { exact: true }),
  ).toHaveValue('unknown');
  await expect(
    b.getByRole('button', { name: 'Use current plan', exact: true }),
  ).toHaveCount(0);

  await b
    .getByLabel('Plan name', { exact: true })
    .fill('Fictional alternative');
  await b
    .getByLabel('Crown · Benefit category', { exact: true })
    .selectOption('basic');
  await b
    .getByLabel('Crown · Provider network', { exact: true })
    .selectOption('out');
  await b.getByLabel('Crown · Allowed amount', { exact: true }).fill('800.25');
  await b.getByLabel('Crown · Dentist write-off', { exact: true }).fill('100');
  await expect(
    a.getByLabel('Crown · Benefit category', { exact: true }),
  ).toHaveValue('major');
  await expect(
    a.getByLabel('Crown · Provider network', { exact: true }),
  ).toHaveValue('in');
  await expect(
    a.getByLabel('Crown · Allowed amount', { exact: true }),
  ).toHaveValue('1000');
  await expect(
    a.getByLabel('Crown · Dentist write-off', { exact: true }),
  ).toHaveValue('0');
  await b.getByLabel('Crown · Allowed amount', { exact: true }).fill('');
  await expect(
    b.getByLabel('Crown · Allowed amount', { exact: true }),
  ).toHaveValue('');
  await expect(
    a.getByLabel('Crown · Allowed amount', { exact: true }),
  ).toHaveValue('1000');
  expect(
    api.requests.some((request) => request.path.endsWith('/plan-comparison')),
  ).toBe(false);
});

test('form validates names and malformed amounts, sends unknowns without editing or saving the case', async ({
  page,
}) => {
  const api = await openForm(page);
  const requestsBefore = api.requests.length;
  const a = planGroup(page, 'Plan A');
  const b = planGroup(page, 'Plan B');
  await openCrown(b);
  await page
    .getByRole('button', { name: 'Compare plans', exact: true })
    .click();
  await expect(
    page.getByText('Name both plans before continuing.'),
  ).toBeVisible();
  await a.getByLabel('Plan name', { exact: true }).fill('Fictional Alpha');
  await b.getByLabel('Plan name', { exact: true }).fill('Fictional Beta');
  await b.getByLabel('Crown · Allowed amount', { exact: true }).fill('12.345');
  await page
    .getByRole('button', { name: 'Compare plans', exact: true })
    .click();
  await expect(
    b.getByLabel('Crown · Allowed amount', { exact: true }),
  ).toHaveAttribute('aria-invalid', 'true');
  await expect(page.getByRole('alert').first()).toBeVisible();
  expect(api.requests.slice(requestsBefore)).toEqual([]);
  await b.getByLabel('Crown · Allowed amount', { exact: true }).fill('');
  await page
    .getByRole('button', { name: 'Compare plans', exact: true })
    .click();
  await expect(
    page.getByText('Needs information', { exact: true }),
  ).toHaveCount(2);
  await expect(
    page.getByRole('figure', { name: /cost breakdown/ }),
  ).toHaveCount(0);
  const requests = api.requests.slice(requestsBefore);
  expect(requests).toHaveLength(1);
  expect(requests[0]).toMatchObject({ method: 'POST' });
  expect(requests[0]!.path).toMatch(/\/plan-comparison$/);
  await expect(
    page.getByText('Estimated patient cost', { exact: true }),
  ).toHaveCount(0);
  await b
    .getByLabel('Plan name', { exact: true })
    .fill('Edited fictional Beta');
  await expect(
    page.getByText('Needs information', { exact: true }),
  ).toHaveCount(0);
  expect(api.requests.slice(requestsBefore)).toEqual(requests);
});

test('benefit periods start without invented calendar dates or balances', async ({
  page,
}) => {
  await openForm(page);
  const b = planGroup(page, 'Plan B');
  await b
    .getByRole('button', { name: 'Add benefit year', exact: true })
    .click();
  const dates = b.locator('input[type="date"]');
  await expect(dates).toHaveCount(2);
  await expect(dates.nth(0)).toHaveValue('');
  await expect(dates.nth(1)).toHaveValue('');
  await expect(
    planGroup(page, 'Plan A').locator('input[type="date"]'),
  ).toHaveCount(0);
  await dates.nth(0).fill('2026-07-01');
  await dates.nth(1).fill('2027-06-30');
  await expect(dates.nth(0)).toHaveValue('2026-07-01');
  await expect(dates.nth(1)).toHaveValue('2027-06-30');
});

test('prepared request retains null unknowns, exact integer cents and independent facts', async ({
  page,
}) => {
  const api = await openForm(page);
  const record = [...api.cases.values()][0]!;
  await page.goto('/tests/plan-comparison-harness.html');
  await expect(
    page.getByRole('heading', { name: 'Synthetic component test' }),
  ).toBeVisible();
  await page.evaluate(
    (current) => window.renderPlanComparisonFormTest(current),
    record,
  );
  const a = planGroup(page, 'Plan A');
  const b = planGroup(page, 'Plan B');
  await openCrown(a);
  await a.getByLabel('Plan name', { exact: true }).fill('Fictional Alpha');
  await b.getByLabel('Plan name', { exact: true }).fill('Fictional Beta');
  await a
    .getByLabel('Crown · Benefit category', { exact: true })
    .selectOption('major');
  await a
    .getByLabel('Crown · Provider network', { exact: true })
    .selectOption('in');
  await a.getByLabel('Crown · Allowed amount', { exact: true }).fill('800.25');
  await a.getByLabel('Crown · Dentist write-off', { exact: true }).fill('0');
  await page
    .getByRole('button', { name: 'Compare plans', exact: true })
    .click();
  await expect
    .poll(() => page.evaluate(() => window.preparedComparisonTest))
    .not.toBeNull();
  const prepared = PlanComparisonRequestSchema.parse(
    await page.evaluate(() => window.preparedComparisonTest),
  );
  expect(prepared).toMatchObject({
    caseId: record.caseId,
    expectedRevision: record.caseRevision,
    currency: 'USD',
  });
  expect(prepared.planA.procedureFacts['crown-1']).toEqual({
    category: 'major',
    network: 'in',
    allowedCents: 80025,
    contractualWriteoffCents: 0,
  });
  expect(prepared.planB.procedureFacts['crown-1']).toEqual({
    category: null,
    network: 'unknown',
    allowedCents: null,
    contractualWriteoffCents: null,
  });
  expect(prepared.planA.planYears).toEqual({});
  expect(prepared.planB.planYears).toEqual({});
  expect(prepared.planB.policy!.allServicesCovered).toBeNull();
  expect(prepared.planB.policy!.rounding).toBeNull();
  expect(prepared.treatment.schedule).toEqual(
    record.procedures.map((procedure) => ({
      procedureId: procedure.id,
      date: procedure.proposedDate ?? procedure.dentistEarliestDate,
    })),
  );
  expect(
    prepared.treatment.procedures.every(
      (procedure) =>
        !('allowedCents' in procedure) && !('category' in procedure),
    ),
  ).toBe(true);
  expect(prepared.planA.sourceFacts).toContainEqual(
    expect.objectContaining({
      fieldPath: 'procedureFacts.crown-1.allowedCents',
      value: 80025,
      origin: 'user_entered',
      insurerVerification: { status: 'not_verified' },
    }),
  );
});

test('complete results render returned costs, line items, assumptions and the signed patient-pay difference', async ({
  page,
}) => {
  const request = syntheticRequest();
  request.planB.planYears['py-2026']!.insurerAlreadyPaidCents = 0;
  const result = syntheticResult(request, -50000);
  const region = await showResults(page, {
    request,
    state: { status: 'ready', result },
  });
  const a = region.getByRole('region', {
    name: 'Plan A · Fictional Alpha',
    exact: true,
  });
  const b = region.getByRole('region', {
    name: 'Plan B · Fictional Beta',
    exact: true,
  });
  await expect(a).toContainText('Complete estimate');
  await expect(a).toContainText('$1,200');
  await expect(b).toContainText('$700');
  await expectBreakdown(region, 'Plan A', {
    patient: '$1,200 USD',
    insurer: '$300 USD',
    writeoff: '$0 USD',
    fees: '$1,500 USD',
  });
  await expectBreakdown(region, 'Plan B', {
    patient: '$700 USD',
    insurer: '$800 USD',
    writeoff: '$0 USD',
    fees: '$1,500 USD',
  });
  await expect(region).toContainText(
    'Fictional Beta costs an estimated $500 less than Fictional Alpha for this treatment.',
  );
  await expect(a.getByRole('table')).toHaveAccessibleName(
    'Procedure breakdown · Fictional Alpha',
  );
  await expect(
    a.getByRole('columnheader', { name: 'Patient pays', exact: true }),
  ).toBeVisible();
  await expect(
    a.getByRole('rowheader', { name: 'Crown', exact: true }),
  ).toBeVisible();
  await expect(a).toContainText('Assumptions and conditions');
  await expect(a).toContainText('Synthetic sample');
  await expect(region).toContainText(
    'not a guarantee of insurer approval or payment',
  );
  await expect(region).toContainText('Source case revision 1');
  await a
    .getByText('How each patient cost is made up', { exact: true })
    .click();
  await expect(
    a.getByText('Balance billing', { exact: true }).first(),
  ).toBeVisible();
});

test('equal returned costs show an equal outcome without a winning plan', async ({
  page,
}) => {
  const request = syntheticRequest();
  const region = await showResults(page, {
    request,
    state: { status: 'ready', result: syntheticResult(request) },
  });
  await expect(region).toContainText(
    'Both plans have the same estimated patient cost.',
  );
  await expect(region).not.toContainText(
    /costs an estimated .* (more|less) than/,
  );
  for (const side of ['Plan A', 'Plan B'] as const) {
    await expectBreakdown(region, side, {
      patient: '$1,200 USD',
      insurer: '$300 USD',
      writeoff: '$0 USD',
      fees: '$1,500 USD',
    });
  }
});

test('contractual write-offs remain distinct from patient and insurer payments with exact returned cents', async ({
  page,
}) => {
  const request = syntheticRequest();
  request.planB.procedureFacts['crown-1']!.allowedCents = 79975;
  request.planB.procedureFacts['crown-1']!.contractualWriteoffCents = 20025;
  const result = syntheticResult(request, -20025);
  expect(result.planB.estimate).toMatchObject({
    status: 'estimated',
    totals: {
      patientPaysCents: 99975,
      insurerPaysCents: 30000,
      contractualWriteoffCents: 20025,
      providerChargeCents: 150000,
    },
  });
  const region = await showResults(page, {
    request,
    state: { status: 'ready', result },
  });
  await expectBreakdown(region, 'Plan A', {
    patient: '$1,200 USD',
    insurer: '$300 USD',
    writeoff: '$0 USD',
    fees: '$1,500 USD',
  });
  const b = await expectBreakdown(region, 'Plan B', {
    patient: '$999.75 USD',
    insurer: '$300 USD',
    writeoff: '$200.25 USD',
    fees: '$1,500 USD',
  });
  await expect(b.locator('.comparison-cost-segment.writeoff')).toBeVisible();
  await expect(b).toContainText(
    'A contractual write-off is a fee reduction. It is not paid by you or your insurer.',
  );
  await expect(region).toContainText(
    'Fictional Beta costs an estimated $200.25 less than Fictional Alpha for this treatment.',
  );
  await expect(b).not.toContainText('%');
});

for (const zero of ['patient', 'insurer', 'all'] as const) {
  test(`known zero ${zero} amounts stay zero without misleading or invalid bar geometry`, async ({
    page,
  }) => {
    const request = syntheticRequest();
    for (const plan of [request.planA, request.planB]) {
      if (zero === 'patient') {
        plan.policy!.insurerRateBpsByCategory = { basic: 10000, major: 10000 };
        Object.assign(plan.planYears['py-2026']!, {
          annualDeductibleCents: 0,
          deductibleAlreadyMetCents: 0,
          annualMaximumCents: 200000,
          insurerAlreadyPaidCents: 0,
        });
      } else if (zero === 'insurer') {
        plan.planYears['py-2026']!.insurerAlreadyPaidCents = 80000;
      } else {
        for (const procedure of request.treatment.procedures) {
          procedure.providerChargeCents = 0;
          plan.procedureFacts[procedure.id]!.allowedCents = 0;
        }
      }
    }
    const region = await showResults(page, {
      request,
      state: { status: 'ready', result: syntheticResult(request) },
    });
    for (const side of ['Plan A', 'Plan B'] as const) {
      const figure = await expectBreakdown(region, side, {
        patient: zero === 'insurer' ? '$1,500 USD' : '$0 USD',
        insurer: zero === 'patient' ? '$1,500 USD' : '$0 USD',
        writeoff: '$0 USD',
        fees: zero === 'all' ? '$0 USD' : '$1,500 USD',
      });
      const zeroSegments =
        zero === 'all'
          ? figure.locator('.comparison-cost-segment')
          : figure.locator(`.comparison-cost-segment.${zero}`);
      await expect(zeroSegments).toHaveCount(zero === 'all' ? 3 : 1);
      for (const segment of await zeroSegments.all()) {
        expect(
          await segment.evaluate(
            (element) => element.getBoundingClientRect().width,
          ),
        ).toBe(0);
      }
      if (zero === 'all') {
        await expect(figure).toContainText(
          'No treatment charges in this estimate.',
        );
        await expect(figure.locator('.comparison-cost-track')).toBeVisible();
      }
      await expect(figure).not.toContainText(/NaN|Infinity|%/);
    }
    await expect(region).toContainText(
      'Both plans have the same estimated patient cost.',
    );
    await page.emulateMedia({ forcedColors: 'active' });
    for (const segment of await region
      .locator('.comparison-cost-segment.is-zero')
      .all()) {
      expect(
        await segment.evaluate(
          (element) => element.getBoundingClientRect().width,
        ),
      ).toBe(0);
    }
  });
}

test('a positive returned difference identifies the higher patient cost', async ({
  page,
}) => {
  const request = syntheticRequest();
  request.planA.planYears['py-2026']!.insurerAlreadyPaidCents = 0;
  const region = await showResults(page, {
    request,
    state: { status: 'ready', result: syntheticResult(request, 50000) },
  });
  await expect(region).toContainText(
    'Fictional Beta costs an estimated $500 more than Fictional Alpha for this treatment.',
  );
});

test('a missing plan fact does not hide the complete other plan or invent a cost difference', async ({
  page,
}) => {
  const request = syntheticRequest();
  request.planB.procedureFacts['crown-1']!.allowedCents = null;
  const region = await showResults(page, {
    request,
    state: { status: 'ready', result: syntheticResult(request, null) },
  });
  const a = region.getByRole('region', {
    name: 'Plan A · Fictional Alpha',
    exact: true,
  });
  const b = region.getByRole('region', {
    name: 'Plan B · Fictional Beta',
    exact: true,
  });
  await expect(a).toContainText('Complete estimate');
  await expect(breakdown(region, 'Plan A')).toBeVisible();
  await expect(breakdown(region, 'Plan B')).toHaveCount(0);
  await expect(b).toContainText('Needs information');
  await expect(b).toContainText('Crown · Plan allowed amount');
  await expect(b).toContainText(
    'Unknown values have not been treated as zero.',
  );
  await expect(
    b.getByText('Estimated patient cost', { exact: true }),
  ).toHaveCount(0);
  await expect(region).toContainText(
    'A patient-cost difference is unavailable until both plans have complete, comparable estimates.',
  );
});

test('unsupported plan rules remain visible without a misleading difference', async ({
  page,
}) => {
  const request = syntheticRequest();
  request.planB.policy!.waitingPeriods = [
    {
      id: 'fictional-wait',
      description: 'Fictional waiting period',
      categoryIds: ['major'],
    },
  ];
  const region = await showResults(page, {
    request,
    state: { status: 'ready', result: syntheticResult(request, null) },
  });
  const b = region.getByRole('region', {
    name: 'Plan B · Fictional Beta',
    exact: true,
  });
  await expect(b).toContainText('Unsupported plan rules');
  await expect(breakdown(region, 'Plan A')).toBeVisible();
  await expect(breakdown(region, 'Plan B')).toHaveCount(0);
  await expect(b).toContainText('Waiting periods');
  await expect(
    b.getByText('Estimated patient cost', { exact: true }),
  ).toHaveCount(0);
  await expect(region).toContainText(
    'A patient-cost difference is unavailable',
  );
});

test('conditional results show assumptions next to the returned cost difference', async ({
  page,
}) => {
  const request = syntheticRequest();
  request.treatment.schedule.find(
    (entry) => entry.procedureId === 'crown-1',
  )!.date = '2027-01-01';
  const region = await showResults(page, {
    request,
    state: { status: 'ready', result: syntheticResult(request) },
  });
  await expect(
    region.getByText('Conditional estimate', { exact: true }),
  ).toHaveCount(2);
  await expect(region).toContainText(
    'This difference is conditional on the assumptions shown for each plan.',
  );
  await expect(region).toContainText(
    'Confirm the plan terms before relying on these figures.',
  );
  await expect(breakdown(region, 'Plan A')).toBeVisible();
  await expect(breakdown(region, 'Plan B')).toBeVisible();
});

for (const changed of ['revision', 'plan', 'treatment', 'schedule'] as const) {
  test(`results for another ${changed} are withheld until refreshed`, async ({
    page,
  }) => {
    const request = syntheticRequest();
    const result = syntheticResult(request);
    if (changed === 'revision') request.expectedRevision += 1;
    if (changed === 'plan') request.planB.planId = 'different-synthetic-plan';
    if (changed === 'treatment')
      request.treatment.procedures[0]!.providerChargeCents = 26000;
    if (changed === 'schedule')
      request.treatment.schedule.find(
        (entry) => entry.procedureId === 'crown-1',
      )!.date = '2027-01-01';
    const region = await showResults(page, {
      request,
      state: { status: 'ready', result },
    });
    await expect(region).toContainText(
      'These results do not match the current case, plans, treatment or schedule.',
    );
    await expect(
      region.getByText('Estimated patient cost', { exact: true }),
    ).toHaveCount(0);
    await expect(region.getByRole('figure')).toHaveCount(0);
    await expect(
      region.getByRole('heading', {
        name: 'Estimated patient-cost difference',
      }),
    ).toHaveCount(0);
  });
}

test('malformed returned results are withheld instead of rendered as estimates', async ({
  page,
}) => {
  const request = syntheticRequest();
  const result = syntheticResult(request);
  result.planB.estimate.caseRevision += 1;
  const region = await showResults(page, {
    request,
    state: { status: 'ready', result },
  });
  await expect(region).toContainText(
    'These comparison results could not be validated.',
  );
  await expect(
    region.getByText('Estimated patient cost', { exact: true }),
  ).toHaveCount(0);
  await expect(region.getByRole('figure')).toHaveCount(0);
});

test('inconsistent returned totals retain their text but suppress misleading cost geometry', async ({
  page,
}) => {
  const request = syntheticRequest();
  const result = syntheticResult(request);
  if (result.planB.estimate.status !== 'estimated')
    throw new Error('The synthetic comparison must be complete.');
  result.planB.estimate.totals.providerChargeCents = 160000;
  expect(PlanComparisonResultSchema.safeParse(result).success).toBe(true);
  const region = await showResults(page, {
    request,
    state: { status: 'ready', result },
  });
  const a = breakdown(region, 'Plan A');
  const b = breakdown(region, 'Plan B');
  await expect(a.locator('.comparison-cost-track')).toBeVisible();
  await expect(b).toContainText(
    'The returned amounts do not form a consistent cost breakdown.',
  );
  await expect(b.locator('.comparison-cost-track')).toHaveCount(0);
  await expect(b.getByRole('definition')).toHaveText([
    '$1,200 USD',
    '$300 USD',
    '$0 USD',
    '$1,600 USD',
  ]);
  await expect(region).not.toContainText(/NaN|Infinity/);
});

for (const malformed of [
  'currency',
  'fractional cents',
  'negative amount',
] as const) {
  test(`malformed ${malformed} do not reach the cost visualization`, async ({
    page,
  }) => {
    const request = syntheticRequest();
    const result = syntheticResult(request);
    if (malformed === 'currency') Object.assign(result, { currency: 'EUR' });
    if (result.planB.estimate.status !== 'estimated')
      throw new Error('The synthetic comparison must be complete.');
    if (malformed === 'fractional cents')
      result.planB.estimate.totals.patientPaysCents = 120000.5;
    if (malformed === 'negative amount')
      result.planB.estimate.totals.insurerPaysCents = -1;
    const region = await showResults(page, {
      request,
      state: { status: 'ready', result },
    });
    await expect(region).toContainText(
      'These comparison results could not be validated.',
    );
    await expect(region.getByRole('figure')).toHaveCount(0);
    await expect(
      region.getByText('Estimated patient cost', { exact: true }),
    ).toHaveCount(0);
  });
}

test('loading and retryable error states expose status and retry without retaining amounts', async ({
  page,
}) => {
  const region = await showResults(page, {
    request: null,
    state: { status: 'loading' },
  });
  await expect(
    region.getByRole('status').filter({ hasText: 'Comparing the two plans…' }),
  ).toHaveAttribute('aria-busy', 'true');
  await expect(
    region.getByText('Estimated patient cost', { exact: true }),
  ).toHaveCount(0);
  await expect(region.getByRole('figure')).toHaveCount(0);
  await page.evaluate(() =>
    window.renderPlanComparisonTest({
      request: null,
      state: {
        status: 'error',
        message: 'The service is busy. Try again.',
        requestId: 'synthetic-request',
        retryable: true,
      },
    }),
  );
  await expect(region.getByRole('alert')).toContainText(
    'The comparison could not be loaded',
  );
  await expect(region.getByRole('figure')).toHaveCount(0);
  await expect(region).toContainText('Reference: synthetic-request');
  await region
    .getByRole('button', { name: 'Retry comparison', exact: true })
    .click();
  expect(await page.evaluate(() => window.comparisonTestRetryCount)).toBe(1);
  await page.evaluate(() =>
    window.renderPlanComparisonTest({
      request: null,
      state: {
        status: 'error',
        message: 'Review the entered facts.',
        retryable: false,
      },
    }),
  );
  await expect(region.getByRole('alert')).toContainText(
    'Review the entered facts.',
  );
  await expect(
    region.getByRole('button', { name: 'Retry comparison', exact: true }),
  ).toHaveCount(0);
});

for (const width of [360, 1440]) {
  test(`comparison form and supplied results are accessible without page overflow at ${width}px`, async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width, height: 900 });
    await openForm(page);
    const a = planGroup(page, 'Plan A');
    await a.getByLabel('Plan name', { exact: true }).focus();
    await page.keyboard.type('Fictional keyboard plan');
    await expect(a.getByLabel('Plan name', { exact: true })).toHaveValue(
      'Fictional keyboard plan',
    );
    await page.keyboard.press('Tab');
    expect(await page.evaluate(() => document.activeElement?.tagName)).not.toBe(
      'BODY',
    );
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);

    const request = syntheticRequest();
    const region = await showResults(page, {
      request,
      state: { status: 'ready', result: syntheticResult(request) },
    });
    await expectBreakdown(region, 'Plan A', {
      patient: '$1,200 USD',
      insurer: '$300 USD',
      writeoff: '$0 USD',
      fees: '$1,500 USD',
    });
    await expectBreakdown(region, 'Plan B', {
      patient: '$1,200 USD',
      insurer: '$300 USD',
      writeoff: '$0 USD',
      fees: '$1,500 USD',
    });
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  });
}
