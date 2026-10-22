import { expect, test, type Locator, type Page } from '@playwright/test';
import { comparePlans } from '@actionbridge/benefits-engine';
import {
  PlanComparisonRequestSchema,
  type DentalCase,
  type PlanComparisonRequest,
} from '@actionbridge/contracts';
import { mockBackend, type MockApi } from './mock-api';

/** Synthetic browser integration tests. API calculations run in the Node test process. */
const comparisonRoute = /\/v1\/cases\/[^/]+\/plan-comparison$/;
const group = (page: Page, side: 'Plan A' | 'Plan B') =>
  page.getByRole('group', { name: side, exact: true });
const results = (page: Page) =>
  page.getByRole('region', { name: 'Plan comparison results', exact: true });
const submit = (page: Page) =>
  page.getByRole('button', { name: 'Compare plans', exact: true });
const comparisons = (api: MockApi) =>
  api.requests.filter((request) => request.path.endsWith('/plan-comparison'));

async function openComparison(page: Page) {
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
  return api;
}

async function namePlans(page: Page) {
  await group(page, 'Plan A')
    .getByLabel('Plan name', { exact: true })
    .fill('Fictional Alpha');
  await group(page, 'Plan B')
    .getByLabel('Plan name', { exact: true })
    .fill('Fictional Beta');
}

async function openProcedure(plan: Locator, label: string) {
  const summary = plan.locator('summary').filter({ hasText: label }).filter({
    hasNotText: 'Procedure insurance facts',
  });
  const exact = summary.filter({ hasText: new RegExp(`^${label}$`) });
  if (
    !(await exact.evaluate(
      (element) => (element.parentElement as HTMLDetailsElement).open,
    ))
  )
    await exact.click();
}

async function completePlans(page: Page) {
  await group(page, 'Plan A')
    .getByRole('button', { name: 'Use current plan', exact: true })
    .click();
  const b = group(page, 'Plan B');
  await b.getByLabel('Plan name', { exact: true }).fill('Fictional Beta');
  for (const [label, dollars] of [
    ['Filling one', '250'],
    ['Filling two', '250'],
    ['Crown', '1000'],
  ] as const) {
    await openProcedure(b, label);
    await b
      .getByLabel(`${label} · Benefit category`, { exact: true })
      .selectOption('basic');
    await b
      .getByLabel(`${label} · Provider network`, { exact: true })
      .selectOption('out');
    await b
      .getByLabel(`${label} · Allowed amount`, { exact: true })
      .fill(dollars);
    await b
      .getByLabel(`${label} · Dentist write-off`, { exact: true })
      .fill('0');
  }
  await b
    .getByLabel('Deductible before coinsurance', { exact: true })
    .selectOption('true');
  await b
    .getByLabel('All listed services covered', { exact: true })
    .selectOption('true');
  await b
    .getByLabel('Insurer payment rounding', { exact: true })
    .selectOption('half_up_to_cent');
  await b.getByLabel('basic services · Plan pays', { exact: true }).fill('80');
  await b
    .getByLabel('basic services · Deductible applies', { exact: true })
    .selectOption('true');
  await b
    .getByLabel('basic services · Annual maximum applies', { exact: true })
    .selectOption('true');
  for (const label of [
    'Waiting periods',
    'Exclusions',
    'Frequency restrictions',
  ])
    await b.getByLabel(label, { exact: true }).selectOption('none');
  await b
    .getByRole('button', { name: 'Add benefit year', exact: true })
    .click();
  await b.getByLabel('Benefit year starts', { exact: true }).fill('2026-01-01');
  await b.getByLabel('Benefit year ends', { exact: true }).fill('2026-12-31');
  for (const [label, dollars] of [
    ['Annual insurer maximum', '2000'],
    ['Annual deductible', '0'],
    ['Insurer already paid', '0'],
    ['Deductible already met', '0'],
  ] as const)
    await b.getByLabel(label, { exact: true }).fill(dollars);
}

