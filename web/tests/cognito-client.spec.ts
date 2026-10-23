import { expect, test } from '@playwright/test';
import { CognitoError, createCognitoClient } from '../src/services/cognito';

const email = 'synthetic-registration@example.com';
const password = 'FictionalPassword123';
const clientId = 'syntheticpublicclient';
const rawMessage = 'Internal detail that must never appear in the interface';

type RecordedRequest = {
  url: string;
  target: string;
  body: Record<string, unknown>;
};
type Reply = { body: unknown; status?: number };

function mockedClient(replies: Reply[]) {
  const requests: RecordedRequest[] = [];
  const fetchImpl: typeof fetch = async (input, init) => {
    const headers = new Headers(init?.headers);
    requests.push({
      url: String(input),
      target: headers.get('X-Amz-Target') ?? '',
      body: JSON.parse(String(init?.body)) as Record<string, unknown>,
    });
    expect(init?.method).toBe('POST');
    expect(headers.get('Content-Type')).toBe('application/x-amz-json-1.1');
    const reply = replies.shift();
    if (!reply) throw new Error('Unexpected Cognito request');
    return new Response(JSON.stringify(reply.body), {
      status: reply.status ?? 200,
      headers: { 'Content-Type': 'application/x-amz-json-1.1' },
    });
  };
  return {
    client: createCognitoClient({
      region: 'us-east-2',
      clientId,
      now: () => 1_000,
      fetchImpl,
    }),
    requests,
  };
}

function failure(code: string): Reply {
  return {
    status: 400,
    body: { __type: `com.amazon.cognito#${code}`, message: rawMessage },
  };
}

test('public registration sends only email and password to Cognito and returns no session', async () => {
  const { client, requests } = mockedClient([
    {
      body: {
        UserConfirmed: false,
        UserSub: 'synthetic-user',
        CodeDeliveryDetails: { Destination: 's***@e***.com' },
        Session: 'must-not-be-used-for-auto-sign-in',
      },
    },
  ]);
  await expect(client.signUp(email, password)).resolves.toEqual({
    confirmed: false,
    destination: 's***@e***.com',
  });
  expect(requests).toEqual([
    {
      url: 'https://cognito-idp.us-east-2.amazonaws.com/',
      target: 'AWSCognitoIdentityProviderService.SignUp',
      body: {
        ClientId: clientId,
        Username: email,
        Password: password,
        UserAttributes: [{ Name: 'email', Value: email }],
      },
    },
  ]);
});

test('confirmation never moves an existing email alias or creates authentication tokens', async () => {
  const { client, requests } = mockedClient([
    { body: { Session: 'ignored-confirmation-session' } },
  ]);
  await expect(client.confirmSignUp(email, '123456')).resolves.toBeUndefined();
  expect(requests).toEqual([
    {
      url: 'https://cognito-idp.us-east-2.amazonaws.com/',
      target: 'AWSCognitoIdentityProviderService.ConfirmSignUp',
      body: {
        ClientId: clientId,
        Username: email,
        ConfirmationCode: '123456',
        ForceAliasCreation: false,
      },
    },
  ]);
});

test('verification resend uses the public operation without an automatic retry', async () => {
  const { client, requests } = mockedClient([
    { body: { CodeDeliveryDetails: { Destination: 's***@e***.com' } } },
    failure('TooManyRequestsException'),
  ]);
  await expect(client.resendConfirmationCode(email)).resolves.toEqual({
    destination: 's***@e***.com',
  });
  await expect(client.resendConfirmationCode(email)).rejects.toMatchObject({
    code: 'TooManyRequestsException',
    message: 'Too many attempts. Wait a moment and try again.',
  });
  expect(requests).toHaveLength(2);
  for (const request of requests) {
    expect(request.target).toBe(
      'AWSCognitoIdentityProviderService.ResendConfirmationCode',
    );
    expect(request.body).toEqual({ ClientId: clientId, Username: email });
  }
});

test('unconfirmed users cannot sign in; verified users use the existing sign-in flow', async () => {
  const { client, requests } = mockedClient([
    failure('UserNotConfirmedException'),
    { body: {} },
    {
      body: {
        AuthenticationResult: {
          AccessToken: 'synthetic-access',
          RefreshToken: 'synthetic-refresh',
          ExpiresIn: 3600,
        },
      },
    },
  ]);
  await expect(client.signIn(email, password)).rejects.toMatchObject({
    code: 'UserNotConfirmedException',
    message: expect.stringContaining('Verify your email before signing in'),
  });
  await client.confirmSignUp(email, '123456');
  await expect(client.signIn(email, password)).resolves.toEqual({
    kind: 'signed_in',
    tokens: {
      accessToken: 'synthetic-access',
      refreshToken: 'synthetic-refresh',
      expiresAt: 3_601_000,
    },
  });
  expect(requests[0]?.body).toEqual({
    AuthFlow: 'USER_PASSWORD_AUTH',
    ClientId: clientId,
    AuthParameters: { USERNAME: email, PASSWORD: password },
  });
  expect(requests[2]?.body).toEqual(requests[0]?.body);
});

