import { expect, test, type Page } from '@playwright/test';
import type { AgentJobView } from '@actionbridge/contracts';
import { mockBackend } from './mock-api';

const JOB_ID = 'job-cancellation-synthetic';

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

async function flushRenderedResponse(page: Page) {
  await page.evaluate(
    () => new Promise<void>((done) => setTimeout(() => setTimeout(done, 0), 0)),
  );
}

async function runningAssistant(page: Page) {
  const api = await mockBackend(page);
  await page.goto('/sign-in');
  await page.getByLabel('Email', { exact: true }).fill('jordan@example.com');
  await page.getByLabel('Password', { exact: true }).fill('A-long-password-1');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('button', { name: 'Try a sample case' }).click();
  await expect(
    page.getByRole('heading', { name: "Here is what we'll use" }),
  ).toBeVisible();
  const record = structuredClone([...api.cases.values()][0]!);
  const at = new Date().toISOString();
  const job: AgentJobView = {
    jobId: JOB_ID,
    caseId: record.caseId,
    caseRevision: record.caseRevision,
    operation: 'interpret',
    status: 'running',
    attempt: 1,
    maxAttempts: 2,
    events: [],
    questions: null,
    resultBlocks: null,
    transcript: null,
    error: null,
    createdAt: at,
    updatedAt: at,
  };
  await page.route(`**/v1/jobs/${JOB_ID}`, (route) =>
    route.fulfill({ json: job }),
  );
  return { api, record, job };
}

test('stop waits for one server confirmation and preserves the saved case', async ({
  page,
}) => {
  const { api, record, job } = await runningAssistant(page);
  const finish = deferred();
  let cancellations = 0;
  await page.route(`**/v1/jobs/${JOB_ID}/cancel`, async (route) => {
    cancellations++;
    await finish.promise;
    await route.fulfill({ json: { ...job, status: 'cancelled' } });
  });
  await page.goto(`/assistant/${JOB_ID}`);
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await expect(
    page.getByRole('button', { name: 'Stop', exact: true }),
  ).toBeDisabled();
  await expect.poll(() => cancellations).toBe(1);
  await page
    .getByRole('button', { name: 'Stop', exact: true })
    .dispatchEvent('click');
  expect(cancellations).toBe(1);
  finish.resolve();
  await expect(page.getByRole('status')).toContainText(
    'The assistant is stopped.',
  );
  await expect(page).toHaveURL(new RegExp(`/assistant/${JOB_ID}$`));
  expect(api.cases.get(record.caseId)).toEqual(record);
  await page.getByRole('button', { name: 'Enter details manually' }).click();
  await expect(page).toHaveURL(
    new RegExp(`/intake/manual\\?caseId=${record.caseId}$`),
  );
  await expect(page.getByLabel('Procedure 1 name')).toHaveValue(
    record.procedures[0]!.label,
  );
});

test('a stop failure keeps the job visible and requires an explicit retry', async ({
  page,
}) => {
  const { job } = await runningAssistant(page);
  let cancellations = 0;
  await page.route(`**/v1/jobs/${JOB_ID}/cancel`, (route) => {
    cancellations++;
    return cancellations === 1
      ? route.fulfill({
          status: 503,
          json: {
            error: {
              code: 'UPSTREAM_UNAVAILABLE',
              message: 'Stopping is temporarily unavailable.',
              retryable: true,
              requestId: 'req-synthetic-stop',
            },
          },
        })
      : route.fulfill({ json: { ...job, status: 'cancelled' } });
  });
  await page.goto(`/assistant/${JOB_ID}`);
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await expect(
    page.getByText('Stopping is temporarily unavailable.'),
  ).toBeVisible();
  await expect(
    page.getByRole('heading', { name: 'Working on it' }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Stop', exact: true }),
  ).toBeEnabled();
  expect(cancellations).toBe(1);
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await expect(page.getByRole('status')).toContainText(
    'The assistant is stopped.',
  );
  expect(cancellations).toBe(2);
});

test('completion racing a stop renders the returned completion rather than claiming cancellation', async ({
  page,
}) => {
  const { job } = await runningAssistant(page);
  await page.route(`**/v1/jobs/${JOB_ID}/cancel`, (route) =>
    route.fulfill({ json: { ...job, status: 'completed' } }),
  );
  await page.goto(`/assistant/${JOB_ID}`);
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Almost there' }),
  ).toBeVisible();
  await expect(page.getByText('The assistant is stopped.')).toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(`/assistant/${JOB_ID}$`));
});

