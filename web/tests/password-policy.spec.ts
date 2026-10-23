import { expect, test } from '@playwright/test';
import {
  missingPasswordRequirements,
  passwordRequirements,
  passwordValidationMessage,
} from '../src/features/auth/password-policy';

// Fictional values exercise the local policy without making Cognito requests.
const validPassword = 'Abcdefghi1!x';

for (const [description, password] of [
  ['the 12-character minimum', validPassword],
  ['the 256-character maximum', `Aa1!${'x'.repeat(252)}`],
  ['hyphen as a special character', 'Valid-Test-Password-42'],
] as const) {
  test(`new password accepts ${description}`, () => {
    expect(
      passwordRequirements(password).every((requirement) => requirement.met),
    ).toBe(true);
    expect(missingPasswordRequirements(password)).toEqual([]);
    expect(passwordValidationMessage(password)).toBeNull();
  });
}

for (const invalid of [
  {
    description: '11 characters',
    password: 'Abcdefgh1!x',
    missing: 'At least 12 characters',
  },
  {
    description: '257 characters',
    password: `Aa1!${'x'.repeat(253)}`,
    missing: 'No more than 256 characters',
  },
  {
    description: 'no uppercase letter',
    password: 'lowercase-password-42',
    missing: 'At least one uppercase letter (A–Z)',
  },
  {
    description: 'no lowercase letter',
    password: 'UPPERCASE-PASSWORD-42',
    missing: 'At least one lowercase letter (a–z)',
  },
  {
    description: 'no number',
    password: 'Missing-Number-Password',
    missing: 'At least one number (0–9)',
  },
  {
    description: 'no special character',
    password: 'MissingSpecialPassword42',
    missing: 'At least one special character (for example, !, @ or #)',
  },
] as const) {
  test(`new password rejects ${invalid.description} and names only its missing requirement`, () => {
    expect(missingPasswordRequirements(invalid.password)).toEqual([
      invalid.missing,
    ]);
    expect(passwordValidationMessage(invalid.password)).toBe(
      `Password needs: ${invalid.missing}.`,
    );
  });
}

test('every supported ASCII punctuation character can satisfy the special-character requirement', () => {
  const punctuation = Array.from({ length: 94 }, (_, index) =>
    String.fromCharCode(index + 33),
  ).filter((character) => !/[a-zA-Z0-9]/.test(character));
  expect(punctuation).toHaveLength(32);
  for (const character of punctuation) {
    expect(
      passwordValidationMessage(`ValidPassword42${character}`),
      `punctuation ${character}`,
    ).toBeNull();
  }
});

for (const whitespace of [' ', '\t', '\n', '\r', '\u00a0']) {
  test(`new password rejects whitespace ${JSON.stringify(whitespace)}`, () => {
    expect(
      missingPasswordRequirements(`ValidPassword42!${whitespace}`),
    ).toEqual(['No spaces or whitespace']);
  });
}

for (const misleadingSymbol of [' ', '🦷', 'é', '—']) {
  test(`new password does not count ${JSON.stringify(misleadingSymbol)} as an AWS special character`, () => {
    expect(
      missingPasswordRequirements(`ValidPassword42${misleadingSymbol}`),
    ).toContain('At least one special character (for example, !, @ or #)');
  });
}

test('an empty password names every missing minimum and character requirement', () => {
  expect(missingPasswordRequirements('')).toEqual([
    'At least 12 characters',
    'At least one uppercase letter (A–Z)',
    'At least one lowercase letter (a–z)',
    'At least one number (0–9)',
    'At least one special character (for example, !, @ or #)',
  ]);
});
