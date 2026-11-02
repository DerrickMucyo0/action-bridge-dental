import { expect, test, type Page } from '@playwright/test';
import { mockBackend, type MockApi } from './mock-api';

async function signInCore(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('actionbridge.web.voice.v1', 'on');
    const scope = window as unknown as { syntheticMicrophoneRequests: number };
    scope.syntheticMicrophoneRequests = 0;
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: async () => {
          scope.syntheticMicrophoneRequests++;
          throw new Error('A core page must not request a microphone');
        },
      },
    });
  });
  const api = await mockBackend(page);
  await page.goto('/sign-in');
  await page.getByLabel('Email', { exact: true }).fill('jordan@example.com');
  await page.getByLabel('Password', { exact: true }).fill('A-long-password-1');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(
    page.getByText(
      'Assistant analysis, document uploads and voice are unavailable in this version. Manual entry and cost comparisons remain available.',
    ),
  ).toBeVisible();
  return api;
}

function expectNoBackground(api: MockApi) {
  expect(
    api.requests.filter((request) =>
      /\/(jobs|uploads|speech)(?:\/|$)/.test(request.path),
    ),
  ).toEqual([]);
}

test('core profile describes unavailable voice and truthful storage behavior without background requests', async ({
  page,
}) => {
  await page.route('**/*', (route) => {
    if (new URL(route.request().url()).hostname === '127.0.0.1')
      return route.continue();
    return route.abort('blockedbyclient');
  });
  const api = await signInCore(page);
  await page.getByRole('link', { name: 'Profile', exact: true }).click();
  await expect(
    page.getByText(
      'Voice guidance is unavailable in this version. Use the on-screen controls instead.',
    ),
  ).toBeVisible();
  await expect(page.getByText(/key screens read themselves aloud/)).toHaveCount(
    0,
  );
  await expect(
    page.getByText(
      /the service attempts to delete raw uploads after processing/,
    ),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: /voice guidance/i }),
  ).toHaveCount(0);
  expectNoBackground(api);
});

test('core landing explains its available features before sign-in and opens existing-account sign-in', async ({
  page,
}) => {
  const api = await mockBackend(page);
  await page.goto('/');
  await expect(page.getByRole('note')).toContainText(
    'AI analysis, uploads and voice are unavailable.',
  );
  await expect(page.getByRole('note')).toContainText('fictional details only');
  const callsToAction = page.getByRole('link', {
    name: 'Get started',
    exact: true,
  });
  for (const link of await callsToAction.all())
    await expect(link).toHaveAttribute('href', '/sign-in');
  await callsToAction.filter({ visible: true }).first().click();
  await expect(page).toHaveURL(/\/sign-in$/);
  await expect(
    page.getByRole('button', { name: 'Sign in', exact: true }),
  ).toBeVisible();
  expect(api.cases.size).toBe(0);
  expectNoBackground(api);
});

test('core landing notice and sign-in stay usable on a small phone without starting work', async ({
  page,
}) => {
  await page.setViewportSize({ width: 360, height: 640 });
  const api = await mockBackend(page);
  await page.goto('/');
  await expect(page.getByRole('note')).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(360);
  const start = page
    .getByRole('link', { name: 'Get started', exact: true })
    .filter({ visible: true })
    .first();
  await expect(start).toHaveAttribute('href', '/sign-in');
  const heroBounds = await page.locator('.lp-hero').boundingBox();
  const actionBounds = await start.boundingBox();
  expect(actionBounds!.y + actionBounds!.height).toBeLessThanOrEqual(
    heroBounds!.y + heroBounds!.height,
  );
  await start.click();
  await expect(page.getByLabel('Email', { exact: true })).toBeVisible();
  expect(api.cases.size).toBe(0);
  expectNoBackground(api);
});

