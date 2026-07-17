import { useCallback, useRef, useState } from 'react';
import { uploadMedia } from '../api/mediaApi';
import { ApiError } from '../api/problem';
import type { MediaKind } from '../api/types';
import { generateClientId } from '../utils/id';
import { inferMediaKind, preflightSizeError, preflightTypeError } from '../utils/mediaValidation';

export type PendingAttachmentStatus = 'uploading' | 'done' | 'error';

export interface PendingAttachment {
  /** Client-generated id — stable React key and the handle used by
   * `removeAttachment`/`retryAttachment`. Unrelated to the server `media_id`. */
  id: string;
  file: File;
  kind: MediaKind;
  status: PendingAttachmentStatus;
  /** Fraction in `[0, 1]`; only meaningful while `status === 'uploading'`. */
  progress: number;
  /** Set once `status === 'done'` — this is what gets sent as a message's
   * `media_ids` entry. */
  mediaId: string | null;
  error: string | null;
  /** Seconds to wait before retrying, from a `429` response's `Retry-After`
   * header (upload rate limit: 20/min/user). `undefined` for any other
   * failure. */
  retryAfterSeconds?: number;
}

export interface UseMediaUploadsResult {
  attachments: PendingAttachment[];
  /** Validates (client-side pre-check) and uploads each file, tracking
   * per-file progress/state independently. */
  addFiles: (files: FileList | File[]) => void;
  removeAttachment: (id: string) => void;
  retryAttachment: (id: string) => void;
  /** Clears every attachment — called after a successful send. */
  reset: () => void;
  /** True while any attachment is still uploading — the composer must not
   * submit yet (its `media_ids` set isn't final). */
  isUploading: boolean;
  /** True while any attachment is in an unresolved error state — the
   * composer blocks submit until the user removes or retries it, so a
   * message is never sent silently missing an attachment the user intended
   * to include. */
  hasError: boolean;
  /** The `media_id`s of every successfully uploaded attachment, in add order. */
  readyMediaIds: string[];
}

function apiErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    return err.problem.detail || err.problem.title;
  }
  return err instanceof Error ? err.message : 'Upload failed.';
}

/**
 * Manages the set of in-progress/completed file uploads for a single message
 * composer (T35): client-side pre-validation (fast-fail before spending an
 * upload rate-limit token), `XMLHttpRequest`-backed progress reporting, and
 * per-attachment retry/remove. Deliberately composer-scoped (not
 * conversation-scoped) — call `reset()` once the message carrying these
 * `media_ids` has been sent.
 */
export function useMediaUploads(): UseMediaUploadsResult {
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const filesById = useRef(new Map<string, File>());

  const runUpload = useCallback((id: string, file: File, kind: MediaKind) => {
    uploadMedia(file, kind, file.type || 'application/octet-stream', file.name, {
      onProgress: (fraction) => {
        setAttachments((prev) => prev.map((a) => (a.id === id ? { ...a, progress: fraction } : a)));
      },
    })
      .then((result) => {
        setAttachments((prev) =>
          prev.map((a) => (a.id === id ? { ...a, status: 'done', progress: 1, mediaId: result.media_id, error: null } : a)),
        );
      })
      .catch((err: unknown) => {
        setAttachments((prev) =>
          prev.map((a) =>
            a.id === id
              ? {
                  ...a,
                  status: 'error',
                  error: apiErrorMessage(err),
                  retryAfterSeconds: err instanceof ApiError ? err.retryAfterSeconds : undefined,
                }
              : a,
          ),
        );
      });
  }, []);

  const addFiles = useCallback(
    (files: FileList | File[]) => {
      const list = Array.from(files);
      const newAttachments: PendingAttachment[] = [];

      for (const file of list) {
        const id = generateClientId();
        filesById.current.set(id, file);
        const kind = inferMediaKind(file.type);
        const preflightError = preflightSizeError(file, kind) ?? preflightTypeError(file, kind);

        if (preflightError !== null) {
          newAttachments.push({
            id,
            file,
            kind,
            status: 'error',
            progress: 0,
            mediaId: null,
            error: preflightError,
          });
          continue;
        }

        newAttachments.push({ id, file, kind, status: 'uploading', progress: 0, mediaId: null, error: null });
        runUpload(id, file, kind);
      }

      setAttachments((prev) => [...prev, ...newAttachments]);
    },
    [runUpload],
  );

  const removeAttachment = useCallback((id: string) => {
    filesById.current.delete(id);
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const retryAttachment = useCallback(
    (id: string) => {
      const file = filesById.current.get(id);
      if (!file) {
        return;
      }
      setAttachments((prev) =>
        prev.map((a) => (a.id === id ? { ...a, status: 'uploading', progress: 0, error: null } : a)),
      );
      const kind = inferMediaKind(file.type);
      runUpload(id, file, kind);
    },
    [runUpload],
  );

  const reset = useCallback(() => {
    filesById.current.clear();
    setAttachments([]);
  }, []);

  return {
    attachments,
    addFiles,
    removeAttachment,
    retryAttachment,
    reset,
    isUploading: attachments.some((a) => a.status === 'uploading'),
    hasError: attachments.some((a) => a.status === 'error'),
    readyMediaIds: attachments.filter((a) => a.status === 'done' && a.mediaId !== null).map((a) => a.mediaId as string),
  };
}
