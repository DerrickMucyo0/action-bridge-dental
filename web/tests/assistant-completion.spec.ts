import { expect, test, type Page } from '@playwright/test';
import type { AgentJobView } from '@actionbridge/contracts';
import { mockBackend } from './mock-api';

const JOB_ID = 'job-completed-synthetic';

async function completedAssistant(
  page: Page,
  options: {
    otherSelected?: boolean;
    changed?: boolean;
    missing?: boolean;
    voice?: boolean;
  } = {},
) {
  const api = await mockBackend(page);
  await page.goto('/sign-in');
  await page.getByLabel('Email', { exact: true }).fill('jordan@example.com');
  await page.getByLabel('Password', { exact: true }).fill('A-long-password-1');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  // Facts loads its own calculator results. Finish those requests before changing
  // the mock record or clearing history for the separate completed-job visit.
  const initialCalculations = Promise.all(
    ['estimates', 'scenarios', 'coverage-comparison'].map((operation) =>
      page.waitForResponse(
        (response) =>
          response.request().method() === 'POST' &&
          response.url().endsWith(`/${operation}`),
      ),
    ),
  );
  await page.getByRole('button', { name: 'Try a sample case' }).click();
  await expect(
    page.getByRole('heading', { name: "Here is what we'll use" }),
  ).toBeVisible();
  await initialCalculations;
  const record = structuredClone([...api.cases.values()][0]!);
  if (options.otherSelected) {
    const other = {
      ...structuredClone(record),
      caseId: 'case-other-completion-synthetic',
    };
    other.procedures[0]!.label = 'Another synthetic case';
    api.cases.set(other.caseId, other);
    await page.evaluate(
      ({ otherId, originalId }) => {
        localStorage.setItem(
          'actionbridge.web.cases.v1.jordan@example.com',
          JSON.stringify([otherId, originalId]),
        );
      },
      { otherId: other.caseId, originalId: record.caseId },
    );
  }
  if (options.changed) {
    const latest = structuredClone(record);
    latest.caseRevision++;
    latest.procedures[0]!.label = 'Updated synthetic filling';
    api.cases.set(record.caseId, latest);
  }
  const at = new Date().toISOString();
  const job: AgentJobView = {
    jobId: JOB_ID,
    caseId: options.missing
      ? 'case-missing-completion-synthetic'
      : record.caseId,
    caseRevision: record.caseRevision,
    operation: 'interpret',
    status: 'completed',
    attempt: 1,
    maxAttempts: 2,
    events: [],
    questions: null,
    resultBlocks: {
      schemaVersion: 1,
      caseRevision: record.caseRevision,
      blocks: [{ id: 'summary', type: 'cost_summary', scenarioId: 'baseline' }],
    },
    transcript: null,
    error: null,
    createdAt: at,
    updatedAt: at,
  };
  await page.route(`**/v1/jobs/${JOB_ID}`, (route) =>
    route.fulfill({ json: job }),
  );
  if (options.voice)
    await page.evaluate(() =>
      localStorage.setItem('actionbridge.web.voice.v1', 'on'),
    );
  api.requests.length = 0;
  await page.goto(`/assistant/${JOB_ID}`);
  return { api, record, job };
}

test('completed analysis calculates only its own case when another case has the same revision', async ({
  page,
}) => {
  const { api, record } = await completedAssistant(page, {
    otherSelected: true,
  });
  await expect(
    page.getByRole('heading', { name: 'Your estimate is ready' }),
  ).toBeVisible();
  await expect(page.locator('.estimate-summary .scenario-money')).toHaveText(
    '$1,200',
  );
  const calculations = api.requests.filter(
    (request) => request.method === 'POST',
  );
  expect(
    [...new Set(calculations.map((request) => request.path))].sort(),
  ).toEqual(
    ['coverage-comparison', 'estimates', 'scenarios']
      .map((operation) => `/v1/cases/${record.caseId}/${operation}`)
      .sort(),
  );
  expect(
    calculations.every((request) =>
      request.path.startsWith(`/v1/cases/${record.caseId}/`),
    ),
  ).toBe(true);
  expect(
    calculations.every(
      (request) =>
        (request.body as { expectedRevision: number }).expectedRevision ===
        record.caseRevision,
    ),
  ).toBe(true);
  await page.getByRole('button', { name: 'See your options' }).click();
  await expect(page).toHaveURL(/\/options$/);
  expect(api.cases.size).toBe(2);
});

test('an older completed analysis requires reviewing the current revision without showing old numbers', async ({
  page,
}) => {
  const { api } = await completedAssistant(page, {
    changed: true,
    voice: true,
  });
  await expect(
    page.getByRole('heading', { name: 'Review your updated details' }),
  ).toBeVisible();
  await expect(page.getByRole('status')).toContainText(
    'Your details have changed since this analysis.',
  );
  await expect(page.locator('.estimate-summary')).toHaveCount(0);
  await expect(
    page.getByRole('heading', { name: 'Your estimate is ready' }),
  ).toHaveCount(0);
  expect(api.requests.filter((request) => request.method === 'POST')).toEqual(
    [],
  );
  await page.getByRole('button', { name: 'Check current details' }).click();
  await expect(page).toHaveURL(/\/facts$/);
  await expect(
    page.getByText('Updated synthetic filling', { exact: true }),
  ).toBeVisible();
});

test('a missing completed-analysis case shows its error without using another saved case or creating one', async ({
  page,
}) => {
  const { api } = await completedAssistant(page, { missing: true });
  await expect(
    page.getByRole('heading', { name: 'Couldn’t open this analysis’s case' }),
  ).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('Case not found.');
  await expect(page.locator('.estimate-summary')).toHaveCount(0);
  expect(api.requests.filter((request) => request.method === 'POST')).toEqual(
    [],
  );
  expect(api.cases.size).toBe(1);
});