test('core home labels unavailable features and keeps manual/sample entry available without voice', async ({
  page,
}) => {
  const api = await signInCore(page);
  for (const name of ['Speak', 'Upload', 'Photo', 'Type'])
    await expect(page.getByRole('button', { name, exact: true })).toHaveCount(
      0,
    );
  await expect(
    page.getByRole('button', { name: /voice guidance/i }),
  ).toHaveCount(0);
  await expect(
    page.getByRole('button', {
      name: 'Enter details step by step',
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Try a sample case' }),
  ).toBeVisible();
  expectNoBackground(api);
});

test('core sample still compares server estimates and saves a strategy without background services', async ({
  page,
}) => {
  const api = await signInCore(page);
  await page.getByRole('button', { name: 'Try a sample case' }).click();
  await expect(
    page.getByText('Sample case · Review before calculating'),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Confirm and compare' }).click();
  const cards = page.locator('.choice-card');
  await expect(cards).toHaveCount(2);
  await expect(cards.first()).toContainText('$1,200');
  await expect(cards.nth(1)).toContainText('$725');
  await cards.nth(1).getByRole('radio').check();
  await page.getByRole('button', { name: 'Review this plan' }).click();
  await page.getByLabel('Save this plan and my answers in my account.').check();
  await page.getByRole('button', { name: 'Save this plan' }).click();
  await expect(
    page.getByRole('heading', { name: 'Your plan is saved' }),
  ).toBeVisible();
  expect(
    api.requests.some((request) => request.path.endsWith('/scenarios')),
  ).toBe(true);
  expect([...api.strategies.values()].flat()).toHaveLength(1);
  expectNoBackground(api);
});

test('core manual entry creates a real case while keeping unknown values unknown', async ({
  page,
}) => {
  const api = await signInCore(page);
  await page
    .getByRole('button', { name: 'Enter details step by step', exact: true })
    .click();
  await page.getByLabel('Procedure 1 name').fill('Synthetic core crown');
  await page.getByLabel('Procedure 1 type').selectOption('major');
  await page.getByRole('button', { name: 'Continue to review' }).click();
  await expect(page).toHaveURL(/\/facts$/);
  const record = [...api.cases.values()][0]!;
  expect(record.procedures[0]).toMatchObject({
    label: 'Synthetic core crown',
    providerChargeCents: null,
    allowedCents: null,
    proposedDate: null,
  });
  expect(record.coverageMode).toBe('unknown');
  expect(api.cases.size).toBe(1);
  await expect(
    page.getByText(/an answer before the comparison is available/),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Confirm and compare' }).click();
  await expect(page).toHaveURL(/\/questions$/);
  await expect(
    page.getByRole('heading', { name: 'Enter details manually' }),
  ).toBeVisible();
  await page
    .getByRole('button', { name: 'Enter details step by step', exact: true })
    .click();
  await expect(page).toHaveURL(
    new RegExp(`/intake/manual\\?caseId=${record.caseId}$`),
  );
  await expect(page.getByLabel('Procedure 1 name')).toHaveValue(
    'Synthetic core crown',
  );
  expect(api.cases.size).toBe(1);
  expectNoBackground(api);
});

for (const mode of ['type', 'speak', 'upload', 'photo']) {
  test(`core ${mode} deep link has a manual fallback and never records/uploads/starts a job`, async ({
    page,
  }) => {
    const api = await signInCore(page);
    await page.goto(`/intake/${mode}`);
    await expect(
      page.getByRole('heading', { name: 'Enter details manually' }),
    ).toBeVisible();
    await expect(
      page.getByText(
        /Assistant analysis, document uploads and voice are unavailable in this version/,
      ),
    ).toBeVisible();
    await expect(
      page.getByRole('textbox', {
        name: 'Describe your treatment and your plan',
      }),
    ).toHaveCount(0);
    await expect(page.locator('input[type=file]')).toHaveCount(0);
    await page
      .getByRole('button', { name: 'Enter details step by step', exact: true })
      .click();
    await expect(
      page.getByRole('heading', { name: 'Enter your details' }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () =>
          (window as unknown as { syntheticMicrophoneRequests: number })
            .syntheticMicrophoneRequests,
      ),
    ).toBe(0);
    expect(api.cases.size).toBe(0);
    expectNoBackground(api);
  });
}

for (const path of ['/questions', '/assistant/job-unavailable-synthetic']) {
  test(`core ${path} does not read/answer/retry jobs and opens the current case manually`, async ({
    page,
  }) => {
    const api = await signInCore(page);
    await page.getByRole('button', { name: 'Try a sample case' }).click();
    await expect(
      page.getByRole('heading', { name: "Here is what we'll use" }),
    ).toBeVisible();
    const record = [...api.cases.values()][0]!;
    await page.goto(path);
    await expect(
      page.getByRole('heading', { name: 'Enter details manually' }),
    ).toBeVisible();
    await page
      .getByRole('button', { name: 'Enter details step by step', exact: true })
      .click();
    await expect(page).toHaveURL(
      new RegExp(`/intake/manual\\?caseId=${record.caseId}$`),
    );
    await expect(page.getByLabel('Procedure 1 name')).toHaveValue(
      record.procedures[0]!.label,
    );
    expect(api.cases.size).toBe(1);
    expectNoBackground(api);
  });
}
