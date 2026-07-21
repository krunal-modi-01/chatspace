import { useState, type JSX } from 'react';
import type { ChannelMemberSummary, Message } from '../../api/types';
import { MESSAGE_MAX_LENGTH } from '../../constants';
import { Avatar } from '../ui/Avatar';
import { Button } from '../ui/Button';
import { Textarea } from '../ui/Textarea';
import { MediaAttachment } from './MediaAttachment';

export interface MessageTimelineProps {
  messages: Message[];
  /** Current user id, used to distinguish "you" vs. others, and to gate the
   * author-only edit/delete affordances. */
  currentUserId?: string | null;
  /** Identity source for the "other user" badge (F21/F24) — the channel
   * member list (T31's endpoint), keyed by `user_id`. When omitted, falls
   * back to rendering the raw `sender_id` (pre-T32 behavior), so this stays
   * usable before member data has loaded. */
  members?: ReadonlyMap<string, ChannelMemberSummary>;
  /** Author-only edit. Omit to render the timeline read-only (no edit
   * affordance at all). Rejections are shown inline against the message
   * being edited. */
  onEdit?: (messageId: string, content: string) => Promise<void>;
  /** Author-only soft-delete. Omit to render the timeline read-only (no
   * delete affordance at all). */
  onDelete?: (messageId: string) => Promise<void>;
}

function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function displayName(member: ChannelMemberSummary | undefined, senderId: string): string {
  if (!member) {
    return senderId;
  }
  const fullName = [member.first_name, member.last_name].filter(Boolean).join(' ').trim();
  return fullName || member.username;
}

/** The author's inline edit form for one message: shared `Textarea` (T59),
 * the same non-empty/4000-char gate as the composer (R36), a limit hint
 * that only appears near/over the cap, and Save/Cancel. Save stays disabled
 * until the draft is valid — never a silent no-op submit. */
