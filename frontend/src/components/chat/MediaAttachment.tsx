import { useEffect, useState, type JSX } from 'react';
import { fetchMediaUrl } from '../../api/mediaApi';
import { ApiError } from '../../api/problem';
import type { MessageMedia } from '../../api/types';
import { formatBytes } from '../../utils/formatBytes';
import { AlertBanner } from '../ui/AlertBanner';

export interface MediaAttachmentProps {
  media: MessageMedia;
}

type FetchState = 'loading' | 'ready' | 'error';

function isInlineRenderableKind(kind: string): boolean {
  return kind === 'image' || kind === 'video';
}

/**
 * Renders one message attachment (T35): fetches a fresh presigned URL via
 * `GET /v1/media/{media_id}/url` at render/fetch time (never cached across
 * renders, per the frozen contract), then either renders it inline
 * (`image`/`video` kinds) or shows a filename+size download affordance for
 * everything else — including an `image`/`video` whose bytes the browser
 * fails to decode (`onError` fallback), since "decodable" can only be
 * determined by the browser actually trying. No transcoding happens
 * anywhere in this flow.
 */
export function MediaAttachment({ media }: MediaAttachmentProps): JSX.Element {
  const [state, setState] = useState<FetchState>('loading');
  const [url, setUrl] = useState<string | null>(null);
  const [errorDetail, setErrorDetail] = useState<string>('Could not load this attachment.');
  const [decodeFailed, setDecodeFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setState('loading');
    setDecodeFailed(false);

    fetchMediaUrl(media.media_id)
      .then((result) => {
        if (cancelled) {
          return;
        }
        setUrl(result.url);
        setState('ready');
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        setErrorDetail(err instanceof ApiError ? err.problem.detail || err.problem.title : 'Could not load this attachment.');
        setState('error');
      });

    return () => {
      cancelled = true;
    };
  }, [media.media_id]);

  if (state === 'loading') {
    return (
      <p role="status" className="text-caption text-[var(--color-text-tertiary)]">
        Loading {media.filename}…
      </p>
    );
  }

  if (state === 'error') {
    return (
      <AlertBanner variant="error" role="alert">
        <p>
          {media.filename} — {errorDetail}
        </p>
      </AlertBanner>
    );
  }

  const canRenderInline = isInlineRenderableKind(media.kind) && !decodeFailed;

  if (canRenderInline && media.kind === 'image') {
    return (
      <img
        src={url ?? undefined}
        alt={media.filename}
        className="max-h-64 max-w-full rounded-md border border-[var(--color-border)] object-contain"
        onError={() => setDecodeFailed(true)}
      />
    );
  }

  if (canRenderInline && media.kind === 'video') {
    return (
      <video
        src={url ?? undefined}
        controls
        className="max-h-64 max-w-full rounded-md border border-[var(--color-border)]"
        onError={() => setDecodeFailed(true)}
      >
        <track kind="captions" />
      </video>
    );
  }

  return (
    <a
      href={url ?? undefined}
      download={media.filename}
      className="inline-flex items-center gap-2 rounded-md border border-[var(--color-border)] px-3 py-2 text-body text-[var(--color-accent)] transition-colors duration-150 ease-out hover:text-[var(--color-accent-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]"
      aria-label={`Download ${media.filename}, ${formatBytes(media.size)}`}
    >
      <span aria-hidden="true">&#8595;</span>
      <span className="max-w-[16rem] truncate">{media.filename}</span>
      <span className="text-caption text-[var(--color-text-tertiary)]">({formatBytes(media.size)})</span>
    </a>
  );
}
