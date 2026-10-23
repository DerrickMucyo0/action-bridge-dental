/**
 * Minimal Cognito client over HTTPS (no AWS SDK), shared design with the mobile app.
 * Uses a public app client (no secret). Registration and email confirmation never
 * establish a session; only the existing sign-in flow returns authentication tokens.
 */
export interface Tokens {
  accessToken: string;
  refreshToken: string;
  /** Epoch milliseconds when the access token expires. */
  expiresAt: number;
}

export type SignInResult =
  | { kind: 'signed_in'; tokens: Tokens }
  | { kind: 'new_password_required'; session: string };

export interface CodeDelivery {
  destination?: string;
}

export class CognitoError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = 'CognitoError';
  }
}

const FRIENDLY: Record<string, string> = {
  NotAuthorizedException: 'Email or password is incorrect.',
  UserNotFoundException: 'Email or password is incorrect.',
  PasswordResetRequiredException:
    'Reset your password using Forgot password, then sign in.',
  UserNotConfirmedException:
    'Verify your email before signing in. Enter your verification code or request a new one.',
  UsernameExistsException:
    'Unable to create an account with those details. Try signing in, verifying your email, or resetting your password.',
  AliasExistsException:
    'Unable to verify an account with those details. Try signing in or resetting your password.',
  TooManyRequestsException: 'Too many attempts. Wait a moment and try again.',
  TooManyFailedAttemptsException:
    'Too many attempts. Wait a while before trying again.',
  LimitExceededException:
    'Too many requests. Wait a while before trying again. If you just created an account, return to email verification to request a new code.',
  InvalidPasswordException:
    'That password does not meet the requirements (12+ characters, upper and lower case, a number).',
  PasswordHistoryPolicyViolationException:
    'Choose a password you have not used before.',
  InvalidParameterException:
    'Check your email address and the information entered, then try again. If the problem continues, contact support.',
  CodeMismatchException:
    'That verification code is incorrect. Check the code and try again.',
  ExpiredCodeException:
    'That verification code has expired. Request a new code and try again.',
  CodeDeliveryFailureException:
    'We could not send the email. Wait a moment and request a new code.',
  InvalidEmailRoleAccessPolicyException:
    'Email delivery is unavailable. Try again later or contact support.',
  ForbiddenException:
    'This request could not be completed. Wait a moment and try again.',
  ResourceNotFoundException:
    'The account service is unavailable. Try again later or contact support.',
  InternalErrorException:
    'The account service is temporarily unavailable. Try again later.',
};

type Json = Record<string, unknown>;

function asJson(value: unknown): Json {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Json)
    : {};
}

function errorMessage(target: string, code: string): string {
  if (target !== 'InitiateAuth' && code === 'NotAuthorizedException') {
    return target === 'SignUp'
      ? 'Account registration is unavailable. Try again later or contact support.'
      : 'This request could not be completed. Try signing in, or request a new code if your email is not verified.';
  }
  if (target !== 'InitiateAuth' && code === 'UserNotFoundException') {
    return 'This request could not be completed. Check your email address or try signing in.';
  }
  return (
    FRIENDLY[code] ?? 'The request could not be completed. Try again later.'
  );
}

function deliveryFrom(json: Json): CodeDelivery {
  const destination = asJson(json.CodeDeliveryDetails).Destination;
  return typeof destination === 'string' ? { destination } : {};
}

