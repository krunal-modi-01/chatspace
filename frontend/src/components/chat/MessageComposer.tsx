import {
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
  type JSX,
  type KeyboardEvent,
} from 'react';
import { type PendingAttachment, useMediaUploads } from '../../hooks/useMediaUploads';
import { formatBytes } from '../../utils/formatBytes';
import { Button } from '../ui/Button';

export interface MessageComposerProps {
  /** `mediaIds` (T35) is the `media_id`s of every successfully uploaded
   * attachment, in add order — an empty array for a text-only send. */
  onSend: (content: string, mediaIds: string[]) => Promise<void> | void;
  disabled?: boolean;
  /** Notifies the caller that the user is actively composing — feeds the
   * live `typing` WS frame (F56). Throttled here (at most once per
   * `TYPING_NOTIFY_INTERVAL_MS`) so continuous typing doesn't send a frame
   * per keystroke; the receiving end's 5s auto-expire only needs a repeat
   * frame well before its window lapses, not on every character. Optional —
   * a no-op omission keeps this component usable without a live connection
   * (e.g. in tests, or before the caller has one established). */
  onTyping?: () => void;
}

const MAX_LENGTH = 4000;
/** Must stay comfortably under the server's 5s auto-expire window (F56) so
 * a continuously-typing user's indicator never lapses on the receiving
 * end between two of this client's frames. */
const TYPING_NOTIFY_INTERVAL_MS = 3_000;

function attachmentStatusLabel(attachment: PendingAttachment): string {
  if (attachment.status === 'uploading') {
    return `Uploading… ${Math.round(attachment.progress * 100)}%`;
  }
  if (attachment.status === 'error') {
    return attachment.error ?? 'Upload failed.';
  }
  return 'Ready';
}

/** One row of the attachment list: filename/size, live upload progress, and
 * an error + retry/remove affordance — never a silent failure (design
 * tokens §5/§9: every interactive state must be visible). */
function AttachmentRow({
  attachment,
  onRemove,
  onRetry,
}: {
  attachment: PendingAttachment;
  onRemove: (id: string) => void;
  onRetry: (id: string) => void;
}): JSX.Element {
  const isError = attachment.status === 'error';

  return (
    <li className="flex flex-col gap-1 rounded-md border border-[var(--color-border)] px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="min-w-0 flex-1 truncate text-body text-[var(--color-text-primary)]">{attachment.file.name}</span>
        <span className="shrink-0 text-caption text-[var(--color-text-tertiary)]">{formatBytes(attachment.file.size)}</span>
        <button
          type="button"
          onClick={() => onRemove(attachment.id)}
          className="shrink-0 text-caption font-medium text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]"
        >
          Remove
        </button>
      </div>

      {attachment.status === 'uploading' && (
        <div
          role="progressbar"
          aria-label={`Uploading ${attachment.file.name}`}
          aria-valuenow={Math.round(attachment.progress * 100)}
          aria-valuemin={0}
          aria-valuemax={100}
          className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--color-surface-raised)]"
        >
          <div
            className="h-full rounded-full bg-[var(--color-accent)] transition-[width] duration-150 ease-out"
            style={{ width: `${Math.round(attachment.progress * 100)}%` }}
          />
        </div>
      )}

      <div className="flex items-center justify-between gap-2">
        <span
          role={isError ? 'alert' : 'status'}
          className={`text-caption ${isError ? 'text-[var(--color-danger)]' : 'text-[var(--color-text-tertiary)]'}`}
        >
          {attachmentStatusLabel(attachment)}
          {isError && attachment.retryAfterSeconds !== undefined && ` Try again in ${attachment.retryAfterSeconds}s.`}
        </span>
        {isError && (
          <button
            type="button"
            onClick={() => onRetry(attachment.id)}
            className="shrink-0 text-caption font-medium text-[var(--color-accent)] hover:text-[var(--color-accent-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]"
          >
            Retry
          </button>
        )}
      </div>
    </li>
  );
}

