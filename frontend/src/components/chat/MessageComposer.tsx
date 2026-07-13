import { useState, type FormEvent, type JSX, type KeyboardEvent } from 'react';
import { Button } from '../ui/Button';

export interface MessageComposerProps {
  onSend: (content: string) => Promise<void> | void;
  disabled?: boolean;
}

const MAX_LENGTH = 4000;

/** Message composer: submits on Enter (Shift+Enter for a newline), disables
 * itself while a send is in flight, and surfaces a live character count as
 * the 4000-char limit (R36) approaches/is exceeded. Never a silent no-op —
 * the submit button always reflects `disabled`/loading state. */
export function MessageComposer({ onSend, disabled = false }: MessageComposerProps): JSX.Element {
  const [content, setContent] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const trimmedLength = content.trim().length;
  const isOverLimit = content.length > MAX_LENGTH;
  const canSubmit = !disabled && !isSubmitting && trimmedLength > 0 && !isOverLimit;

  async function submit(): Promise<void> {
    if (!canSubmit) {
      return;
    }
    setIsSubmitting(true);
    try {
      await onSend(content);
      setContent('');
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleSubmit(event: FormEvent): void {
    event.preventDefault();
    void submit();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void submit();
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2 border-t border-[var(--color-border)] pt-3">
      <label htmlFor="message-composer" className="sr-only">
        Message
      </label>
      <textarea
        id="message-composer"
        value={content}
        onChange={(event) => setContent(event.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled || isSubmitting}
        rows={2}
        placeholder="Write a message… (Enter to send, Shift+Enter for a new line)"
        aria-describedby="message-composer-hint"
        aria-invalid={isOverLimit ? true : undefined}
        className="block w-full resize-none rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] transition-colors duration-150 ease-out focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] disabled:cursor-not-allowed disabled:bg-[var(--color-surface-raised)] disabled:text-[var(--color-text-tertiary)]"
      />
      <div className="flex items-center justify-between gap-3">
        <p
          id="message-composer-hint"
          className={`text-caption ${isOverLimit ? 'text-[var(--color-danger)]' : 'text-[var(--color-text-tertiary)]'}`}
        >
          {content.length}/{MAX_LENGTH}
        </p>
        <Button type="submit" isLoading={isSubmitting} loadingText="Sending…" disabled={!canSubmit} className="w-auto">
          Send
        </Button>
      </div>
    </form>
  );
}
