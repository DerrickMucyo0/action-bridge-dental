/** Browser rules for choosing a new password; existing-password sign-in stays unchanged. */
const SPECIAL_CHARACTERS = '^$*.[]{}()?"!@#%&/\\,><\':;|_~`=+-';

export function passwordRequirements(value: string) {
  return [
    {
      id: 'minimumLength',
      label: 'At least 12 characters',
      met: value.length >= 12,
    },
    {
      id: 'maximumLength',
      label: 'No more than 256 characters',
      met: value.length <= 256,
    },
    {
      id: 'uppercase',
      label: 'At least one uppercase letter (A–Z)',
      met: /[A-Z]/.test(value),
    },
    {
      id: 'lowercase',
      label: 'At least one lowercase letter (a–z)',
      met: /[a-z]/.test(value),
    },
    {
      id: 'number',
      label: 'At least one number (0–9)',
      met: /[0-9]/.test(value),
    },
    {
      id: 'special',
      label: 'At least one special character (for example, !, @ or #)',
      met: Array.from(value).some((character) =>
        SPECIAL_CHARACTERS.includes(character),
      ),
    },
    {
      id: 'whitespace',
      label: 'No spaces or whitespace',
      met: !/\s/.test(value),
    },
  ];
}

export function missingPasswordRequirements(value: string): string[] {
  return passwordRequirements(value)
    .filter((requirement) => !requirement.met)
    .map((requirement) => requirement.label);
}

export function passwordValidationMessage(value: string): string | null {
  const missing = missingPasswordRequirements(value);
  return missing.length ? `Password needs: ${missing.join('; ')}.` : null;
}