/** Message composer: submits on Enter (Shift+Enter for a newline), disables
 * itself while a send is in flight, and surfaces a live character count as
 * the 4000-char limit (R36) approaches/is exceeded. Never a silent no-op —
 * the submit button always reflects `disabled`/loading state. Also owns file
 * attachment (T35): upload progress, per-attachment size/type errors
 * (413/415/429 surfaced), and gates Send until every attachment has either
 * finished uploading or been removed. */
export function MessageComposer({ onSend, disabled = false, onTyping }: MessageComposerProps): JSX.Element {
  const [content, setContent] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const lastTypingNotifiedAtRef = useRef(0);
  const { attachments, addFiles, removeAttachment, retryAttachment, reset, isUploading, hasError, readyMediaIds } =
    useMediaUploads();

  const trimmedLength = content.trim().length;
  const isOverLimit = content.length > MAX_LENGTH;
  const canSubmit = !disabled && !isSubmitting && !isUploading && !hasError && trimmedLength > 0 && !isOverLimit;

  function notifyTyping(): void {
    if (!onTyping) {
      return;
    }
    const now = Date.now();
    if (now - lastTypingNotifiedAtRef.current >= TYPING_NOTIFY_INTERVAL_MS) {
      lastTypingNotifiedAtRef.current = now;
      onTyping();
    }
  }

  async function submit(): Promise<void> {
    if (!canSubmit) {
      return;
    }
    setIsSubmitting(true);
    try {
      await onSend(content, readyMediaIds);
      setContent('');
      reset();
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

  function handleFileInputChange(event: ChangeEvent<HTMLInputElement>): void {
    if (event.target.files && event.target.files.length > 0) {
      addFiles(event.target.files);
    }
    // Reset so selecting the same file again (e.g. after removing it) fires
    // another `change` event.
    event.target.value = '';
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2 border-t border-[var(--color-border)] pt-3">
      <label htmlFor="message-composer" className="sr-only">
        Message
      </label>
      <textarea
        id="message-composer"
        value={content}
        onChange={(event) => {
          const value = event.target.value;
          setContent(value);
          if (value.trim().length > 0) {
            notifyTyping();
          }
        }}
        onKeyDown={handleKeyDown}
        disabled={disabled || isSubmitting}
        rows={2}
        placeholder="Write a message… (Enter to send, Shift+Enter for a new line)"
        aria-describedby="message-composer-hint"
        aria-invalid={isOverLimit ? true : undefined}
        className="block w-full resize-none rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] transition-colors duration-150 ease-out focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] disabled:cursor-not-allowed disabled:bg-[var(--color-surface-raised)] disabled:text-[var(--color-text-tertiary)]"
      />

      {attachments.length > 0 && (
        <ul aria-label="Attachments to send" className="flex flex-col gap-2">
          {attachments.map((attachment) => (
            <AttachmentRow key={attachment.id} attachment={attachment} onRemove={removeAttachment} onRetry={retryAttachment} />
          ))}
        </ul>
      )}

      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <label
            htmlFor="message-composer-attach"
            className="cursor-pointer text-caption font-medium text-[var(--color-accent)] hover:text-[var(--color-accent-hover)] focus-within:outline-none focus-within:ring-2 focus-within:ring-[var(--color-accent)]"
          >
            Attach file
          </label>
          <input
            id="message-composer-attach"
            type="file"
            multiple
            disabled={disabled || isSubmitting}
            onChange={handleFileInputChange}
            className="sr-only"
          />
          <p
            id="message-composer-hint"
            className={`text-caption ${isOverLimit ? 'text-[var(--color-danger)]' : 'text-[var(--color-text-tertiary)]'}`}
          >
            {content.length}/{MAX_LENGTH}
          </p>
        </div>
        <Button type="submit" isLoading={isSubmitting} loadingText="Sending…" disabled={!canSubmit} className="w-auto">
          Send
        </Button>
      </div>
    </form>
  );
}