export function createCognitoClient({
  region,
  clientId,
  now = Date.now,
  fetchImpl = (...args) => fetch(...args),
}: {
  region: string;
  clientId: string;
  now?: () => number;
  fetchImpl?: typeof fetch;
}) {
  async function call(target: string, body: Json): Promise<Json> {
    let response: Response;
    try {
      response = await fetchImpl(
        `https://cognito-idp.${region}.amazonaws.com/`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/x-amz-json-1.1',
            'X-Amz-Target': `AWSCognitoIdentityProviderService.${target}`,
          },
          body: JSON.stringify(body),
        },
      );
    } catch {
      throw new CognitoError(
        'NETWORK',
        'Can’t reach the account service. Check your connection.',
      );
    }
    const json = asJson(await response.json().catch(() => ({})));
    if (!response.ok) {
      const code =
        String(json.__type ?? 'Unknown')
          .split('#')
          .pop() ?? 'Unknown';
      // Never display Cognito's raw message: it can contain internal configuration
      // details and user input. Keep the code for actionable UI recovery flows.
      throw new CognitoError(code, errorMessage(target, code));
    }
    return json;
  }

  function tokensFrom(result: unknown, previousRefresh?: string): Tokens {
    const r = asJson(result);
    if (typeof r.AccessToken !== 'string')
      throw new CognitoError('NO_TOKENS', 'Sign-in did not return a session.');
    return {
      accessToken: r.AccessToken,
      refreshToken:
        (typeof r.RefreshToken === 'string' ? r.RefreshToken : undefined) ??
        previousRefresh ??
        '',
      expiresAt: now() + Number(r.ExpiresIn ?? 3600) * 1000,
    };
  }

  return {
    async signUp(
      email: string,
      password: string,
    ): Promise<CodeDelivery & { confirmed: boolean }> {
      const json = await call('SignUp', {
        ClientId: clientId,
        Username: email,
        Password: password,
        UserAttributes: [{ Name: 'email', Value: email }],
      });
      if (typeof json.UserConfirmed !== 'boolean')
        throw new CognitoError(
          'BAD_RESPONSE',
          'The account service returned an unexpected response. Try signing in or verifying your email.',
        );
      return { confirmed: json.UserConfirmed, ...deliveryFrom(json) };
    },
    async confirmSignUp(email: string, code: string): Promise<void> {
      await call('ConfirmSignUp', {
        ClientId: clientId,
        Username: email,
        ConfirmationCode: code,
        // Never take an existing account's email alias during confirmation.
        ForceAliasCreation: false,
      });
    },
    async resendConfirmationCode(email: string): Promise<CodeDelivery> {
      return deliveryFrom(
        await call('ResendConfirmationCode', {
          ClientId: clientId,
          Username: email,
        }),
      );
    },
    async forgotPassword(email: string): Promise<CodeDelivery> {
      try {
        return deliveryFrom(
          await call('ForgotPassword', {
            ClientId: clientId,
            Username: email,
          }),
        );
      } catch (error) {
        // Match Cognito's user-existence protection if a pool returns this error.
        if (
          error instanceof CognitoError &&
          error.code === 'UserNotFoundException'
        )
          return {};
        throw error;
      }
    },
    async confirmForgotPassword(
      email: string,
      code: string,
      newPassword: string,
    ): Promise<void> {
      await call('ConfirmForgotPassword', {
        ClientId: clientId,
        Username: email,
        ConfirmationCode: code,
        Password: newPassword,
      });
    },
    async signIn(email: string, password: string): Promise<SignInResult> {
      const json = await call('InitiateAuth', {
        AuthFlow: 'USER_PASSWORD_AUTH',
        ClientId: clientId,
        AuthParameters: { USERNAME: email, PASSWORD: password },
      });
      if (json.ChallengeName === 'NEW_PASSWORD_REQUIRED')
        return { kind: 'new_password_required', session: String(json.Session) };
      if (json.ChallengeName)
        throw new CognitoError(
          String(json.ChallengeName),
          'This account needs an extra sign-in step the site does not support yet.',
        );
      return {
        kind: 'signed_in',
        tokens: tokensFrom(json.AuthenticationResult),
      };
    },
    async completeNewPassword(
      email: string,
      newPassword: string,
      session: string,
    ): Promise<Tokens> {
      const json = await call('RespondToAuthChallenge', {
        ChallengeName: 'NEW_PASSWORD_REQUIRED',
        ClientId: clientId,
        Session: session,
        ChallengeResponses: { USERNAME: email, NEW_PASSWORD: newPassword },
      });
      return tokensFrom(json.AuthenticationResult);
    },
    async refresh(refreshToken: string): Promise<Tokens> {
      const json = await call('InitiateAuth', {
        AuthFlow: 'REFRESH_TOKEN_AUTH',
        ClientId: clientId,
        AuthParameters: { REFRESH_TOKEN: refreshToken },
      });
      return tokensFrom(json.AuthenticationResult, refreshToken);
    },
    async revoke(refreshToken: string): Promise<void> {
      await call('RevokeToken', {
        Token: refreshToken,
        ClientId: clientId,
      }).catch(() => undefined);
    },
  };
}

export type CognitoClient = ReturnType<typeof createCognitoClient>;
