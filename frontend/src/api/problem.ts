import type { ProblemDetails } from './types';

/** Thrown by the HTTP client for any non-2xx response. Always carries a
 * parsed (or synthesized) RFC 7807 problem body — never the raw response,
 * so callers never accidentally log tokens/headers. */
export class ApiError extends Error {
  readonly problem: ProblemDetails;

  constructor(problem: ProblemDetails) {
    super(problem.detail || problem.title);
    this.name = 'ApiError';
    this.problem = problem;
  }

  get status(): number {
    return this.problem.status;
  }

  get correlationId(): string {
    return this.problem.correlation_id;
  }
}

const FALLBACK_TYPE = 'https://chatspace.example/problems/unknown';

/** Parses a failed `Response` into a `ProblemDetails`. Falls back to a
 * synthesized problem body if the server did not return
 * `application/problem+json` (e.g. an upstream proxy error or network
 * failure surfaced as a non-conforming body). */
export async function parseErrorResponse(
  response: Response,
  instance: string,
): Promise<ProblemDetails> {
  const contentType = response.headers.get('content-type') ?? '';
  if (contentType.includes('application/problem+json') || contentType.includes('application/json')) {
    try {
      const body = (await response.json()) as Partial<ProblemDetails>;
      return {
        type: body.type ?? FALLBACK_TYPE,
        title: body.title ?? response.statusText,
        status: body.status ?? response.status,
        detail: body.detail ?? 'An unexpected error occurred.',
        instance: body.instance ?? instance,
        correlation_id: body.correlation_id ?? 'unknown',
        errors: body.errors,
      };
    } catch {
      // fall through to the generic problem below
    }
  }

  return {
    type: FALLBACK_TYPE,
    title: response.statusText || 'Request failed',
    status: response.status,
    detail: 'The server returned an unexpected error response.',
    instance,
    correlation_id: 'unknown',
  };
}

export function networkErrorProblem(instance: string): ProblemDetails {
  return {
    type: 'https://chatspace.example/problems/network-error',
    title: 'Network error',
    status: 0,
    detail: 'Could not reach the server. Check your connection and try again.',
    instance,
    correlation_id: 'unknown',
  };
}
