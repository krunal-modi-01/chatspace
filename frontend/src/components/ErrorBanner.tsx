import type { JSX } from 'react';
import { env } from '../config/env';
import { ApiError } from '../api/problem';

export interface ErrorBannerProps {
  error: unknown;
}

function toMessage(error: unknown): { title: string; detail: string; correlationId: string | null } {
  if (error instanceof ApiError) {
    return {
      title: error.problem.title,
      detail: error.problem.detail,
      correlationId: error.correlationId,
    };
  }
  return {
    title: 'Something went wrong',
    detail: error instanceof Error ? error.message : 'An unexpected error occurred.',
    correlationId: null,
  };
}

/** Renders a base problem+json error state. In dev builds, shows the
 * correlation id to speed up cross-referencing backend logs. */
export function ErrorBanner({ error }: ErrorBannerProps): JSX.Element {
  const { title, detail, correlationId } = toMessage(error);

  return (
    <div
      role="alert"
      className="rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800"
    >
      <p className="font-medium">{title}</p>
      <p>{detail}</p>
      {env.isDev && correlationId && (
        <p className="mt-1 font-mono text-xs text-red-600">correlation_id: {correlationId}</p>
      )}
    </div>
  );
}