function MessageEditForm({
  messageId,
  draft,
  onDraftChange,
  onSave,
  onCancel,
  isSaving,
  error,
}: {
  messageId: string;
  draft: string;
  onDraftChange: (value: string) => void;
  onSave: () => void;
  onCancel: () => void;
  isSaving: boolean;
  error: string | null;
}): JSX.Element {
  const isDraftEmpty = draft.trim().length === 0;
  const isDraftOverLimit = draft.length > MESSAGE_MAX_LENGTH;
  const showLimitHint = draft.length >= MESSAGE_MAX_LENGTH * 0.9;
  const canSave = !isDraftEmpty && !isDraftOverLimit;
  const hintId = `edit-${messageId}-hint`;

  return (
    <div className="flex w-full flex-col gap-2">
      <label htmlFor={`edit-${messageId}`} className="sr-only">
        Edit message
      </label>
      <Textarea
        id={`edit-${messageId}`}
        value={draft}
        onChange={(event) => onDraftChange(event.target.value)}
        rows={2}
        aria-describedby={showLimitHint ? hintId : undefined}
        aria-invalid={isDraftOverLimit ? true : undefined}
        hasError={isDraftOverLimit}
      />
      {showLimitHint && (
        <p id={hintId} className={`text-caption ${isDraftOverLimit ? 'text-[var(--color-danger)]' : 'text-[var(--color-text-tertiary)]'}`}>
          {draft.length}/{MESSAGE_MAX_LENGTH}
        </p>
      )}
      {error && (
        <p role="alert" className="text-caption text-[var(--color-danger)]">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="button" size="sm" isLoading={isSaving} loadingText="Saving…" disabled={!canSave} onClick={onSave}>
          Save
        </Button>
        <Button type="button" variant="secondary" size="sm" onClick={onCancel} disabled={isSaving}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

/** Renders a REST-backed message list (T32): dedup'd, id-ordered messages
 * with identity badges, edit/delete affordances for the author, and
 * `edited`/`deleted` state applied in place. `role="log"` + `aria-live` keep
 * the accessible-announcement behavior established in T33. */
export function MessageTimeline({
  messages,
  currentUserId,
  members,
  onEdit,
  onDelete,
}: MessageTimelineProps): JSX.Element {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [editError, setEditError] = useState<string | null>(null);
  const [isSavingEdit, setIsSavingEdit] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deleteErrorId, setDeleteErrorId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  if (messages.length === 0) {
    return <p className="text-body text-[var(--color-text-secondary)]">No messages yet.</p>;
  }

  function startEdit(message: Message): void {
    setEditingId(message.id);
    setDraft(message.content);
    setEditError(null);
  }

  function cancelEdit(): void {
    setEditingId(null);
    setDraft('');
    setEditError(null);
  }

  async function saveEdit(messageId: string): Promise<void> {
    if (!onEdit || draft.trim().length === 0 || draft.length > MESSAGE_MAX_LENGTH) {
      return;
    }
    setIsSavingEdit(true);
    setEditError(null);
    try {
      await onEdit(messageId, draft);
      setEditingId(null);
      setDraft('');
    } catch (err) {
      setEditError(err instanceof Error ? err.message : 'Failed to save edit.');
    } finally {
      setIsSavingEdit(false);
    }
  }

  function cancelDelete(): void {
    setConfirmDeleteId(null);
    setDeleteErrorId(null);
    setDeleteError(null);
  }

  async function confirmDelete(messageId: string): Promise<void> {
    if (!onDelete) {
      return;
    }
    setIsDeleting(true);
    setDeleteError(null);
    setDeleteErrorId(null);
    try {
      await onDelete(messageId);
      setConfirmDeleteId(null);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : 'Failed to delete message.');
      setDeleteErrorId(messageId);
    } finally {
      setIsDeleting(false);
    }
  }

  return (
    <ul aria-label="Conversation messages" role="log" aria-live="polite" className="flex flex-col gap-3">
      {messages.map((message) => {
        const isDeleted = message.deleted_at !== null;
        const isOwn = currentUserId != null && message.sender_id === currentUserId;
        const member = members?.get(message.sender_id);
        const isEditing = editingId === message.id;
        const isConfirmingDelete = confirmDeleteId === message.id;

        return (
          <li
            key={message.id}
            className={`flex gap-2 rounded-md border border-[var(--color-border)] px-3 py-2 ${
              isOwn ? 'flex-row-reverse' : 'flex-row'
            }`}
          >
            {!isDeleted && (
              <Avatar
                firstName={member?.first_name}
                lastName={member?.last_name}
                username={member?.username ?? (isOwn ? 'You' : message.sender_id)}
                avatarUrl={member?.avatar_url}
                size="sm"
              />
            )}
            <div className={`flex min-w-0 flex-1 flex-col gap-0.5 ${isOwn ? 'items-end' : 'items-start'}`}>
              <div className="flex items-center gap-2 text-caption text-[var(--color-text-tertiary)]">
                <span className="font-medium text-[var(--color-text-secondary)]">
                  {isOwn ? 'You' : displayName(member, message.sender_id)}
                </span>
                <time dateTime={message.created_at}>{formatTimestamp(message.created_at)}</time>
                {message.edited_at !== null && !isDeleted && <span>(edited)</span>}
              </div>

              {isDeleted ? (
                <p className="text-body italic text-[var(--color-text-tertiary)]">This message was deleted.</p>
              ) : isEditing ? (
                <MessageEditForm
                  messageId={message.id}
                  draft={draft}
                  onDraftChange={setDraft}
                  onSave={() => void saveEdit(message.id)}
                  onCancel={cancelEdit}
                  isSaving={isSavingEdit}
                  error={editError}
                />
              ) : (
                <p className="text-body whitespace-pre-wrap text-[var(--color-text-primary)]">{message.content}</p>
              )}

              {!isDeleted && !isEditing && message.media.length > 0 && (
                <ul aria-label="Attachments" className={`flex flex-col gap-2 pt-1 ${isOwn ? 'items-end' : 'items-start'}`}>
                  {message.media.map((media) => (
                    <li key={media.media_id}>
                      <MediaAttachment media={media} />
                    </li>
                  ))}
                </ul>
              )}

              {!isDeleted && !isEditing && isOwn && (onEdit || onDelete) && (
                <div className="flex items-center gap-2 pt-1">
                  {onEdit && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="text-[var(--color-accent)]! hover:text-[var(--color-accent-hover)]!"
                      onClick={() => startEdit(message)}
                    >
                      Edit
                    </Button>
                  )}
                  {onDelete &&
                    (isConfirmingDelete ? (
                      <span className="flex items-center gap-2">
                        <Button
                          type="button"
                          variant="danger"
                          size="sm"
                          isLoading={isDeleting}
                          loadingText="Deleting…"
                          onClick={() => void confirmDelete(message.id)}
                        >
                          Confirm delete
                        </Button>
                        <Button type="button" variant="ghost" size="sm" disabled={isDeleting} onClick={cancelDelete}>
                          Cancel
                        </Button>
                      </span>
                    ) : (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="text-[var(--color-danger)]! hover:opacity-80"
                        onClick={() => setConfirmDeleteId(message.id)}
                      >
                        Delete
                      </Button>
                    ))}
                </div>
              )}
              {deleteErrorId === message.id && deleteError && (
                <p role="alert" className="text-caption text-[var(--color-danger)]">
                  {deleteError}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
