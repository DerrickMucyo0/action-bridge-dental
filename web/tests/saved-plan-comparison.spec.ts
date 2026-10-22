import { expect, test, type Page } from '@playwright/test';
import { comparePlans } from '@actionbridge/benefits-engine';
import { SavePlanComparisonRequestSchema } from '@actionbridge/contracts';
import { mockBackend, type MockApi } from './mock-api';

const savedRoute =
  /\/v1\/cases\/[^/]+\/plan-comparisons(?:\/[^/?]+)?(?:\?.*)?$/;
const group = (page: Page, side: 'Plan A' | 'Plan B') =>
  page.getByRole('group', { name: side, exact: true });
const panel = (page: Page) =>
  page.getByRole('region', {
    name: 'Saved insurance comparisons',
    exact: true,
  });
const results = (page: Page) =>
  page.getByRole('region', { name: 'Plan comparison results', exact: true });
const saves = (api: MockApi) =>
  api.requests.filter(
    (request) =>
      request.method === 'POST' && request.path.endsWith('/plan-comparisons'),
  );

async function open(page: Page) {
  const api = await mockBackend(page);
  await page.goto('/sign-in');
  await page.getByLabel('Email', { exact: true }).fill('jordan@example.com');
  await page.getByLabel('Password', { exact: true }).fill('A-long-password-1');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('button', { name: 'Try a sample case' }).click();
  await page
    .getByRole('button', { name: 'Compare insurance plans', exact: true })
    .click();
  await expect(
    panel(page).getByText('No saved comparisons for this treatment version.', {
      exact: true,
    }),
  ).toBeVisible();
  return api;
}

async function compareUnknowns(page: Page) {
  await group(page, 'Plan A')
    .getByLabel('Plan name', { exact: true })
    .fill('Fictional Alpha');
  await group(page, 'Plan B')
    .getByLabel('Plan name', { exact: true })
    .fill('Fictional Beta');
  await page
    .getByRole('button', { name: 'Compare plans', exact: true })
    .click();
  await expect(
    results(page).getByText('Needs information', { exact: true }),
  ).toHaveCount(2);
}

async function complete(page: Page) {
  await group(page, 'Plan A')
    .getByRole('button', { name: 'Use current plan', exact: true })
    .click();
  const b = group(page, 'Plan B');
  await b.getByLabel('Plan name', { exact: true }).fill('Fictional Beta');
  for (const [label, amount] of [
    ['Filling one', '250'],
    ['Filling two', '250'],
    ['Crown', '1000'],
  ]) {
    const summary = b
      .locator('summary')
      .filter({ hasText: new RegExp(`^${label}$`) });
    if (
      !(await summary.evaluate(
        (element) => (element.parentElement as HTMLDetailsElement).open,
      ))
    )
      await summary.click();
    await b
      .getByLabel(`${label} · Benefit category`, { exact: true })
      .selectOption('basic');
    await b
      .getByLabel(`${label} · Provider network`, { exact: true })
      .selectOption('out');
    await b
      .getByLabel(`${label} · Allowed amount`, { exact: true })
      .fill(amount!);
    await b
      .getByLabel(`${label} · Dentist write-off`, { exact: true })
      .fill('0');
  }
  for (const label of [
    'Deductible before coinsurance',
    'All listed services covered',
    'basic services · Deductible applies',
    'basic services · Annual maximum applies',
  ])
    await b.getByLabel(label, { exact: true }).selectOption('true');
  await b
    .getByLabel('Insurer payment rounding', { exact: true })
    .selectOption('half_up_to_cent');
  await b.getByLabel('basic services · Plan pays', { exact: true }).fill('80');
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
  for (const [label, amount] of [
    ['Annual insurer maximum', '2000'],
    ['Annual deductible', '0'],
    ['Insurer already paid', '0'],
    ['Deductible already met', '0'],
  ])
    await b.getByLabel(label!, { exact: true }).fill(amount!);
  await page
    .getByRole('button', { name: 'Compare plans', exact: true })
    .click();
  await expect(
    results(page).getByText('Complete estimate', { exact: true }),
  ).toHaveCount(2);
}

async function save(page: Page) {
  await panel(page)
    .getByRole('checkbox', {
      name: 'Save this insurance comparison and my answers in my account.',
      exact: true,
    })
    .check();
  await panel(page)
    .getByRole('button', { name: 'Save comparison', exact: true })
    .click();
}

