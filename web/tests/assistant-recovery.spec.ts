import { expect, test, type Page } from '@playwright/test';
import type { AgentJobView, DentalCase } from '@actionbridge/contracts';
import { mockBackend } from './mock-api';

const JOB_ID = 'job-recovery-synthetic';
const FAILURE = 'The assistant could not finish this synthetic analysis.';

async function failedAssistant(
  page: Page,
  options: {
    empty?: boolean;
    otherSelected?: boolean;
    missing?: boolean;
    attempt?: number;
    unknownCoverage?: boolean;
  } = {},
) {
  const api = await mockBackend(page);
  await page.goto('/sign-in');
  await page.getByLabel('Email', { exact: true }).fill('jordan@example.com');
  await page.getByLabel('Password', { exact: true }).fill('A-long-password-1');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('button', { name: 'Try a sample case' }).click();
  await expect(
    page.getByRole('heading', { name: "Here is what we'll use" }),
  ).toBeVisible();
  let record = structuredClone([...api.cases.values()][0]!);
  if (options.empty) {
    record = {
      ...record,
      status: 'draft',
      coverageMode: 'unknown',
      policy: null,
      planYears: {},
      procedures: [],
      sourceFacts: [],
    };
    api.cases.set(record.caseId, record);
  }
  if (options.unknownCoverage) {
    record.coverageMode = 'unknown';
    api.cases.set(record.caseId, record);
  }
  let other: DentalCase | undefined;
  if (options.otherSelected) {
    other = { ...structuredClone(record), caseId: 'case-other-synthetic' };
    other.procedures[0]!.label = 'Different synthetic treatment';
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
  const at = new Date().toISOString();
  const job: AgentJobView = {
    jobId: JOB_ID,
    caseId: options.missing ? 'case-missing-synthetic' : record.caseId,
    caseRevision: record.caseRevision,
    operation: 'interpret',
    status: 'failed',
    attempt: options.attempt ?? 1,
    maxAttempts: 2,
    events: [],
    questions: null,
    resultBlocks: null,
    transcript: null,
    error: {
      code: 'UPSTREAM_UNAVAILABLE',
      message: FAILURE,
      retryable: true,
      requestId: 'req-synthetic-recovery',
    },
    createdAt: at,
    updatedAt: at,
  };
  await page.route(`**/v1/jobs/${JOB_ID}`, (route) =>
    route.fulfill({ json: job }),
  );
  await page.goto(`/assistant/${JOB_ID}`);
  await expect(page.getByRole('status')).toContainText(FAILURE);
  return { api, record, other, job };
}

test('failed analysis opens the same case for manual editing without another case or AI job', async ({
  page,
}) => {
  const { api, record } = await failedAssistant(page);
  await page.getByRole('button', { name: 'Enter details manually' }).click();
  await expect(page).toHaveURL(
    new RegExp(`/intake/manual\\?caseId=${record.caseId}$`),
  );
  await expect(page.getByLabel('Procedure 1 name')).toHaveValue(
    record.procedures[0]!.label,
  );
  await expect(page.getByLabel('Procedure 3 name')).toHaveValue(
    record.procedures[2]!.label,
  );
  await page.getByLabel('Procedure 1 name').fill('Updated synthetic filling');
  await page.getByRole('button', { name: 'Continue to review' }).click();
  await expect(page).toHaveURL(/\/facts$/);

  const patches = api.requests.filter((request) => request.method === 'PATCH');
  expect(patches).toHaveLength(1);
  expect(patches[0]).toMatchObject({
    path: `/v1/cases/${record.caseId}`,
    body: { expectedRevision: 1 },
  });
  const saved = api.cases.get(record.caseId)!;
  expect(saved.procedures[0]!.label).toBe('Updated synthetic filling');
  expect(saved.procedures[0]!.providerChargeCents).toBe(
    record.procedures[0]!.providerChargeCents,
  );
  expect(saved.procedures[1]).toEqual(record.procedures[1]);
  expect(saved.procedures[2]).toEqual(record.procedures[2]);
  expect(saved.policy).toEqual(record.policy);
  expect(saved.planYears).toEqual(record.planYears);
  expect(api.cases.size).toBe(1);
  expect(
    api.requests.filter(
      (request) => request.method === 'POST' && request.path.endsWith('/jobs'),
    ),
  ).toHaveLength(0);
  expect(
    api.requests.filter(
      (request) => request.method === 'POST' && request.path === '/v1/cases',
    ),
  ).toHaveLength(1);
});

test('manual recovery from an empty case keeps unentered amounts, coverage and dates unknown', async ({
  page,
}) => {
  const { api, record } = await failedAssistant(page, { empty: true });
  await page.getByRole('button', { name: 'Enter details manually' }).click();
  await page.getByLabel('Procedure 1 name').fill('Synthetic crown');
  await page.getByLabel('Procedure 1 type').selectOption('major');
  await page.getByRole('button', { name: 'Continue to review' }).click();
  await expect(page).toHaveURL(/\/facts$/);
  const saved = api.cases.get(record.caseId)!;
  expect(saved.caseRevision).toBe(2);
  expect(saved.coverageMode).toBe('unknown');
  expect(saved.policy).toBeNull();
  expect(saved.planYears).toEqual({});
  expect(saved.procedures[0]).toMatchObject({
    label: 'Synthetic crown',
    providerChargeCents: null,
    allowedCents: null,
    contractualWriteoffCents: null,
    network: 'unknown',
    proposedDate: null,
    dentistEarliestDate: null,
    dentistLatestDate: null,
    timingSource: 'unknown',
  });
  expect(api.cases.size).toBe(1);
  expect(
    api.requests.filter(
      (request) => request.method === 'POST' && request.path.endsWith('/jobs'),
    ),
  ).toHaveLength(0);
});

test('manual recovery preserves confirmed plan facts while coverage status is still unknown', async ({
  page,
}) => {
  const { api, record } = await failedAssistant(page, {
    unknownCoverage: true,
  });
  await page.getByRole('button', { name: 'Enter details manually' }).click();
  await expect(page.getByLabel('Insurance status')).toHaveValue('unknown');
  await page.getByLabel('Procedure 1 name').fill('Synthetic corrected filling');
  await page.getByRole('button', { name: 'Continue to review' }).click();
  await expect(page).toHaveURL(/\/facts$/);
  const saved = api.cases.get(record.caseId)!;
  expect(saved.coverageMode).toBe('unknown');
  expect(saved.policy).toEqual(record.policy);
  expect(saved.planYears).toEqual(record.planYears);
  const patch = api.requests.find((request) => request.method === 'PATCH')!;
  expect((patch.body as { changes: unknown }).changes).not.toHaveProperty(
    'policy',
  );
});

test('manual recovery selects the failed job case rather than another recent case', async ({
  page,
}) => {
  const { api, record, other } = await failedAssistant(page, {
    otherSelected: true,
  });
  await page.getByRole('button', { name: 'Enter details manually' }).click();
  await expect(page.getByLabel('Procedure 1 name')).toHaveValue(
    record.procedures[0]!.label,
  );
  await page
    .getByLabel('Procedure 1 name')
    .fill('Correct case synthetic filling');
  await page.getByRole('button', { name: 'Continue to review' }).click();
  await expect(page).toHaveURL(/\/facts$/);
  expect(
    api.requests
      .filter((request) => request.method === 'PATCH')
      .map((request) => request.path),
  ).toEqual([`/v1/cases/${record.caseId}`]);
  expect(api.cases.get(other!.caseId)).toEqual(other);
});

test('an unavailable recovery case shows the API error instead of creating a replacement case', async ({
  page,
}) => {
  const { api } = await failedAssistant(page, { missing: true });
  await page.getByRole('button', { name: 'Enter details manually' }).click();
  await expect(
    page.getByRole('heading', { name: 'Couldn’t open your saved case' }),
  ).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('Case not found.');
  await expect(page.getByLabel('Procedure 1 name')).toHaveCount(0);
  await expect(
    page.getByRole('button', { name: 'Continue to review' }),
  ).toHaveCount(0);
  expect(api.cases.size).toBe(1);
  expect(
    api.requests.filter(
      (request) => request.method === 'POST' && request.path.endsWith('/jobs'),
    ),
  ).toHaveLength(0);
});

test('exhausted assistant retries offer manual entry without a retry request', async ({
  page,
}) => {
  await failedAssistant(page, { attempt: 2 });
  let retries = 0;
  await page.route(`**/v1/jobs/${JOB_ID}/retry`, async (route) => {
    retries++;
    await route.fulfill({ status: 202, json: { jobId: JOB_ID } });
  });
  await expect(page.getByText(/reached its retry limit/)).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Try again', exact: true }),
  ).toHaveCount(0);
  await page.getByRole('button', { name: 'Enter details manually' }).click();
  await expect(
    page.getByRole('heading', { name: 'Enter your details' }),
  ).toBeVisible();
  expect(retries).toBe(0);
});

