import { expect, test, type Page, type Route } from '@playwright/test';

async function setup(page: Page, expireSecond = false) {
  const requests: string[] = [];
  const pendingRefreshes: Route[] = [];
  await page.route(/cognito-idp\..*\.amazonaws\.com/, async (route) => {
    const target = route.request().headers()['x-amz-target'] ?? '';
    const body = route.request().postDataJSON();
    if (target.endsWith('RevokeToken')) return route.fulfill({ json: {} });
    if (body.AuthFlow === 'REFRESH_TOKEN_AUTH') {
      pendingRefreshes.push(route);
      return;
    }
    const second = body.AuthParameters?.USERNAME === 'second@example.com';
    return route.fulfill({
      json: {
        AuthenticationResult: {
          AccessToken: second ? 'second-access' : 'first-access',
          RefreshToken: second ? 'second-refresh' : 'first-refresh',
          ExpiresIn: second && !expireSecond ? 3600 : 0,
        },
      },
    });
  });
  await page.route('https://api.test.invalid/**', async (route) => {
    requests.push(route.request().headers().authorization ?? 'missing');
    return route.fulfill({
      status: 404,
      json: {
        error: {
          code: 'NOT_FOUND',
          message: 'Synthetic case absent.',
          retryable: false,
          requestId: 'synthetic-auth-race',
        },
      },
    });
  });
  await page.goto('/tests/auth-session-harness.html');
  await page
    .getByRole('button', { name: 'First sign-in', exact: true })
    .click();
  await expect(page.getByTestId('email')).toHaveText('first@example.com');
  await page
    .getByRole('button', { name: 'Read synthetic case', exact: true })
    .click();
  await expect.poll(() => pendingRefreshes.length).toBe(1);
  return {
    requests,
    pendingRefreshes,
    release: (index = 0, token = 'old-refreshed-access') =>
      pendingRefreshes[index]!.fulfill({
        json: {
          AuthenticationResult: {
            AccessToken: token,
            ExpiresIn: 3600,
          },
        },
      }),
  };
}

test('a refresh completed after sign-out cannot dispatch the pending API request', async ({
  page,
}) => {
  const mock = await setup(page);
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page.getByTestId('status')).toHaveText('signed_out');
  await mock.release();
  await expect(page.getByTestId('outcome')).toHaveText('rejected');
  expect(mock.requests).toEqual([]);
  await expect(page.getByTestId('email')).toHaveText('none');
});

test('an old refresh cannot replace a newer login or end its session', async ({
  page,
}) => {
  const mock = await setup(page);
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await page
    .getByRole('button', { name: 'Second sign-in', exact: true })
    .click();
  await expect(page.getByTestId('email')).toHaveText('second@example.com');
  await mock.release();
  await expect(page.getByTestId('outcome')).toHaveText('rejected');
  expect(mock.requests).toEqual([]);
  await expect(page.getByTestId('status')).toHaveText('signed_in');
  await expect(page.getByTestId('email')).toHaveText('second@example.com');
  await page
    .getByRole('button', { name: 'Read synthetic case', exact: true })
    .click();
  await expect.poll(() => mock.requests).toEqual(['Bearer second-access']);
});

test('an old refresh finishing cannot clear the new session refresh or duplicate it', async ({
  page,
}) => {
  const mock = await setup(page, true);
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await page
    .getByRole('button', { name: 'Second sign-in', exact: true })
    .click();
  await expect(page.getByTestId('email')).toHaveText('second@example.com');
  await page
    .getByRole('button', { name: 'Read synthetic case', exact: true })
    .click();
  await expect.poll(() => mock.pendingRefreshes.length).toBe(2);
  await mock.release();
  await expect(page.getByTestId('outcome')).toHaveText('rejected');
  await page
    .getByRole('button', { name: 'Read synthetic case', exact: true })
    .click();
  await mock.release(1, 'new-refreshed-access');
  await expect.poll(() => mock.requests.length).toBe(2);
  expect(mock.pendingRefreshes).toHaveLength(2);
  expect(mock.requests).toEqual([
    'Bearer new-refreshed-access',
    'Bearer new-refreshed-access',
  ]);
  await expect(page.getByTestId('status')).toHaveText('signed_in');
});

