import { forwardRef, type TextareaHTMLAttributes } from 'react';

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  /** Marks the field as invalid — draws the danger border. Mirrors
   * `Input`'s `hasError`; callers wire this from their own validation (e.g.
   * the composer's over-limit state) since validation rules differ per
   * consumer. */
  hasError?: boolean;
}

const BASE_CLASSES =
  'block w-full resize-none rounded-md border bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-primary)] ' +
  'placeholder:text-[var(--color-text-tertiary)] transition-colors duration-150 ease-out focus:outline-none ' +
  'focus:ring-2 focus:ring-offset-0 disabled:cursor-not-allowed disabled:bg-[var(--color-surface-raised)] ' +
  'disabled:text-[var(--color-text-tertiary)]';

/** Shared multi-line text input primitive per DESIGN_SYSTEM.md §3.3 —
 * extracted from the styles previously duplicated across the message
 * composer and the message-edit box, matching `Input`'s border/focus/
 * disabled treatment and the inset focus-ring recipe (0 offset, per
 * architecture/design-tokens.md §12). Callers own their own value/length
 * validation (e.g. the 4000-char message-content limit) and pass `hasError`
 * to reflect it — the primitive itself has no opinion on content rules. */
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { hasError = false, rows = 2, className, ...rest },
  ref,
) {
  const stateClasses = hasError
    ? 'border-[var(--color-danger)] focus:border-[var(--color-danger)] focus:ring-[var(--color-danger)]'
    : 'border-[var(--color-border)] focus:border-[var(--color-accent)] focus:ring-[var(--color-accent)]';

  return (
    <textarea ref={ref} rows={rows} className={[BASE_CLASSES, stateClasses, className].filter(Boolean).join(' ')} {...rest} />
  );
});
