import { passwordRequirements } from './password-policy';

export function PasswordRequirements({
  value,
  id,
}: {
  value: string;
  id: string;
}) {
  return (
    <ul
      id={id}
      className="si-hint si-password-requirements"
      aria-label="Password requirements"
      aria-live="polite"
    >
      {passwordRequirements(value).map((requirement) => (
        <li key={requirement.id}>
          {value ? (requirement.met ? 'Met' : 'Missing') : 'Required'}:{' '}
          {requirement.label}
        </li>
      ))}
    </ul>
  );
}