test('a sign-in response arriving after sign-out cannot restore the session', async ({
  page,
}) => {
  let pendingSignIn: Route | null = null;
  await page.route(/cognito-idp\..*\.amazonaws\.com/, async (route) => {
    pendingSignIn = route;
  });
  await page.goto('/tests/auth-session-harness.html');
  await page
    .getByRole('button', { name: 'First sign-in', exact: true })
    .click();
  await expect.poll(() => pendingSignIn !== null).toBe(true);
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await pendingSignIn!.fulfill({
    json: {
      AuthenticationResult: {
        AccessToken: 'old-sign-in-access',
        RefreshToken: 'old-sign-in-refresh',
        ExpiresIn: 3600,
      },
    },
  });
  await expect(page.getByTestId('outcome')).toHaveText('rejected');
  await expect(page.getByTestId('status')).toHaveText('signed_out');
  await expect(page.getByTestId('email')).toHaveText('none');
  expect(
    await page.evaluate(() =>
      sessionStorage.getItem('actionbridge.web.session.v1'),
    ),
  ).toBeNull();
});

test('switching accounts clears the previous credentials before the next sign-in completes', async ({
  page,
}) => {
  const mock = await setup(page);
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await mock.release();
  await expect(page.getByTestId('outcome')).toHaveText('rejected');
  await page
    .getByRole('button', { name: 'Second sign-in', exact: true })
    .click();
  await expect(page.getByTestId('email')).toHaveText('second@example.com');
  let thirdSignIn: Route | null = null;
  await page.route(/cognito-idp\..*\.amazonaws\.com/, async (route) => {
    thirdSignIn = route;
  });
  await page
    .getByRole('button', { name: 'Third sign-in', exact: true })
    .click();
  await expect.poll(() => thirdSignIn !== null).toBe(true);
  await expect(page.getByTestId('status')).toHaveText('signed_out');
  await expect(page.getByTestId('email')).toHaveText('none');
  expect(
    await page.evaluate(() =>
      sessionStorage.getItem('actionbridge.web.session.v1'),
    ),
  ).toBeNull();
  await page
    .getByRole('button', { name: 'Read synthetic case', exact: true })
    .click();
  await expect(page.getByTestId('outcome')).toHaveText('rejected');
  expect(mock.requests).toEqual([]);
  await thirdSignIn!.fulfill({
    json: {
      AuthenticationResult: {
        AccessToken: 'third-access',
        RefreshToken: 'third-refresh',
        ExpiresIn: 3600,
      },
    },
  });
  await expect(page.getByTestId('outcome')).toHaveText('rejected');
  await expect(page.getByTestId('status')).toHaveText('signed_out');
});

test('sign-out during restoration revokes the stored refresh token and ignores its late response', async ({
  page,
}) => {
  let refresh: Route | null = null;
  const revoked: string[] = [];
  await page.addInitScript(() =>
    sessionStorage.setItem(
      'actionbridge.web.session.v1',
      JSON.stringify({
        email: 'restoring@example.com',
        refreshToken: 'stored-fictional-refresh',
      }),
    ),
  );
  await page.route(/cognito-idp\..*\.amazonaws\.com/, async (route) => {
    const target = route.request().headers()['x-amz-target'] ?? '';
    if (target.endsWith('RevokeToken')) {
      revoked.push(route.request().postDataJSON().Token);
      return route.fulfill({ json: {} });
    }
    refresh = route;
  });
  await page.goto('/tests/auth-session-harness.html');
  await expect.poll(() => refresh !== null).toBe(true);
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect.poll(() => revoked).toEqual(['stored-fictional-refresh']);
  await refresh!.fulfill({
    json: {
      AuthenticationResult: {
        AccessToken: 'old-restore-access',
        ExpiresIn: 3600,
      },
    },
  });
  await expect(page.getByTestId('status')).toHaveText('signed_out');
  await expect(page.getByTestId('email')).toHaveText('none');
  expect(
    await page.evaluate(() =>
      sessionStorage.getItem('actionbridge.web.session.v1'),
    ),
  ).toBeNull();
});
