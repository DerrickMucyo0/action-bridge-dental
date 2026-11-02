import { expect, test } from '@playwright/test';
import { readConfig } from '../src/config';
import {
  createCognitoClient,
  type CognitoClient,
} from '../src/services/cognito';

const configured = {
  apiBaseUrl: 'https://api.test.invalid/staging',
  cognitoClientId: 'testclientid0123456789abcd',
  cognitoRegion: 'us-east-2',
};
for (const setting of [undefined, 'true', 'false']) {
  test(`public account setting ${String(setting)} preserves full mode or explicitly restricts it`, () => {
    const result = readConfig({
      ...configured,
      publicAccountActionsEnabled: setting,
    });
    expect(result.ok).toBe(true);
    if (result.ok)
      expect(result.config.publicAccountActionsEnabled).toBe(
        setting !== 'false',
      );
  });
}
for (const setting of ['', 'yes', '0', 'TRUE']) {
  test(`malformed public account setting ${JSON.stringify(setting)} fails configuration`, () => {
    const result = readConfig({
      ...configured,
      publicAccountActionsEnabled: setting,
    });
    expect(result.ok).toBe(false);
    if (!result.ok)
      expect(result.problems).toContain(
        'VITE_PUBLIC_ACCOUNT_ACTIONS_ENABLED must be true or false when set.',
      );
  });
}
for (const background of ['true', 'false'])
  for (const accounts of ['true', 'false']) {
    test(`public account setting ${accounts} is independent of background setting ${background}`, () => {
      const result = readConfig({
        ...configured,
        backgroundJobsEnabled: background,
        publicAccountActionsEnabled: accounts,
      });
      expect(result.ok).toBe(true);
      if (result.ok)
        expect(result.config).toMatchObject({
          backgroundJobsEnabled: background === 'true',
          publicAccountActionsEnabled: accounts === 'true',
        });
    });
  }

const blocked: [string, (client: CognitoClient) => Promise<unknown>][] = [
  [
    'SignUp',
    (client) => client.signUp('fictional@example.com', 'Fictional-Password-42'),
  ],
  [
    'ConfirmSignUp',
    (client) => client.confirmSignUp('fictional@example.com', '123456'),
  ],
  [
    'ResendConfirmationCode',
    (client) => client.resendConfirmationCode('fictional@example.com'),
  ],
  [
    'ForgotPassword',
    (client) => client.forgotPassword('fictional@example.com'),
  ],
  [
    'ConfirmForgotPassword',
    (client) =>
      client.confirmForgotPassword(
        'fictional@example.com',
        '123456',
        'Fictional-Password-42',
      ),
  ],
];
for (const [operation, invoke] of blocked) {
  test(`restricted account policy blocks ${operation} before Cognito transport`, async () => {
    let calls = 0;
    const client = createCognitoClient({
      region: 'us-east-2',
      clientId: configured.cognitoClientId,
      publicAccountActionsEnabled: false,
      fetchImpl: async () => {
        calls++;
        throw new Error('No network is authorized');
      },
    });
    await expect(invoke(client)).rejects.toMatchObject({
      code: 'FEATURE_UNAVAILABLE',
    });
    expect(calls).toBe(0);
  });
}

test('restricted policy retains sign-in, refresh and revocation transport', async () => {
  const calls: string[] = [];
  const client = createCognitoClient({
    region: 'us-east-2',
    clientId: configured.cognitoClientId,
    publicAccountActionsEnabled: false,
    fetchImpl: async (_url, options) => {
      calls.push(
        new Headers(options?.headers).get('X-Amz-Target')!.split('.').at(-1)!,
      );
      return new Response(
        JSON.stringify({
          AuthenticationResult: {
            AccessToken: 'synthetic-access',
            RefreshToken: 'synthetic-refresh',
            ExpiresIn: 3600,
          },
        }),
        { status: 200 },
      );
    },
  });
  await client.signIn('fictional@example.com', 'Fictional-Password-42');
  await client.refresh('synthetic-refresh');
  await client.revoke('synthetic-refresh');
  expect(calls).toEqual(['InitiateAuth', 'InitiateAuth', 'RevokeToken']);
});

test('restricted policy preserves the existing admin-created account new-password challenge', async () => {
  const calls: string[] = [];
  const client = createCognitoClient({
    region: 'us-east-2',
    clientId: configured.cognitoClientId,
    publicAccountActionsEnabled: false,
    fetchImpl: async (_url, options) => {
      const operation = new Headers(options?.headers)
        .get('X-Amz-Target')!
        .split('.')
        .at(-1)!;
      calls.push(operation);
      return new Response(
        JSON.stringify(
          operation === 'InitiateAuth'
            ? {
                ChallengeName: 'NEW_PASSWORD_REQUIRED',
                Session: 'synthetic-session',
              }
            : {
                AuthenticationResult: {
                  AccessToken: 'synthetic-access',
                  RefreshToken: 'synthetic-refresh',
                  ExpiresIn: 3600,
                },
              },
        ),
        { status: 200 },
      );
    },
  });
  await expect(
    client.signIn('fictional@example.com', 'Fictional-Password-42'),
  ).resolves.toEqual({
    kind: 'new_password_required',
    session: 'synthetic-session',
  });
  await client.completeNewPassword(
    'fictional@example.com',
    'Fictional-New-Password-42',
    'synthetic-session',
  );
  expect(calls).toEqual(['InitiateAuth', 'RespondToAuthChallenge']);
});
