import { expect, test, type Page, type Route } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mockBackend } from './mock-api';

type Json = Record<string, unknown>;
type Account = { password: string; confirmed: boolean };
type CognitoCall = { operation: string; body: Json };
type Failure = { operation: string; code: string };

// These are fictional test credentials. Every Cognito call is intercepted in this file.
const EMAIL = 'new.user@example.com';
const PASSWORD = 'Fictional-Test-Password-42';
const CODE = '123456';
const CLIENT_ID = 'testclientid0123456789abcd';

async function registrationBackend(page: Page) {
  const api = await mockBackend(page);
  const calls: CognitoCall[] = [];
  const accounts = new Map<string, Account>([
    ['existing@example.com', { password: PASSWORD, confirmed: true }],
  ]);
  const failures: Failure[] = [];
  const unexpected: string[] = [];
  const state = {
    api,
    calls,
    accounts,
    failures,
    unexpected,
    abortNextSignUp: false,
    signupUserConfirmed: false,
    holdSignUp: null as Promise<void> | null,
    holdInitiateAuth: null as Promise<void> | null,
  };
  const error = (route: Route, code: string) =>
    route.fulfill({
      status: 400,
      json: {
        __type: code,
        message: 'Do not display this raw service message.',
      },
    });

  // Registered after mockBackend: this route overrides its permissive sign-in stand-in.
  await page.route(/cognito-idp\..*\.amazonaws\.com/, async (route) => {
    if (route.request().method() === 'OPTIONS')
      return route.fulfill({ status: 204 });
    const operation = (route.request().headers()['x-amz-target'] ?? '')
      .split('.')
      .at(-1)!;
    const body = route.request().postDataJSON() as Json;
    calls.push({ operation, body });
    const failureIndex = failures.findIndex(
      (failure) => failure.operation === operation,
    );
    if (failureIndex !== -1) {
      const { code } = failures.splice(failureIndex, 1)[0]!;
      // Cognito can create the unconfirmed account before email delivery fails.
      if (
        operation === 'SignUp' &&
        ['LimitExceededException', 'CodeDeliveryFailureException'].includes(
          code,
        )
      )
        accounts.set(String(body.Username), {
          password: String(body.Password),
          confirmed: false,
        });
      return error(route, code);
    }
    const username = String(body.Username ?? '');
    const account = accounts.get(username);
    if (operation === 'SignUp') {
      if (state.abortNextSignUp) {
        state.abortNextSignUp = false;
        return route.abort('failed');
      }
      if (state.holdSignUp) await state.holdSignUp;
      if (account) return error(route, 'UsernameExistsException');
      accounts.set(username, {
        password: String(body.Password),
        confirmed: state.signupUserConfirmed,
      });
      return route.fulfill({
        json: {
          UserConfirmed: state.signupUserConfirmed,
          UserSub: 'fictional-new-user',
          CodeDeliveryDetails: {
            AttributeName: 'email',
            DeliveryMedium: 'EMAIL',
            Destination: 'n***@e***',
          },
        },
      });
    }
    if (operation === 'ConfirmSignUp') {
      if (!account) return error(route, 'UserNotFoundException');
      if (body.ConfirmationCode === '222222')
        return error(route, 'ExpiredCodeException');
      if (body.ConfirmationCode !== CODE)
        return error(route, 'CodeMismatchException');
      account.confirmed = true;
      return route.fulfill({ json: {} });
    }
    if (operation === 'ResendConfirmationCode') {
      return route.fulfill({
        json: {
          CodeDeliveryDetails: {
            AttributeName: 'email',
            DeliveryMedium: 'EMAIL',
            Destination: 'n***@e***',
          },
        },
      });
    }
    if (operation === 'ForgotPassword')
      return route.fulfill({
        json: {
          CodeDeliveryDetails: {
            AttributeName: 'email',
            DeliveryMedium: 'EMAIL',
            Destination: 'e***@e***',
          },
        },
      });
    if (operation === 'ConfirmForgotPassword') {
      if (body.ConfirmationCode !== CODE)
        return error(route, 'CodeMismatchException');
      if (!account) return error(route, 'UserNotFoundException');
      account.password = String(body.Password);
      return route.fulfill({ json: {} });
    }
    if (operation === 'InitiateAuth') {
      if (state.holdInitiateAuth) await state.holdInitiateAuth;
      const auth = body.AuthParameters as Json;
      const current = accounts.get(String(auth.USERNAME));
      if (!current || auth.PASSWORD !== current.password)
        return error(route, 'NotAuthorizedException');
      if (!current.confirmed) return error(route, 'UserNotConfirmedException');
      return route.fulfill({
        json: {
          AuthenticationResult: {
            AccessToken: 'test-access',
            RefreshToken: 'test-refresh',
            ExpiresIn: 3600,
          },
        },
      });
    }
    unexpected.push(operation);
    return route.fulfill({
      status: 500,
      json: { __type: 'UnexpectedTestCall' },
    });
  });
  return state;
}

