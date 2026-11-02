import { expect, test, type Page } from '@playwright/test';
import { mockBackend } from './mock-api';

test.beforeEach(async ({ page }) => {
  // Every non-local request must be intercepted by a reviewed mock. Never send
  // a Cognito, API, analytics or other external request during this suite.
  await page.route('**/*', (route) => {
    if (new URL(route.request().url()).hostname === '127.0.0.1')
      return route.continue();
    return route.abort('blockedbyclient');
  });
});

async function openSyntheticCase(page: Page) {
  const api = await mockBackend(page);
  await page.goto('/sign-in');
  await page.getByLabel('Email', { exact: true }).fill('jordan@example.com');
  await page.getByLabel('Password', { exact: true }).fill('A-long-password-1');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('button', { name: 'Try a sample case' }).click();
  await expect(
    page.getByRole('heading', { name: "Here is what we'll use" }),
  ).toBeVisible();
  expect(api.cases.size).toBe(1);
  return api;
}

test('an activity permission failure stays visible instead of pretending the ledger is empty', async ({
  page,
}) => {
  await openSyntheticCase(page);
  let attempts = 0;
  await page.route(/\/v1\/cases\/[^/]+\/ledger$/, (route) => {
    attempts++;
    return route.fulfill({
      status: 403,
      json: {
        error: {
          code: 'FORBIDDEN',
          message: 'Synthetic activity access denied.',
          retryable: false,
          requestId: 'synthetic-ledger-denied',
        },
      },
    });
  });
  await page.getByRole('link', { name: 'Activity', exact: true }).click();
  await expect(
    page.getByText('Synthetic activity access denied.'),
  ).toBeVisible();
  await expect(
    page.getByText('Reference: synthetic-ledger-denied'),
  ).toBeVisible();
  await expect(page.getByText('No recent actions were returned.')).toHaveCount(
    0,
  );
  await expect(page.getByText('Loading activity…')).toHaveCount(0);
  await expect(
    page.getByRole('button', { name: 'Try again', exact: true }),
  ).toHaveCount(0);
  const settled = attempts;
  await page.waitForTimeout(400);
  expect(attempts).toBe(settled);
});

test('a failed activity load can be retried explicitly and recovers the actual ledger events', async ({
  page,
}) => {
  await openSyntheticCase(page);
  let attempts = 0;
  await page.route(/\/v1\/cases\/[^/]+\/ledger$/, async (route) => {
    attempts++;
    const explicitlyRetried = await page.evaluate(() =>
      Boolean(
        (window as Window & { syntheticActivityRetry?: boolean })
          .syntheticActivityRetry,
      ),
    );
    if (explicitlyRetried) return route.fallback();
    return route.fulfill({
      status: 503,
      json: {
        error: {
          code: 'UPSTREAM_UNAVAILABLE',
          message: 'Synthetic activity service unavailable.',
          retryable: true,
          requestId: 'synthetic-ledger-unavailable',
        },
      },
    });
  });
  await page.getByRole('link', { name: 'Activity', exact: true }).click();
  await expect(
    page.getByText('Synthetic activity service unavailable.'),
  ).toBeVisible();
  await expect(page.getByText('No recent actions were returned.')).toHaveCount(
    0,
  );
  // Existing GET retry policy is bounded; the UI must not start another loop.
  expect(attempts).toBeLessThanOrEqual(6);
  const settled = attempts;
  await page.waitForTimeout(400);
  expect(attempts).toBe(settled);
  await page.evaluate(() => {
    document.addEventListener('click', (event) => {
      if (
        event.target instanceof Element &&
        event.target.closest('button')?.textContent === 'Try again'
      )
        (
          window as Window & { syntheticActivityRetry?: boolean }
        ).syntheticActivityRetry = true;
    });
  });
  await page
    .getByRole('button', { name: 'Try again', exact: true })
    .click({ timeout: 5000 });
  await expect(page.locator('.activity-list li')).toHaveCount(1);
  await expect(
    page.getByText('Synthetic activity service unavailable.'),
  ).toHaveCount(0);
  await expect(
    page.getByText('Reference: synthetic-ledger-unavailable'),
  ).toHaveCount(0);
});

test('a failed saved-plan read blocks the case view rather than inventing an empty saved-plan list', async ({
  page,
}) => {
  const api = await mockBackend(page);
  await page.route(/\/v1\/cases\/[^/]+\/strategies$/, (route) =>
    route.fulfill({
      status: 500,
      json: {
        error: {
          code: 'INTERNAL',
          message: 'Synthetic saved-plan read failed.',
          retryable: false,
          requestId: 'synthetic-strategies-failed',
        },
      },
    }),
  );
  await page.goto('/sign-in');
  await page.getByLabel('Email', { exact: true }).fill('jordan@example.com');
  await page.getByLabel('Password', { exact: true }).fill('A-long-password-1');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('button', { name: 'Try a sample case' }).click();
  await expect(
    page.getByText('Synthetic saved-plan read failed.'),
  ).toBeVisible();
  await expect(
    page.getByText('Reference: synthetic-strategies-failed'),
  ).toBeVisible();
  await expect(
    page.getByRole('heading', { name: "Here is what we'll use" }),
  ).toHaveCount(0);
  expect(api.cases.size).toBe(1);
});

test('case history surfaces a failed saved-plan read while a genuine empty saved-plan list remains valid', async ({
  page,
}) => {
  await openSyntheticCase(page);
  await page.route(/\/v1\/cases\/[^/]+\/strategies$/, (route) =>
    route.fulfill({
      status: 500,
      json: {
        error: {
          code: 'INTERNAL',
          message: 'Synthetic case-history saved-plan read failed.',
          retryable: false,
          requestId: 'synthetic-history-strategies-failed',
        },
      },
    }),
  );
  await page.getByRole('link', { name: 'Activity', exact: true }).click();
  await expect(
    page.getByText('Synthetic case-history saved-plan read failed.'),
  ).toBeVisible();
  await expect(
    page.getByText('Reference: synthetic-history-strategies-failed'),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Resume case', exact: true }),
  ).toHaveCount(0);
});

test('an actually empty ledger is distinct from a failed read', async ({
  page,
}) => {
  await openSyntheticCase(page);
  await page.route(/\/v1\/cases\/[^/]+\/ledger$/, (route) =>
    route.fulfill({ json: { events: [], nextCursor: null } }),
  );
  await page.getByRole('link', { name: 'Activity', exact: true }).click();
  await expect(
    page.getByText('No recent actions were returned.'),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Try again', exact: true }),
  ).toHaveCount(0);
});

test('profile privacy copy distinguishes attempted cleanup from guaranteed deletion', async ({
  page,
}) => {
  await openSyntheticCase(page);
  await page.getByRole('link', { name: 'Profile', exact: true }).click();
  await expect(
    page.getByText(
      /the service attempts to delete raw uploads after processing/,
    ),
  ).toBeVisible();
  await expect(
    page.getByText(/Failed or unfinished processing can retain uploads/),
  ).toBeVisible();
  await expect(
    page.getByText(/Your sign-in session is kept in this tab/),
  ).toBeVisible();
  await expect(
    page.getByText(
      'Uploaded documents and voice notes are read once and then deleted.',
    ),
  ).toHaveCount(0);
});
