import { forwardRef, type InputHTMLAttributes } from 'react';

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  /** Marks the field as invalid — draws the danger border. Prefer using
   * `FormField`, which wires this automatically from its `error` prop. */
  hasError?: boolean;
}

const BASE_CLASSES =
  'mt-1 block w-full rounded-md border bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-primary)] ' +
  'placeholder:text-[var(--color-text-tertiary)] transition-colors duration-150 ease-out focus:outline-none ' +
  'focus:ring-2 focus:ring-offset-0 disabled:cursor-not-allowed disabled:bg-[var(--color-surface-raised)] ' +
  'disabled:text-[var(--color-text-tertiary)]';

/** Shared text input primitive per architecture/design-tokens.md §6. Use via
 * `FormField` for the standard label + input + hint/error layout. */
export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { hasError = false, className, ...rest },
  ref,
) {
  const stateClasses = hasError
    ? 'border-[var(--color-danger)] focus:border-[var(--color-danger)] focus:ring-[var(--color-danger)]'
    : 'border-[var(--color-border)] focus:border-[var(--color-accent)] focus:ring-[var(--color-accent)]';

  return <input ref={ref} className={[BASE_CLASSES, stateClasses, className].filter(Boolean).join(' ')} {...rest} />;
});