test('an older in-flight poll cannot overwrite the confirmed cancellation', async ({
  page,
}) => {
  const { job } = await runningAssistant(page);
  const finishPoll = deferred();
  const pollStarted = deferred();
  let holdNextPoll = false;
  await page.route(`**/v1/jobs/${JOB_ID}`, async (route) => {
    if (holdNextPoll) {
      holdNextPoll = false;
      pollStarted.resolve();
      await finishPoll.promise;
    }
    await route.fulfill({ json: job });
  });
  await page.route(`**/v1/jobs/${JOB_ID}/cancel`, (route) =>
    route.fulfill({ json: { ...job, status: 'cancelled' } }),
  );
  await page.goto(`/assistant/${JOB_ID}`);
  await expect(
    page.getByRole('heading', { name: 'Working on it' }),
  ).toBeVisible();
  // Wait for the initial StrictMode reads to render before holding a real poll.
  holdNextPoll = true;
  await pollStarted.promise;
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await expect(page.getByRole('status')).toContainText(
    'The assistant is stopped.',
  );
  const staleResponse = page.waitForResponse((response) =>
    response.url().endsWith(`/v1/jobs/${JOB_ID}`),
  );
  finishPoll.resolve();
  await (await staleResponse).finished();
  await flushRenderedResponse(page);
  await expect(
    page.getByRole('heading', { name: 'Working on it' }),
  ).toHaveCount(0);
  await expect(page.getByRole('status')).toContainText(
    'The assistant is stopped.',
  );
});

test('a late cancellation response cannot replace another job after navigation', async ({
  page,
}) => {
  const { job } = await runningAssistant(page);
  const finish = deferred();
  const secondId = 'job-second-synthetic';
  let cancellationStarted = false;
  await page.route(`**/v1/jobs/${JOB_ID}/cancel`, async (route) => {
    cancellationStarted = true;
    await finish.promise;
    await route.fulfill({ json: { ...job, status: 'cancelled' } });
  });
  await page.route(`**/v1/jobs/${secondId}`, (route) =>
    route.fulfill({ json: { ...job, jobId: secondId } }),
  );
  await page.goto(`/assistant/${JOB_ID}`);
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await expect.poll(() => cancellationStarted).toBe(true);
  await page.evaluate((id) => {
    history.pushState({}, '', `/assistant/${id}`);
    dispatchEvent(new PopStateEvent('popstate'));
  }, secondId);
  await expect(page).toHaveURL(new RegExp(`/assistant/${secondId}$`));
  await expect(
    page.getByRole('button', { name: 'Stop', exact: true }),
  ).toBeEnabled();
  const response = page.waitForResponse((item) =>
    item.url().endsWith(`/v1/jobs/${JOB_ID}/cancel`),
  );
  finish.resolve();
  await (await response).finished();
  await flushRenderedResponse(page);
  await expect(
    page.getByRole('heading', { name: 'Working on it' }),
  ).toBeVisible();
  await expect(page.getByText('The assistant is stopped.')).toHaveCount(0);
});