test('a staging quota error leaves manual recovery available and never retries automatically', async ({
  page,
}) => {
  const { api } = await failedAssistant(page);
  let retries = 0;
  await page.route(`**/v1/jobs/${JOB_ID}/retry`, async (route) => {
    retries++;
    await route.fulfill({
      status: 429,
      json: {
        error: {
          code: 'RATE_LIMITED',
          message: 'No assistant analyses remain today.',
          retryable: false,
          requestId: 'req-quota-synthetic',
        },
      },
    });
  });
  await page.getByRole('button', { name: 'Try again', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText(
    'No assistant analyses remain today.',
  );
  await page.getByRole('button', { name: 'Enter details manually' }).click();
  await expect(
    page.getByRole('heading', { name: 'Enter your details' }),
  ).toBeVisible();
  expect(retries).toBe(1);
  expect(
    api.requests.filter(
      (request) => request.method === 'POST' && request.path.endsWith('/jobs'),
    ),
  ).toHaveLength(0);
});

test('a successful explicit retry resumes the existing job and shows the server response', async ({
  page,
}) => {
  const { job } = await failedAssistant(page);
  let retries = 0;
  await page.route(`**/v1/jobs/${JOB_ID}/retry`, async (route) => {
    retries++;
    job.status = 'completed';
    job.error = null;
    job.resultBlocks = {
      schemaVersion: 1,
      caseRevision: job.caseRevision,
      blocks: [
        {
          id: 'recovered-notice',
          type: 'notice',
          severity: 'info',
          title: 'Analysis recovered',
          body: 'Review the synthetic details to continue.',
        },
      ],
    };
    await route.fulfill({ status: 202, json: { jobId: JOB_ID } });
  });
  await page.getByRole('button', { name: 'Try again', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Almost there' }),
  ).toBeVisible();
  await expect(
    page.getByText('Analysis recovered', { exact: true }),
  ).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/assistant/${JOB_ID}$`));
  expect(retries).toBe(1);
});

test('manual recovery blocks stale saves until the latest details are explicitly loaded', async ({
  page,
}) => {
  const { api, record } = await failedAssistant(page);
  await page.getByRole('button', { name: 'Enter details manually' }).click();
  await page
    .getByLabel('Procedure 1 name')
    .fill('My unsaved synthetic correction');
  const latest = structuredClone(api.cases.get(record.caseId)!);
  latest.caseRevision = 2;
  latest.procedures[0]!.label = 'Changed in another synthetic session';
  latest.procedures[0]!.providerChargeCents = 30000;
  latest.policy!.insurerRateBpsByCategory.basic = 6000;
  api.cases.set(record.caseId, latest);
  await page.getByRole('button', { name: 'Continue to review' }).click();
  await expect(page.getByRole('alert')).toContainText(
    'This case changed in another window.',
  );
  await expect(page.getByLabel('Procedure 1 name')).toHaveValue(
    'My unsaved synthetic correction',
  );
  expect(api.cases.get(record.caseId)!.procedures[0]!.label).toBe(
    'Changed in another synthetic session',
  );

  await page.getByRole('button', { name: 'Continue to review' }).click();
  await expect(page.getByRole('alert')).toContainText(
    'Load the latest details',
  );
  expect(
    api.requests.filter((request) => request.method === 'PATCH'),
  ).toHaveLength(1);
  await page.getByRole('button', { name: 'Load latest details' }).click();
  await expect(page.getByLabel('Procedure 1 name')).toHaveValue(
    'Changed in another synthetic session',
  );
  await expect(
    page.getByLabel('Changed in another synthetic session · Dentist’s charge'),
  ).toHaveValue('300');
  await expect(page.getByLabel('basic services · Plan pays')).toHaveValue('60');
  await page
    .getByLabel('Procedure 1 name')
    .fill('Reviewed synthetic correction');
  await page.getByRole('button', { name: 'Continue to review' }).click();
  await expect(page).toHaveURL(/\/facts$/);
  const patches = api.requests.filter((request) => request.method === 'PATCH');
  expect(patches).toHaveLength(2);
  expect(patches[1]!.body).toMatchObject({ expectedRevision: 2 });
  expect(api.cases.get(record.caseId)!.caseRevision).toBe(3);
});