async function reopen(page: Page) {
  await page.reload();
  await panel(page)
    .getByRole('button', { name: /^Open saved comparison:/ })
    .click();
}

test('saves inputs only with consent, authentication and revision, then reopens independent plans', async ({
  page,
}) => {
  const readUrls: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'GET' && savedRoute.test(request.url()))
      readUrls.push(request.url());
  });
  const api = await open(page);
  const source = structuredClone([...api.cases.values()][0]!);
  await complete(page);
  await expect(
    panel(page).getByRole('button', { name: 'Save comparison', exact: true }),
  ).toBeDisabled();
  await save(page);
  await expect(panel(page)).toContainText('Comparison saved in your account.');
  expect(saves(api)).toHaveLength(1);
  const sent = saves(api)[0]!;
  const body = SavePlanComparisonRequestSchema.parse(sent.body);
  expect(Object.keys(body)).toEqual(['comparison', 'consent']);
  expect('result' in body).toBe(false);
  expect(sent.headers.authorization).toBe('Bearer test-access');
  expect(sent.headers['idempotency-key']).toBeTruthy();
  expect(body.comparison.caseId).toBe(source.caseId);
  expect(body.comparison.expectedRevision).toBe(source.caseRevision);
  expect(body.comparison.planA.procedureFacts['crown-1']!.network).toBe('in');
  expect(body.comparison.planB.procedureFacts['crown-1']!.network).toBe('out');
  expect([...api.cases.values()]).toEqual([source]);
  expect([...api.strategies.values()].flat()).toEqual([]);
  await reopen(page);
  await expect(
    group(page, 'Plan A').getByLabel('Plan name', { exact: true }),
  ).toHaveValue('Current plan');
  await expect(
    group(page, 'Plan B').getByLabel('Plan name', { exact: true }),
  ).toHaveValue('Fictional Beta');
  await expect(
    results(page).getByText('Complete estimate', { exact: true }),
  ).toHaveCount(2);
  await expect(results(page)).toContainText(
    'Fictional Beta costs an estimated $900 less than Current plan',
  );
  expect(
    readUrls.every(
      (url) =>
        new URL(url).searchParams.get('expectedRevision') ===
        String(source.caseRevision),
    ),
  ).toBe(true);
  expect(readUrls.some((url) => /plan-comparisons\/pc-/.test(url))).toBe(true);
  const reads = api.requests.filter(
    (request) =>
      request.method === 'GET' && request.path.includes('/plan-comparisons'),
  );
  expect(
    reads.every(
      (request) => request.headers.authorization === 'Bearer test-access',
    ),
  ).toBe(true);
  await group(page, 'Plan B')
    .getByLabel('Plan name', { exact: true })
    .fill('Edited Beta');
  await expect(
    results(page).getByText('Complete estimate', { exact: true }),
  ).toHaveCount(0);
  await expect(panel(page)).not.toContainText(
    'Comparison saved in your account.',
  );
  await expect(
    panel(page).getByRole('button', { name: 'Save comparison', exact: true }),
  ).toHaveCount(0);
});

for (const unsupported of [false, true]) {
  test(`preserves ${unsupported ? 'unsupported' : 'unknown'} statuses through save and reopen without a cost winner`, async ({
    page,
  }) => {
    const api = await open(page);
    await compareUnknowns(page);
    if (unsupported) {
      await group(page, 'Plan A')
        .getByRole('button', { name: 'Use current plan', exact: true })
        .click();
      await group(page, 'Plan A')
        .getByLabel('Waiting periods', { exact: true })
        .selectOption('present');
      await page
        .getByRole('button', { name: 'Compare plans', exact: true })
        .click();
      await expect(
        results(page).getByText('Unsupported plan rules', { exact: true }),
      ).toBeVisible();
    }
    await save(page);
    await expect(panel(page)).toContainText(
      'Comparison saved in your account.',
    );
    const snapshot = [...api.comparisons.values()][0]![0]!;
    expect(snapshot.result.planA.estimate.status).toBe(
      unsupported ? 'unsupported' : 'needs_information',
    );
    expect(snapshot.result.planB.estimate.status).toBe('needs_information');
    expect(snapshot.result.planBMinusPlanACents).toBeNull();
    expect(
      snapshot.request.planB.procedureFacts['crown-1']!.allowedCents,
    ).toBeNull();
    await reopen(page);
    await expect(
      results(page).getByText(
        unsupported ? 'Unsupported plan rules' : 'Needs information',
        { exact: true },
      ),
    ).toHaveCount(unsupported ? 1 : 2);
    await expect(results(page)).toContainText(
      'A patient-cost difference is unavailable',
    );
    await expect(results(page)).not.toContainText('costs an estimated');
  });
}