test('password recovery remains public and requires the received code without signing in', async () => {
  const { client, requests } = mockedClient([
    { body: { CodeDeliveryDetails: { Destination: 's***@e***.com' } } },
    { body: {} },
  ]);
  await expect(client.forgotPassword(email)).resolves.toEqual({
    destination: 's***@e***.com',
  });
  await expect(
    client.confirmForgotPassword(email, '123456', password),
  ).resolves.toBeUndefined();
  expect(requests.map(({ target, body }) => ({ target, body }))).toEqual([
    {
      target: 'AWSCognitoIdentityProviderService.ForgotPassword',
      body: { ClientId: clientId, Username: email },
    },
    {
      target: 'AWSCognitoIdentityProviderService.ConfirmForgotPassword',
      body: {
        ClientId: clientId,
        Username: email,
        ConfirmationCode: '123456',
        Password: password,
      },
    },
  ]);
});

test('password recovery does not disclose a missing account', async () => {
  const { client } = mockedClient([failure('UserNotFoundException')]);
  await expect(client.forgotPassword(email)).resolves.toEqual({});
});

for (const [code, message] of [
  ['UsernameExistsException', /Try signing in, verifying your email/],
  ['InvalidPasswordException', /12\+ characters/],
  ['InvalidParameterException', /Check your email address/],
  ['CodeDeliveryFailureException', /request a new code/],
  ['InvalidEmailRoleAccessPolicyException', /Email delivery is unavailable/],
  ['LimitExceededException', /return to email verification/],
  ['NotAuthorizedException', /Account registration is unavailable/],
  ['ResourceNotFoundException', /account service is unavailable/],
  ['UnknownServerFailure', /request could not be completed/],
] as const) {
  test(`registration handles ${code} without exposing Cognito details`, async () => {
    const { client, requests } = mockedClient([failure(code)]);
    await expect(client.signUp(email, password)).rejects.toMatchObject({
      name: 'CognitoError',
      code,
      message: expect.stringMatching(message),
    });
    expect(requests).toHaveLength(1);
  });
}

for (const [code, message] of [
  ['CodeMismatchException', /code is incorrect/],
  ['ExpiredCodeException', /code has expired.*Request a new code/],
  ['TooManyFailedAttemptsException', /Wait a while/],
  ['AliasExistsException', /Try signing in or resetting your password/],
] as const) {
  test(`confirmation handles ${code} safely`, async () => {
    const { client } = mockedClient([failure(code)]);
    await expect(client.confirmSignUp(email, '123456')).rejects.toMatchObject({
      code,
      message: expect.stringMatching(message),
    });
  });
}

test('existing new-password challenges, refresh, and revocation are preserved', async () => {
  const { client, requests } = mockedClient([
    {
      body: {
        ChallengeName: 'NEW_PASSWORD_REQUIRED',
        Session: 'synthetic-session',
      },
    },
    {
      body: {
        AuthenticationResult: {
          AccessToken: 'synthetic-access',
          RefreshToken: 'synthetic-refresh',
          ExpiresIn: 60,
        },
      },
    },
    {
      body: {
        AuthenticationResult: {
          AccessToken: 'synthetic-refreshed',
          ExpiresIn: 120,
        },
      },
    },
    { body: {} },
  ]);
  await expect(client.signIn(email, password)).resolves.toEqual({
    kind: 'new_password_required',
    session: 'synthetic-session',
  });
  await expect(
    client.completeNewPassword(email, password, 'synthetic-session'),
  ).resolves.toEqual({
    accessToken: 'synthetic-access',
    refreshToken: 'synthetic-refresh',
    expiresAt: 61_000,
  });
  await expect(client.refresh('synthetic-refresh')).resolves.toEqual({
    accessToken: 'synthetic-refreshed',
    refreshToken: 'synthetic-refresh',
    expiresAt: 121_000,
  });
  await expect(client.revoke('synthetic-refresh')).resolves.toBeUndefined();
  expect(requests[1]?.body).toEqual({
    ChallengeName: 'NEW_PASSWORD_REQUIRED',
    ClientId: clientId,
    Session: 'synthetic-session',
    ChallengeResponses: { USERNAME: email, NEW_PASSWORD: password },
  });
  expect(requests[2]?.body).toEqual({
    AuthFlow: 'REFRESH_TOKEN_AUTH',
    ClientId: clientId,
    AuthParameters: { REFRESH_TOKEN: 'synthetic-refresh' },
  });
  expect(requests[3]?.body).toEqual({
    Token: 'synthetic-refresh',
    ClientId: clientId,
  });
});

for (const code of [
  'NotAuthorizedException',
  'UserNotFoundException',
  'PasswordResetRequiredException',
]) {
  test(`existing sign-in handles ${code} without exposing raw messages`, async () => {
    const { client } = mockedClient([failure(code)]);
    try {
      await client.signIn(email, password);
      throw new Error('Expected sign-in to fail');
    } catch (error) {
      expect(error).toBeInstanceOf(CognitoError);
      expect((error as CognitoError).code).toBe(code);
      expect((error as CognitoError).message).not.toContain(rawMessage);
    }
  });
}

test('a network failure is safe and never retried automatically', async () => {
  let calls = 0;
  const client = createCognitoClient({
    region: 'us-east-2',
    clientId,
    fetchImpl: async () => {
      calls += 1;
      throw new Error(rawMessage);
    },
  });
  await expect(client.signUp(email, password)).rejects.toMatchObject({
    code: 'NETWORK',
    message: 'Can’t reach the account service. Check your connection.',
  });
  expect(calls).toBe(1);
});

for (const body of [null, [], {}, { UserConfirmed: 'false' }]) {
  test(`malformed signup response ${JSON.stringify(body)} never reports success`, async () => {
    const { client } = mockedClient([{ body }]);
    await expect(client.signUp(email, password)).rejects.toMatchObject({
      code: 'BAD_RESPONSE',
    });
  });
}
