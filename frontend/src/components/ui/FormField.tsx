import type { InputHTMLAttributes, JSX, ReactNode } from 'react';
import { Input } from './Input';

export interface FormFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  id: string;
  label: ReactNode;
  /** Helper text shown below the input when there is no error. */
  hint?: string;
  /** Inline validation/error message. Rendered with `role="alert"` and wired
   * into the input's `aria-describedby`. */
  error?: string;
}

/** Shared label + input + hint/error primitive per
 * architecture/design-tokens.md §6. Wires `aria-describedby` to whichever of
 * the hint/error text is currently shown. */
export function FormField({ id, label, hint, error, ...inputProps }: FormFieldProps): JSX.Element {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [errorId, hintId].filter(Boolean).join(' ') || undefined;

  return (
    <div>
      <label htmlFor={id} className="block text-body font-medium text-[var(--color-text-primary)]">
        {label}
      </label>
      <Input
        id={id}
        hasError={Boolean(error)}
        aria-describedby={inputProps['aria-describedby'] ?? describedBy}
        aria-invalid={error ? true : undefined}
        {...inputProps}
      />
      {error ? (
        <p id={errorId} role="alert" className="mt-1 text-caption text-[var(--color-danger)]">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="mt-1 text-caption text-[var(--color-text-tertiary)]">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