test('a late stop response cannot restart polling after leaving the assistant', async ({
  page,
}) => {
  const { job } = await runningAssistant(page);
  const finish = deferred();
  let cancellationStarted = false;
  let reads = 0;
  await page.route(`**/v1/jobs/${JOB_ID}`, (route) => {
    reads++;
    return route.fulfill({ json: job });
  });
  await page.route(`**/v1/jobs/${JOB_ID}/cancel`, async (route) => {
    cancellationStarted = true;
    await finish.promise;
    // A concurrent state change can leave the job running. The unmounted
    // assistant must not start following that response in the background.
    await route.fulfill({ json: job });
  });
  await page.goto(`/assistant/${JOB_ID}`);
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await expect.poll(() => cancellationStarted).toBe(true);
  await page.getByRole('link', { name: 'Home', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  const readsBeforeResponse = reads;
  const response = page.waitForResponse((item) =>
    item.url().endsWith(`/v1/jobs/${JOB_ID}/cancel`),
  );
  finish.resolve();
  await (await response).finished();
  await flushRenderedResponse(page);
  expect(reads).toBe(readsBeforeResponse);
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByText('The assistant is stopped.')).toHaveCount(0);
});

for (const oldOutcome of ['completed', 'error'] as const) {
  test(`returning to the same job ignores an old ${oldOutcome} cancellation response and preserves the new pending request`, async ({
    page,
  }) => {
    const { job } = await runningAssistant(page);
    const finishOld = deferred();
    const finishNew = deferred();
    const secondId = 'job-roundtrip-synthetic';
    let cancellations = 0;
    await page.route(`**/v1/jobs/${secondId}`, (route) =>
      route.fulfill({ json: { ...job, jobId: secondId } }),
    );
    await page.route(`**/v1/jobs/${JOB_ID}/cancel`, async (route) => {
      const mine = ++cancellations;
      await (mine === 1 ? finishOld.promise : finishNew.promise);
      if (mine === 1 && oldOutcome === 'error')
        await route.fulfill({
          status: 503,
          json: {
            error: {
              code: 'UPSTREAM_UNAVAILABLE',
              message: 'This belongs to the old stop request.',
              retryable: true,
              requestId: 'req-old-stop-synthetic',
            },
          },
        });
      else
        await route.fulfill({
          json: { ...job, status: mine === 1 ? 'completed' : 'cancelled' },
        });
    });
    await page.goto(`/assistant/${JOB_ID}`);
    await page.getByRole('button', { name: 'Stop', exact: true }).click();
    await expect.poll(() => cancellations).toBe(1);
    for (const id of [secondId, JOB_ID]) {
      const next = page.waitForResponse((response) =>
        response.url().endsWith(`/v1/jobs/${id}`),
      );
      await page.evaluate((nextId) => {
        history.pushState({}, '', `/assistant/${nextId}`);
        dispatchEvent(new PopStateEvent('popstate'));
      }, id);
      await (await next).finished();
      await flushRenderedResponse(page);
      await expect(
        page.getByRole('button', { name: 'Stop', exact: true }),
      ).toBeEnabled();
    }
    await page.getByRole('button', { name: 'Stop', exact: true }).click();
    await expect.poll(() => cancellations).toBe(2);
    await expect(
      page.getByRole('button', { name: 'Stop', exact: true }),
    ).toBeDisabled();
    const oldResponse = page.waitForResponse((response) =>
      response.url().endsWith(`/v1/jobs/${JOB_ID}/cancel`),
    );
    finishOld.resolve();
    await (await oldResponse).finished();
    await flushRenderedResponse(page);
    await expect(
      page.getByRole('heading', { name: 'Working on it' }),
    ).toBeVisible();
    await expect(
      page.getByText('This belongs to the old stop request.'),
    ).toHaveCount(0);
    await expect(
      page.getByRole('button', { name: 'Stop', exact: true }),
    ).toBeDisabled();
    await page
      .getByRole('button', { name: 'Stop', exact: true })
      .dispatchEvent('click');
    expect(cancellations).toBe(2);
    finishNew.resolve();
    await expect(page.getByRole('status')).toContainText(
      'The assistant is stopped.',
    );
  });
}