function sourceTreatment(record: DentalCase) {
  return {
    procedures: record.procedures.map((procedure) => {
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
    schedule: record.procedures.map((procedure) => ({
      procedureId: procedure.id,
      date: procedure.proposedDate ?? procedure.dentistEarliestDate,
    })),
  };
}

function successfulResult(request: PlanComparisonRequest) {
  const result = comparePlans(request);
  if ('status' in result)
    throw new Error('Contradictory synthetic comparison test input.');
  return result;
}

test('sends the selected case revision and independent plan facts with the Cognito bearer token', async ({
  page,
}) => {
  const api = await openComparison(page);
  const source = structuredClone([...api.cases.values()][0]!);
  const previousRequests = api.requests.length;
  await group(page, 'Plan A')
    .getByRole('button', { name: 'Use current plan', exact: true })
    .click();
  const b = group(page, 'Plan B');
  await b.getByLabel('Plan name', { exact: true }).fill('Fictional Beta');
  await openProcedure(b, 'Crown');
  await b
    .getByLabel('Crown · Benefit category', { exact: true })
    .selectOption('basic');
  await b
    .getByLabel('Crown · Provider network', { exact: true })
    .selectOption('out');
  await b.getByLabel('Crown · Allowed amount', { exact: true }).fill('800.25');
  await b.getByLabel('Crown · Dentist write-off', { exact: true }).fill('100');
  await submit(page).click();
  await expect(
    results(page).getByText('Needs information', { exact: true }),
  ).toBeVisible();

  expect(comparisons(api)).toHaveLength(1);
  const sent = comparisons(api)[0]!;
  const body = PlanComparisonRequestSchema.parse(sent.body);
  expect(sent.method).toBe('POST');
  expect(sent.path).toBe(`/v1/cases/${source.caseId}/plan-comparison`);
  expect(sent.headers.authorization).toBe('Bearer test-access');
  expect(body.caseId).toBe(source.caseId);
  expect(body.expectedRevision).toBe(source.caseRevision);
  expect(body.currency).toBe(source.currency);
  expect(body.treatment.procedures).toEqual(sourceTreatment(source).procedures);
  expect(body.treatment.schedule).toEqual(sourceTreatment(source).schedule);
  expect(body.planA.procedureFacts['crown-1']).toEqual({
    category: 'major',
    network: 'in',
    allowedCents: 100000,
    contractualWriteoffCents: 0,
  });
  expect(body.planB.procedureFacts['crown-1']).toEqual({
    category: 'basic',
    network: 'out',
    allowedCents: 80025,
    contractualWriteoffCents: 10000,
  });
  expect(body.planB.procedureFacts['filling-1']).toEqual({
    category: null,
    network: 'unknown',
    allowedCents: null,
    contractualWriteoffCents: null,
  });
  expect(body.planB.planYears).toEqual({});
  expect(body.planB.policy?.allServicesCovered).toBeNull();
  expect(body.planA.planId).not.toBe(body.planB.planId);
  await expect(
    results(page).getByText(/A patient-cost difference is unavailable/),
  ).toBeVisible();
  expect([...api.cases.values()]).toEqual([source]);
  expect([...api.strategies.values()].flat()).toEqual([]);
  expect(
    api.requests
      .slice(previousRequests)
      .map(({ method, path }) => ({ method, path })),
  ).toEqual([{ method: 'POST', path: sent.path }]);
});

test('renders both real engine estimates and their returned patient-cost difference', async ({
  page,
}) => {
  const api = await openComparison(page);
  await completePlans(page);
  await submit(page).click();
  const output = results(page);
  await expect(
    output.getByText('Complete estimate', { exact: true }),
  ).toHaveCount(2);
  const a = output.getByRole('region', {
    name: 'Plan A · Current plan',
    exact: true,
  });
  const b = output.getByRole('region', {
    name: 'Plan B · Fictional Beta',
    exact: true,
  });
  await expect(a).toContainText('$1,200');
  await expect(b).toContainText('$300');
  await expect(output).toContainText(
    'Fictional Beta costs an estimated $900 less than Current plan',
  );
  await expect(output).toContainText('Assumptions and conditions');
  const returned = successfulResult(
    PlanComparisonRequestSchema.parse(comparisons(api)[0]!.body),
  );
  expect(returned.planBMinusPlanACents).toBe(-90000);
  expect(returned.planB.estimate.status).toBe('estimated');

  // Editing the same plan IDs invalidates figures immediately, before the next request.
  await group(page, 'Plan B')
    .getByLabel('Plan name', { exact: true })
    .fill('Revised Beta');
  await expect(
    output.getByText('Complete estimate', { exact: true }),
  ).toHaveCount(0);
  await expect(output).not.toContainText('$900');
});

test('preserves an unsupported plan independently and withholds the cost difference', async ({
  page,
}) => {
  await openComparison(page);
  await completePlans(page);
  await group(page, 'Plan B')
    .getByLabel('Waiting periods', { exact: true })
    .selectOption('present');
  await submit(page).click();
  const output = results(page);
  await expect(
    output.getByText('Complete estimate', { exact: true }),
  ).toHaveCount(1);
  await expect(
    output.getByText('Unsupported plan rules', { exact: true }),
  ).toBeVisible();
  await expect(output).toContainText(
    'A patient-cost difference is unavailable',
  );
  await expect(output).not.toContainText('costs an estimated');
});

test('blocks duplicate submits and ignores an old response after the draft changes', async ({
  page,
}) => {
  await openComparison(page);
  await completePlans(page);
  let release: (() => void) | undefined;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  let requests = 0;
  await page.route(comparisonRoute, async (route) => {
    requests += 1;
    const body = PlanComparisonRequestSchema.parse(
      route.request().postDataJSON(),
    );
    if (requests === 1) await held;
    await route.fulfill({ json: successfulResult(body) });
  });
  await page
    .getByRole('form', { name: 'Insurance plan comparison', exact: true })
    .evaluate((form) => {
      (form as HTMLFormElement).requestSubmit();
      (form as HTMLFormElement).requestSubmit();
    });
  await expect(
    results(page).getByText('Comparing the two plans…', { exact: true }),
  ).toBeVisible();
  await expect(submit(page)).toBeDisabled();
  expect(requests).toBe(1);
  // Keep the same plan IDs and labels: only request generation can identify this old response.
  await group(page, 'Plan B')
    .getByLabel('basic services · Plan pays', { exact: true })
    .fill('50');
  await expect(
    results(page).getByText('Comparing the two plans…', { exact: true }),
  ).toHaveCount(0);
  await expect(submit(page)).toBeEnabled();
  await submit(page).click();
  const beta = results(page).getByRole('region', {
    name: 'Plan B · Fictional Beta',
    exact: true,
  });
  await expect(beta).toContainText('$750');
  const oldResponse = page.waitForResponse(
    (response) =>
      comparisonRoute.test(response.url()) &&
      response.request().postDataJSON().planB.policy.insurerRateBpsByCategory
        .basic === 8000,
  );
  release!();
  await (await oldResponse).finished();
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  );
  await expect(beta).toContainText('$750');
  await expect(beta).not.toContainText('$300');
  expect(requests).toBe(2);
});

for (const scenario of [
  { status: 400, code: 'BAD_REQUEST' },
  { status: 422, code: 'INCONSISTENT_INPUT' },
] as const) {
  test(`${scenario.status} validation errors show the server field issue without retrying`, async ({
    page,
  }) => {
    await openComparison(page);
    await namePlans(page);
    let requests = 0;
    await page.route(comparisonRoute, (route) => {
      requests += 1;
      return route.fulfill({
        status: scenario.status,
        json: {
          error: {
            code: scenario.code,
            message: 'Review the independently entered plan facts.',
            retryable: false,
            requestId: 'req-validation',
            issues: [
              {
                fieldPath: 'planB.procedureFacts.crown-1.allowedCents',
                code: 'INVALID_ALLOWED_AMOUNT',
                message: 'The allowed amount needs review for this plan.',
              },
              {
                fieldPath: null,
                code: 'INVALID_COMPARISON',
                message: 'Review the complete comparison request.',
              },
            ],
          },
        },
      });
    });
    await submit(page).click();
    await expect(results(page)).toContainText(
      'The allowed amount needs review for this plan.',
    );
    await expect(results(page)).toContainText(
      'Review the complete comparison request.',
    );
    await expect(results(page)).toContainText('req-validation');
    await expect(
      results(page).getByRole('button', { name: 'Retry comparison' }),
    ).toHaveCount(0);
    expect(requests).toBe(1);
    await expect(
      group(page, 'Plan B').getByLabel('Plan name', { exact: true }),
    ).toHaveValue('Fictional Beta');
  });
}

test('a forbidden comparison shows a permission error while preserving the draft', async ({
  page,
}) => {
  await openComparison(page);
  await namePlans(page);
  await page.route(comparisonRoute, (route) =>
    route.fulfill({
      status: 403,
      json: {
        error: {
          code: 'FORBIDDEN',
          message: 'Comparison is forbidden.',
          retryable: false,
          requestId: 'req-forbidden',
        },
      },
    }),
  );
  await submit(page).click();
  await expect(results(page)).toContainText(/permission|access|allowed/i);
  await expect(results(page)).toContainText('req-forbidden');
  await expect(
    results(page).getByRole('button', { name: 'Retry comparison' }),
  ).toHaveCount(0);
  await expect(
    group(page, 'Plan B').getByLabel('Plan name', { exact: true }),
  ).toHaveValue('Fictional Beta');
  await expect(page).toHaveURL(/\/plan-comparison$/);
});

for (const scenario of [
  { status: 404, code: 'NOT_FOUND' },
  { status: 409, code: 'REVISION_CONFLICT' },
] as const) {
  test(`${scenario.status} requires reloading the treatment before another comparison`, async ({
    page,
  }) => {
    const api = await openComparison(page);
    const record = [...api.cases.values()][0]!;
    await namePlans(page);
    let calls = 0;
    await page.route(comparisonRoute, (route) => {
      calls += 1;
      return route.fulfill({
        status: scenario.status,
        json: {
          error: {
            code: scenario.code,
            message:
              scenario.status === 409
                ? 'This case changed.'
                : 'Case not found.',
            retryable: false,
            requestId: 'req-reload',
          },
        },
      });
    });
    if (scenario.status === 409) {
      api.cases.set(record.caseId, {
        ...record,
        caseRevision: record.caseRevision + 1,
      });
    } else {
      api.cases.delete(record.caseId);
    }
    await submit(page).click();
    await expect(results(page)).toContainText('req-reload');
    await expect(submit(page)).toBeDisabled();
    await group(page, 'Plan B')
      .getByLabel('Plan name', { exact: true })
      .fill('Edited after conflict');
    await expect(submit(page)).toBeDisabled();
    await page
      .getByRole('button', { name: 'Reload treatment', exact: true })
      .click();
    if (scenario.status === 409) {
      await expect(
        group(page, 'Plan A').getByLabel('Plan name', { exact: true }),
      ).toHaveValue('');
      await expect(
        page.getByText(`Case version ${record.caseRevision + 1}`, {
          exact: true,
        }),
      ).toBeVisible();
      await expect(submit(page)).toBeEnabled();
    } else {
      await expect(
        page.getByText(/Case not found|could not be found/i).first(),
      ).toBeVisible();
      await expect(submit(page)).toHaveCount(0);
    }
    expect(calls).toBe(1);
  });
}

test('an unauthorized response ends the existing Cognito session and returns to sign-in', async ({
  page,
}) => {
  await openComparison(page);
  await namePlans(page);
  await page.route(comparisonRoute, (route) =>
    route.fulfill({
      status: 401,
      json: {
        error: {
          code: 'UNAUTHENTICATED',
          message: 'Expired.',
          retryable: false,
          requestId: 'req-expired',
        },
      },
    }),
  );
  await submit(page).click();
  await expect(page).toHaveURL(/\/sign-in$/);
  await expect(page.getByLabel('Email', { exact: true })).toBeVisible();
  expect(
    await page.evaluate(() =>
      sessionStorage.getItem('actionbridge.web.session.v1'),
    ),
  ).toBeNull();
});

for (const failure of ['network', 'server', 'invalid-response'] as const) {
  test(`${failure} failures never show fallback estimates or auto-retry a comparison`, async ({
    page,
  }) => {
    const api = await openComparison(page);
    await namePlans(page);
    if (failure === 'server') {
      await completePlans(page);
      await submit(page).click();
      await expect(
        results(page).getByText('Complete estimate', { exact: true }),
      ).toHaveCount(2);
    }
    let requests = 0;
    await page.route(comparisonRoute, (route) => {
      requests += 1;
      if (requests > 1) return route.fallback();
      if (failure === 'network') return route.abort('failed');
      if (failure === 'server')
        return route.fulfill({
          status: 500,
          json: {
            error: {
              code: 'INTERNAL',
              message: 'Comparison is temporarily unavailable.',
              retryable: true,
              requestId: 'req-server',
            },
          },
        });
      return route.fulfill({ json: { inventedPatientAmount: 100 } });
    });
    await submit(page).click();
    await expect(results(page)).toContainText(
      'The comparison could not be loaded',
    );
    await expect(
      results(page).getByText('Complete estimate', { exact: true }),
    ).toHaveCount(0);
    await expect(results(page)).not.toContainText('costs an estimated');
    expect(requests).toBe(1);
    await expect(
      group(page, 'Plan B').getByLabel('Plan name', { exact: true }),
    ).toHaveValue('Fictional Beta');
    if (failure !== 'invalid-response') {
      await results(page)
        .getByRole('button', { name: 'Retry comparison', exact: true })
        .click();
      await expect(
        results(page).getByText(
          failure === 'server' ? 'Complete estimate' : 'Needs information',
          { exact: true },
        ),
      ).toHaveCount(2);
      expect(requests).toBe(2);
      expect(comparisons(api)).toHaveLength(failure === 'server' ? 2 : 1);
    }
  });
}

test('comparison uses the existing refreshed Cognito session after a page reload', async ({
  page,
}) => {
  const flows: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('cognito-idp.') && request.postData()) {
      const body = request.postDataJSON() as { AuthFlow?: string };
      if (body.AuthFlow) flows.push(body.AuthFlow);
    }
  });
  const api = await openComparison(page);
  await page.reload();
  await expect(
    group(page, 'Plan A').getByLabel('Plan name', { exact: true }),
  ).toBeVisible();
  await namePlans(page);
  await submit(page).click();
  await expect(
    results(page).getByText('Needs information', { exact: true }),
  ).toHaveCount(2);
  expect(flows).toContain('USER_PASSWORD_AUTH');
  expect(flows).toContain('REFRESH_TOKEN_AUTH');
  expect(comparisons(api)[0]!.headers.authorization).toBe('Bearer test-access');
});