async function fillRegistration(page: Page, email = EMAIL) {
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD);
  await page.getByLabel('Confirm password', { exact: true }).fill(PASSWORD);
}

async function createAccount(page: Page, email = EMAIL) {
  await page.goto('/sign-in?mode=create');
  await fillRegistration(page, email);
  await page
    .getByRole('button', { name: 'Create account', exact: true })
    .click();
  await expect(page).toHaveURL(/\/sign-in\?mode=verify$/);
  await expect(
    page.getByLabel('Verification code', { exact: true }),
  ).toBeVisible();
}

async function storedData(page: Page) {
  return page.evaluate(() =>
    JSON.stringify({
      local: { ...localStorage },
      session: { ...sessionStorage },
    }),
  );
}

for (const invalid of [
  { field: 'Email', value: 'invalid-email', message: /valid email/i },
  { field: 'Password', value: 'short', message: /12 characters/i },
  {
    field: 'Confirm password',
    value: 'Different-Fictional-Password-42',
    message: /passwords (must )?match/i,
  },
]) {
  test(`registration rejects invalid ${invalid.field.toLowerCase()} before sending credentials`, async ({
    page,
  }) => {
    const backend = await registrationBackend(page);
    await page.goto('/sign-in?mode=create');
    await fillRegistration(page);
    await page.getByLabel(invalid.field, { exact: true }).fill(invalid.value);
    await page
      .getByRole('button', { name: 'Create account', exact: true })
      .click();
    await expect(page.getByRole('alert')).toContainText(invalid.message);
    await expect(
      page.getByLabel(invalid.field, { exact: true }),
    ).toHaveAttribute('aria-invalid', 'true');
    expect(backend.calls).toEqual([]);
    expect(backend.api.requests).toEqual([]);
  });
}

for (const invalid of [
  {
    name: 'too short',
    value: 'Abcdefgh1!x',
    requirement: /At least 12 characters/,
  },
  {
    name: 'missing uppercase',
    value: 'lowercase-password-42',
    requirement: /At least one uppercase letter/,
  },
  {
    name: 'missing lowercase',
    value: 'UPPERCASE-PASSWORD-42',
    requirement: /At least one lowercase letter/,
  },
  {
    name: 'missing number',
    value: 'Missing-Number-Password',
    requirement: /At least one number/,
  },
  {
    name: 'missing special character',
    value: 'MissingSpecialPassword42',
    requirement: /At least one special character/,
  },
  {
    name: 'spaces',
    value: 'Valid Password 42!',
    requirement: /No spaces or whitespace/,
  },
  {
    name: 'emoji instead of special character',
    value: 'ValidPassword42🦷',
    requirement: /At least one special character/,
  },
]) {
  test(`registration blocks a password with ${invalid.name} before calling Cognito`, async ({
    page,
  }) => {
    const backend = await registrationBackend(page);
    await page.goto('/sign-in?mode=create');
    await fillRegistration(page);
    await page.getByLabel('Password', { exact: true }).fill(invalid.value);
    await page
      .getByLabel('Confirm password', { exact: true })
      .fill(invalid.value);
    const checklist = page.getByRole('list', { name: 'Password requirements' });
    await expect(
      checklist.getByRole('listitem').filter({ hasText: invalid.requirement }),
    ).toContainText('Missing:');
    await page
      .getByRole('button', { name: 'Create account', exact: true })
      .click();
    await expect(page.getByRole('alert')).toContainText(invalid.requirement);
    await expect(page.getByLabel('Password', { exact: true })).toHaveAttribute(
      'aria-invalid',
      'true',
    );
    expect(backend.calls).toEqual([]);
    expect(backend.api.requests).toEqual([]);
  });
}