test('retries a lost save response with the same idempotency key and creates one snapshot', async ({
  page,
}) => {
  const api = await open(page);
  await compareUnknowns(page);
  api.failNextComparisonSave = true;
  await save(page);
  await expect(panel(page)).toContainText(
    'The save response was interrupted. Retry safely.',
  );
  await panel(page)
    .getByRole('button', { name: 'Retry saving comparison', exact: true })
    .click();
  await expect(panel(page)).toContainText('Comparison saved in your account.');
  expect(saves(api)).toHaveLength(2);
  expect(saves(api)[0]!.headers['idempotency-key']).toBe(
    saves(api)[1]!.headers['idempotency-key'],
  );
  expect(saves(api)[0]!.body).toEqual(saves(api)[1]!.body);
  expect([...api.comparisons.values()].flat()).toHaveLength(1);
});

test('rejects a saved response with matching names and IDs but altered plan facts', async ({
  page,
}) => {
  await open(page);
  await compareUnknowns(page);
  await page.route(savedRoute, (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    const { comparison } = SavePlanComparisonRequestSchema.parse(
      route.request().postDataJSON(),
    );
    comparison.planB.procedureFacts['crown-1']!.allowedCents = 10000;
    const result = comparePlans(comparison);
    if ('status' in result)
      throw new Error('Synthetic altered input must remain contract-valid.');
    return route.fulfill({
      status: 201,
      json: {
        comparison: {
          comparisonId: 'pc-altered-facts',
          caseId: comparison.caseId,
          caseRevision: comparison.expectedRevision,
          request: comparison,
          result,
          savedAt: new Date().toISOString(),
        },
        replayed: false,
      },
    });
  });
  await save(page);
  await expect(panel(page)).toContainText(
    'The saved comparison does not match your submitted plans.',
  );
  await expect(panel(page)).not.toContainText(
    'Comparison saved in your account.',
  );
  await expect(
    panel(page).getByRole('button', { name: 'Save comparison', exact: true }),
  ).toBeDisabled();
});

test('blocks duplicate saves and ignores a late save response after editing', async ({
  page,
}) => {
  await open(page);
  await compareUnknowns(page);
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  let count = 0;
  await page.route(savedRoute, async (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    count++;
    await held;
    return route.fallback();
  });
  await save(page);
  await expect(
    panel(page).getByRole('button', { name: 'Save comparison', exact: true }),
  ).toBeDisabled();
  expect(count).toBe(1);
  await group(page, 'Plan B')
    .getByLabel('Plan name', { exact: true })
    .fill('Edited while saving');
  const response = page.waitForResponse(
    (value) =>
      savedRoute.test(value.url()) && value.request().method() === 'POST',
  );
  release();
  await (await response).finished();
  await expect(panel(page)).not.toContainText(
    'Comparison saved in your account.',
  );
  await expect(
    group(page, 'Plan B').getByLabel('Plan name', { exact: true }),
  ).toHaveValue('Edited while saving');
  await expect(
    results(page).getByText('Needs information', { exact: true }),
  ).toHaveCount(0);
});

