import { expect, test, type Page } from '@playwright/test';
import { mockBackend } from './mock-api';

async function track(page: Page, newPasswordFor?: string) {
  await mockBackend(page, newPasswordFor ? { newPasswordFor } : {});
  const calls: string[] = [];
  await page.route(/cognito-idp\..*\.amazonaws\.com/, async (route) => {
    const operation = (route.request().headers()['x-amz-target'] ?? '')
      .split('.')
      .at(-1)!;
    calls.push(operation);
    await route.fallback();
  });
  return calls;
}
for (const mode of ['create', 'verify', 'forgot', 'reset']) {
  test(`restricted direct ${mode} URL exposes existing-account sign-in and makes no Cognito call`, async ({
    page,
  }) => {
    const calls = await track(page);
    await page.goto(`/sign-in?mode=${mode}`);
    await expect(
      page.getByRole('heading', {
        name: 'Sign in to continue your saved plans.',
      }),
    ).toBeVisible();
    await expect(page.getByRole('status')).toContainText(
      'Account creation, verification and password reset are unavailable',
    );
    for (const name of [
      'Create an account',
      'Forgot password?',
      'Verify email',
      'Already have a verification code?',
      'Resend verification code',
      'Resend reset code',
    ])
      await expect(page.getByRole('button', { name, exact: true })).toHaveCount(
        0,
      );
    await expect(
      page.getByLabel(/Verification code|Reset code|Confirm password/),
    ).toHaveCount(0);
    expect(calls).toEqual([]);
  });
}

test('restricted AuthProvider wrappers reject all public account operations before transport', async ({
  page,
}) => {
  const calls = await track(page);
  await page.goto('/tests/public-account-policy-harness.html');
  for (const name of [
    'SignUp',
    'ConfirmSignUp',
    'ResendConfirmationCode',
    'ForgotPassword',
    'ConfirmForgotPassword',
  ]) {
    await page.getByRole('button', { name, exact: true }).click();
    await expect(page.getByTestId('result')).toHaveText('FEATURE_UNAVAILABLE');
  }
  expect(calls).toEqual([]);
});

test('restricted existing-account sign-in, restoration and logout stay available', async ({
  page,
}) => {
  const calls = await track(page);
  await page.goto('/sign-in');
  await page.getByLabel('Email', { exact: true }).fill('fictional@example.com');
  await page
    .getByLabel('Password', { exact: true })
    .fill('Fictional-Password-42');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).not.toHaveURL(/sign-in/);
  await page.reload();
  await expect(page.getByText('fictional@example.com')).toBeVisible();
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(
    page.getByRole('heading', {
      name: 'Sign in to continue your saved plans.',
    }),
  ).toBeVisible();
  expect(calls).toEqual(['InitiateAuth', 'InitiateAuth', 'RevokeToken']);
});

test('restricted mode preserves an existing account NEW_PASSWORD_REQUIRED challenge', async ({
  page,
}) => {
  const calls = await track(page, 'new-fictional@example.com');
  await page.goto('/sign-in?mode=create');
  await page
    .getByLabel('Email', { exact: true })
    .fill('new-fictional@example.com');
  await page
    .getByLabel('Password', { exact: true })
    .fill('Fictional-Temporary-42');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(
    page.getByRole('heading', {
      name: 'Choose a new password to finish signing in.',
    }),
  ).toBeVisible();
  await page
    .getByLabel('New password', { exact: true })
    .fill('Fictional-New-Password-42');
  await page
    .getByLabel('Confirm password', { exact: true })
    .fill('Fictional-New-Password-42');
  await page
    .getByRole('button', { name: 'Set password and continue', exact: true })
    .click();
  await expect(page).not.toHaveURL(/sign-in/);
  expect(calls).toEqual(['InitiateAuth', 'RespondToAuthChallenge']);
});