test('registration explains every password requirement and updates missing requirements while typing', async ({
  page,
}) => {
  const backend = await registrationBackend(page);
  await page.goto('/sign-in?mode=create');
  const checklist = page.getByRole('list', { name: 'Password requirements' });
  await expect(checklist.getByRole('listitem')).toHaveCount(7);
  for (const requirement of [
    /At least 12 characters/,
    /No more than 256 characters/,
    /At least one uppercase letter/,
    /At least one lowercase letter/,
    /At least one number/,
    /At least one special character/,
    /No spaces or whitespace/,
  ]) {
    await expect(
      checklist.getByRole('listitem').filter({ hasText: requirement }),
    ).toContainText('Required:');
  }
  await page.getByLabel('Password', { exact: true }).fill('ValidPassword42');
  await expect(
    checklist
      .getByRole('listitem')
      .filter({ hasText: /At least one special character/ }),
  ).toContainText('Missing:');
  await expect(
    checklist
      .getByRole('listitem')
      .filter({ hasText: /At least 12 characters/ }),
  ).toContainText('Met:');
  await page.getByLabel('Password', { exact: true }).fill('ValidPassword42!');
  await expect(
    checklist.getByRole('listitem').filter({ hasText: /^Met:/ }),
  ).toHaveCount(7);
  await expect(checklist).not.toContainText('Missing:');
  expect(backend.calls).toEqual([]);
  expect(backend.api.requests).toEqual([]);
});

test('password reset blocks a missing special character before calling Cognito', async ({
  page,
}) => {
  const backend = await registrationBackend(page);
  await page.goto('/sign-in?mode=reset');
  await page.getByLabel('Email', { exact: true }).fill('existing@example.com');
  await page.getByLabel('Reset code', { exact: true }).fill(CODE);
  await page
    .getByLabel('New password', { exact: true })
    .fill('MissingSpecialPassword42');
  await page
    .getByLabel('Confirm password', { exact: true })
    .fill('MissingSpecialPassword42');
  await page
    .getByRole('button', { name: 'Reset password', exact: true })
    .click();
  await expect(page.getByRole('alert')).toContainText(
    /At least one special character/,
  );
  await expect(
    page.getByLabel('New password', { exact: true }),
  ).toHaveAttribute('aria-invalid', 'true');
  expect(backend.calls).toEqual([]);
  expect(backend.api.requests).toEqual([]);
});

test('existing accounts can sign in with an eight-character password that does not meet new-password rules', async ({
  page,
}) => {
  const backend = await registrationBackend(page);
  const oldPassword = 'OldPass1';
  backend.accounts.set('existing@example.com', {
    password: oldPassword,
    confirmed: true,
  });
  await page.goto('/sign-in');
  await page.getByLabel('Email', { exact: true }).fill('existing@example.com');
  await page.getByLabel('Password', { exact: true }).fill(oldPassword);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(
    page.getByRole('heading', {
      name: "Let's make sense of your dental costs.",
    }),
  ).toBeVisible();
  expect(backend.calls).toEqual([
    {
      operation: 'InitiateAuth',
      body: {
        AuthFlow: 'USER_PASSWORD_AUTH',
        ClientId: CLIENT_ID,
        AuthParameters: {
          USERNAME: 'existing@example.com',
          PASSWORD: oldPassword,
        },
      },
    },
  ]);
});