test('a stale save requires treatment reload and never writes a snapshot', async ({
  page,
}) => {
  const api = await open(page);
  await complete(page);
  const source = [...api.cases.values()][0]!;
  api.cases.set(source.caseId, {
    ...source,
    caseRevision: source.caseRevision + 1,
  });
  await save(page);
  await expect(panel(page)).toContainText(
    'The treatment version or access changed.',
  );
  await expect(
    results(page).getByText('Complete estimate', { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole('button', { name: 'Compare plans', exact: true }),
  ).toBeDisabled();
  expect([...api.comparisons.values()].flat()).toEqual([]);
  await panel(page)
    .getByRole('button', { name: 'Reload treatment', exact: true })
    .click();
  await expect(
    group(page, 'Plan B').getByLabel('Plan name', { exact: true }),
  ).toHaveValue('');
  await expect(
    page.getByText(`Case version ${source.caseRevision + 1}`, { exact: true }),
  ).toBeVisible();
});

test('a saved comparison arriving after a draft edit cannot replace the new inputs', async ({
  page,
}) => {
  await open(page);
  await compareUnknowns(page);
  await save(page);
  await expect(panel(page)).toContainText('Comparison saved in your account.');
  await page.reload();
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(savedRoute, async (route) => {
    if (!/\/plan-comparisons\/[^/?]+/.test(route.request().url()))
      return route.fallback();
    await held;
    return route.fallback();
  });
  await panel(page)
    .getByRole('button', { name: /^Open saved comparison:/ })
    .click();
  await group(page, 'Plan B')
    .getByLabel('Plan name', { exact: true })
    .fill('New draft Beta');
  const response = page.waitForResponse((value) =>
    /\/plan-comparisons\/[^/?]+/.test(value.url()),
  );
  release();
  await (await response).finished();
  await expect(
    group(page, 'Plan B').getByLabel('Plan name', { exact: true }),
  ).toHaveValue('New draft Beta');
  await expect(
    group(page, 'Plan A').getByLabel('Plan name', { exact: true }),
  ).toHaveValue('');
  await expect(
    results(page).getByText('Needs information', { exact: true }),
  ).toHaveCount(0);
});

test('a comparison revision conflict also blocks reopening existing snapshots', async ({
  page,
}) => {
  const api = await open(page);
  await compareUnknowns(page);
  await save(page);
  await expect(panel(page)).toContainText('Comparison saved in your account.');
  await expect(
    panel(page).getByRole('button', { name: /^Open saved comparison:/ }),
  ).toBeVisible();
  const source = [...api.cases.values()][0]!;
  api.cases.set(source.caseId, {
    ...source,
    caseRevision: source.caseRevision + 1,
  });
  await page
    .getByRole('button', { name: 'Compare plans', exact: true })
    .click();
  await expect(results(page)).toContainText(
    'This treatment changed since you opened it.',
  );
  await expect(
    panel(page).getByRole('button', { name: /^Open saved comparison:/ }),
  ).toBeDisabled();
  await expect(
    results(page).getByText('Needs information', { exact: true }),
  ).toHaveCount(0);
});

test('a missing saved comparison requires reviewing access and never opens a fallback snapshot', async ({
  page,
}) => {
  await open(page);
  await compareUnknowns(page);
  await save(page);
  await expect(panel(page)).toContainText('Comparison saved in your account.');
  await page.reload();
  await page.route(savedRoute, (route) =>
    /\/plan-comparisons\/[^/?]+/.test(route.request().url())
      ? route.fulfill({
          status: 404,
          json: {
            error: {
              code: 'NOT_FOUND',
              message: 'Comparison not found.',
              retryable: false,
              requestId: 'req-save-missing',
            },
          },
        })
      : route.fallback(),
  );
  await panel(page)
    .getByRole('button', { name: /^Open saved comparison:/ })
    .click();
  await expect(panel(page)).toContainText('Comparison not found.');
  await expect(
    panel(page).getByRole('button', { name: 'Reload treatment', exact: true }),
  ).toBeVisible();
  await expect(
    group(page, 'Plan A').getByLabel('Plan name', { exact: true }),
  ).toHaveValue('');
  await expect(
    results(page).getByText('Needs information', { exact: true }),
  ).toHaveCount(0);
});

for (const status of [401, 403]) {
  test(`${status} save failures preserve authentication enforcement`, async ({
    page,
  }) => {
    await open(page);
    await compareUnknowns(page);
    await page.route(savedRoute, (route) =>
      route.request().method() === 'POST'
        ? route.fulfill({
            status,
            json: {
              error: {
                code: status === 401 ? 'UNAUTHENTICATED' : 'FORBIDDEN',
                message: 'Saving is not authorized.',
                retryable: false,
                requestId: 'req-save-auth',
              },
            },
          })
        : route.fallback(),
    );
    await save(page);
    if (status === 401) {
      await expect(page).toHaveURL(/\/sign-in$/);
      expect(
        await page.evaluate(() =>
          sessionStorage.getItem('actionbridge.web.session.v1'),
        ),
      ).toBeNull();
    } else {
      await expect(panel(page)).toContainText('Saving is not authorized.');
      await expect(
        panel(page).getByRole('button', {
          name: 'Save comparison',
          exact: true,
        }),
      ).toBeDisabled();
      await expect(
        group(page, 'Plan B').getByLabel('Plan name', { exact: true }),
      ).toHaveValue('Fictional Beta');
    }
  });
}