test('registration uses the public Cognito client and keeps credentials out of storage, URLs, logs and the application API', async ({
  page,
}) => {
  const backend = await registrationBackend(page);
  const consoleMessages: string[] = [];
  page.on('console', (message) => consoleMessages.push(message.text()));
  await createAccount(page, 'NEW.User@Example.COM');
  expect(backend.calls).toEqual([
    {
      operation: 'SignUp',
      body: {
        ClientId: CLIENT_ID,
        Username: EMAIL,
        Password: PASSWORD,
        UserAttributes: [{ Name: 'email', Value: EMAIL }],
      },
    },
  ]);
  expect(backend.api.requests).toEqual([]);
  expect(backend.unexpected).toEqual([]);
  const storage = await storedData(page);
  for (const sensitive of [
    EMAIL,
    PASSWORD,
    CODE,
    'test-refresh',
    'test-access',
  ]) {
    expect(storage).not.toContain(sensitive);
    expect(page.url()).not.toContain(sensitive);
    expect(consoleMessages.join('\n')).not.toContain(sensitive);
  }
  // Creating an account does not authenticate it or reveal protected app pages.
  await page.goto('/options');
  await expect(page).toHaveURL(/\/sign-in$/);
  expect(backend.api.requests).toEqual([]);
});

test('duplicate registration gives a useful message without exposing raw Cognito errors', async ({
  page,
}) => {
  const backend = await registrationBackend(page);
  await page.goto('/sign-in?mode=create');
  await fillRegistration(page, 'existing@example.com');
  await page
    .getByRole('button', { name: 'Create account', exact: true })
    .click();
  await expect(page.getByRole('alert')).toContainText(
    /already|exists|sign(?:ing)? in/i,
  );
  await expect(page.getByRole('alert')).not.toContainText(
    /UsernameExistsException|raw service message/,
  );
  expect(
    backend.calls.filter((call) => call.operation === 'SignUp'),
  ).toHaveLength(1);
  expect(await storedData(page)).not.toContain(PASSWORD);
  await expect(page).toHaveURL(/mode=create/);
});

test('incorrect and expired verification codes keep the user signed out; a correct code permits explicit sign-in', async ({
  page,
}) => {
  const backend = await registrationBackend(page);
  await createAccount(page);
  const code = page.getByLabel('Verification code', { exact: true });
  const verify = () =>
    page.getByRole('button', { name: 'Verify email', exact: true });
  await code.fill('000000');
  await verify().click();
  await expect(page.getByRole('alert')).toContainText(
    /incorrect|invalid|does not match/i,
  );
  await expect(page).toHaveURL(/mode=verify/);
  expect(backend.accounts.get(EMAIL)?.confirmed).toBe(false);
  await code.fill('222222');
  await verify().click();
  await expect(page.getByRole('alert')).toContainText(/expired/i);
  await code.fill(CODE);
  await verify().click();
  await expect(page).toHaveURL(/\/sign-in$/);
  await expect(page.getByRole('status')).toContainText(
    'Email verified. Sign in to continue.',
  );
  expect(backend.accounts.get(EMAIL)?.confirmed).toBe(true);
  expect(
    backend.calls.filter((call) => call.operation === 'ConfirmSignUp'),
  ).toHaveLength(3);
  expect(backend.calls.some((call) => call.operation === 'InitiateAuth')).toBe(
    false,
  );
  expect(await storedData(page)).not.toContain('test-refresh');
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(
    page.getByRole('heading', {
      name: "Let's make sense of your dental costs.",
    }),
  ).toBeVisible();
  expect(await storedData(page)).not.toContain(PASSWORD);
});

test('unconfirmed sign-in leads to email verification and never creates an authenticated session', async ({
  page,
}) => {
  const backend = await registrationBackend(page);
  backend.accounts.set(EMAIL, { password: PASSWORD, confirmed: false });
  await page.goto('/options');
  await expect(page).toHaveURL(/\/sign-in$/);
  await page.getByLabel('Email', { exact: true }).fill(EMAIL);
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText(/confirm|verif/i);
  await page.getByRole('button', { name: 'Verify email', exact: true }).click();
  await expect(page).toHaveURL(/mode=verify/);
  await expect(page.getByLabel('Email', { exact: true })).toHaveValue(EMAIL);
  expect(await storedData(page)).not.toContain('test-refresh');
  expect(backend.api.requests).toEqual([]);
});

test('verification can be resumed after a reload without persisting the email or code', async ({
  page,
}) => {
  const backend = await registrationBackend(page);
  await createAccount(page);
  await page.getByLabel('Verification code', { exact: true }).fill(CODE);
  await page.reload();
  await expect(page.getByLabel('Email', { exact: true })).toHaveValue('');
  await expect(
    page.getByLabel('Verification code', { exact: true }),
  ).toHaveValue('');
  await page.getByLabel('Email', { exact: true }).fill(EMAIL);
  await page.getByLabel('Verification code', { exact: true }).fill(CODE);
  await page.getByRole('button', { name: 'Verify email', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Email verified.');
  expect(backend.accounts.get(EMAIL)?.confirmed).toBe(true);
});

test('resend enforces a cooldown after sign-up, successful resend and Cognito throttling', async ({
  page,
}) => {
  const start = new Date('2030-01-01T12:00:00Z');
  await page.clock.install({ time: start });
  await page.clock.pauseAt(new Date(start.getTime() + 1_000));
  const backend = await registrationBackend(page);
  await createAccount(page);
  const resend = page.getByRole('button', {
    name: /Resend verification code/i,
  });
  await expect(resend).toBeDisabled();
  await page.clock.fastForward(59_000);
  await expect(resend).toBeDisabled();
  expect(
    backend.calls.filter((call) => call.operation === 'ResendConfirmationCode'),
  ).toHaveLength(0);
  await page.clock.fastForward(1_001);
  await expect(resend).toBeEnabled();
  await resend.click();
  await expect(resend).toBeDisabled();
  expect(
    backend.calls.filter((call) => call.operation === 'ResendConfirmationCode'),
  ).toEqual([
    {
      operation: 'ResendConfirmationCode',
      body: { ClientId: CLIENT_ID, Username: EMAIL },
    },
  ]);
  await page.clock.fastForward(60_001);
  backend.failures.push({
    operation: 'ResendConfirmationCode',
    code: 'TooManyRequestsException',
  });
  await resend.click();
  await expect(page.getByRole('alert')).toContainText(
    /too many|wait|try again later/i,
  );
  await expect(resend).toBeDisabled();
  expect(
    backend.calls.filter((call) => call.operation === 'ResendConfirmationCode'),
  ).toHaveLength(2);
  expect(await storedData(page)).not.toContain(PASSWORD);
});

test('registration prevents duplicate submission while waiting for Cognito', async ({
  page,
}) => {
  const backend = await registrationBackend(page);
  let release!: () => void;
  backend.holdSignUp = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.goto('/sign-in?mode=create');
  await fillRegistration(page);
  await page
    .getByRole('button', { name: 'Create account', exact: true })
    .click();
  await expect.poll(() => backend.calls.length).toBe(1);
  await expect(page.locator('button[type=submit]')).toBeDisabled();
  await page.keyboard.press('Enter');
  expect(backend.calls).toHaveLength(1);
  release();
  await expect(page).toHaveURL(/mode=verify/);
});

test('registration network failures leave the form retryable without authenticating', async ({
  page,
}) => {
  const backend = await registrationBackend(page);
  backend.abortNextSignUp = true;
  await page.goto('/sign-in?mode=create');
  await fillRegistration(page);
  await page
    .getByRole('button', { name: 'Create account', exact: true })
    .click();
  await expect(page.getByRole('alert')).toContainText(
    /connection|reach|network/i,
  );
  await expect(
    page.getByRole('button', { name: 'Create account', exact: true }),
  ).toBeEnabled();
  expect(await storedData(page)).not.toContain('test-refresh');
  await page
    .getByRole('button', { name: 'Create account', exact: true })
    .click();
  await expect(page).toHaveURL(/mode=verify/);
  expect(
    backend.calls.filter((call) => call.operation === 'SignUp'),
  ).toHaveLength(2);
});

test('forgot password resets through Cognito and preserves normal sign-in', async ({
  page,
}) => {
  const backend = await registrationBackend(page);
  const nextPassword = 'Another-Fictional-Password-42';
  await page.goto('/sign-in');
  await page.getByRole('button', { name: 'Forgot password?' }).click();
  await page.getByLabel('Email', { exact: true }).fill('existing@example.com');
  await page
    .getByRole('button', { name: 'Send reset code', exact: true })
    .click();
  await expect(page).toHaveURL(/mode=reset/);
  await page.getByLabel('Reset code', { exact: true }).fill('000000');
  await page.getByLabel('New password', { exact: true }).fill(nextPassword);
  await page.getByLabel('Confirm password', { exact: true }).fill(nextPassword);
  await page
    .getByRole('button', { name: 'Reset password', exact: true })
    .click();
  await expect(page.getByRole('alert')).toContainText(
    /incorrect|invalid|does not match/i,
  );
  await page.getByLabel('Reset code', { exact: true }).fill(CODE);
  await page
    .getByRole('button', { name: 'Reset password', exact: true })
    .click();
  await expect(page).toHaveURL(/\/sign-in$/);
  expect(backend.accounts.get('existing@example.com')?.password).toBe(
    nextPassword,
  );
  expect(await storedData(page)).not.toContain(nextPassword);
  expect(backend.calls.some((call) => call.operation === 'InitiateAuth')).toBe(
    false,
  );
  await page.getByLabel('Password', { exact: true }).fill(nextPassword);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(
    page.getByRole('heading', {
      name: "Let's make sense of your dental costs.",
    }),
  ).toBeVisible();
  expect(backend.unexpected).toEqual([]);
});

test('existing accounts still reject incorrect credentials and sign in with the correct password', async ({
  page,
}) => {
  const backend = await registrationBackend(page);
  await page.goto('/sign-in');
  await page.getByLabel('Email', { exact: true }).fill('existing@example.com');
  await page
    .getByLabel('Password', { exact: true })
    .fill('Incorrect-Password-42');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText(
    'Email or password is incorrect.',
  );
  expect(await storedData(page)).not.toContain('test-refresh');
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(
    page.getByRole('heading', {
      name: "Let's make sense of your dental costs.",
    }),
  ).toBeVisible();
  expect(
    backend.calls.filter((call) => call.operation === 'InitiateAuth'),
  ).toHaveLength(2);
});

test('pending sign-in disables account-mode switches and cannot be overwritten by registration', async ({
  page,
}) => {
  const backend = await registrationBackend(page);
  backend.accounts.set(EMAIL, { password: PASSWORD, confirmed: false });
  await page.goto('/sign-in');
  await page.getByLabel('Email', { exact: true }).fill(EMAIL);
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText(/confirm|verif/i);
  await expect(
    page.getByRole('button', { name: 'Verify email', exact: true }),
  ).toBeVisible();

  // Retrying after another tab verifies the account must keep this form stable
  // until Cognito returns, including the recovery controls from the first attempt.
  backend.accounts.get(EMAIL)!.confirmed = true;
  let release!: () => void;
  backend.holdInitiateAuth = new Promise<void>((resolve) => {
    release = resolve;
  });
  try {
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await expect
      .poll(
        () =>
          backend.calls.filter((call) => call.operation === 'InitiateAuth')
            .length,
      )
      .toBe(2);
    for (const name of [
      'Create an account',
      'Forgot password?',
      'Already have a verification code?',
      'Verify email',
    ]) {
      const switchButton = page.getByRole('button', { name, exact: true });
      await expect(switchButton).toBeDisabled();
      await switchButton.evaluate((element) =>
        (element as HTMLButtonElement).click(),
      );
    }
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/\/sign-in$/);
    await expect(
      page.getByRole('heading', {
        name: 'Sign in to continue your saved plans.',
      }),
    ).toBeVisible();
    await expect(
      page.getByLabel('Confirm password', { exact: true }),
    ).toHaveCount(0);
    expect(
      backend.calls.filter((call) => call.operation === 'InitiateAuth'),
    ).toHaveLength(2);
    expect(backend.calls.some((call) => call.operation === 'SignUp')).toBe(
      false,
    );
    expect(backend.api.requests).toEqual([]);
  } finally {
    backend.holdInitiateAuth = null;
    release();
  }
  await expect(
    page.getByRole('heading', {
      name: "Let's make sense of your dental costs.",
    }),
  ).toBeVisible();
});

for (const deliveryFailure of [
  { code: 'LimitExceededException', message: /too many|wait/i },
  { code: 'CodeDeliveryFailureException', message: /could not send|new code/i },
]) {
  test(`registration recovers from ${deliveryFailure.code} through verification without signing in`, async ({
    page,
  }) => {
    const backend = await registrationBackend(page);
    backend.failures.push({ operation: 'SignUp', code: deliveryFailure.code });
    await createAccount(page);
    await expect(page.getByRole('status')).toContainText(
      deliveryFailure.message,
    );
    await expect(page.getByRole('status')).not.toContainText(
      'raw service message',
    );
    expect(backend.accounts.get(EMAIL)?.confirmed).toBe(false);
    expect(
      backend.calls.some((call) => call.operation === 'InitiateAuth'),
    ).toBe(false);
    expect(backend.api.requests).toEqual([]);
    expect(await storedData(page)).not.toContain('test-refresh');
    await page.getByLabel('Verification code', { exact: true }).fill(CODE);
    await page
      .getByRole('button', { name: 'Verify email', exact: true })
      .click();
    await expect(page.getByRole('status')).toContainText(
      'Email verified. Sign in to continue.',
    );
    expect(backend.accounts.get(EMAIL)?.confirmed).toBe(true);
    expect(
      backend.calls.filter((call) => call.operation === 'SignUp'),
    ).toHaveLength(1);
    expect(
      backend.calls.some((call) => call.operation === 'InitiateAuth'),
    ).toBe(false);
  });
}

test('a SignUp response marked confirmed still cannot create an authenticated session', async ({
  page,
}) => {
  const backend = await registrationBackend(page);
  backend.signupUserConfirmed = true;
  await createAccount(page);
  expect(backend.accounts.get(EMAIL)?.confirmed).toBe(true);
  expect(backend.calls.map((call) => call.operation)).toEqual(['SignUp']);
  expect(backend.api.requests).toEqual([]);
  expect(await storedData(page)).not.toContain('test-refresh');
  await page.goto('/options');
  await expect(page).toHaveURL(/\/sign-in$/);
  expect(backend.api.requests).toEqual([]);
});

test('public authentication forms are accessible and fit a 360px viewport', async ({
  page,
}) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 360, height: 800 });
  await registrationBackend(page);
  for (const mode of ['create', 'verify', 'forgot', 'reset']) {
    await page.goto(`/sign-in?mode=${mode}`);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await expect(page.getByLabel('Email', { exact: true })).toBeVisible();
  }
});
