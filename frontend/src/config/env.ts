/**
 * Env-based configuration. All values are read from Vite's `import.meta.env`
 * so the API base URL can be swapped per-environment without a rebuild of
 * application logic (only the `.env` file changes).
 */

function readApiBaseUrl(): string {
  const raw = import.meta.env.VITE_API_BASE_URL as string | undefined;
  if (!raw) {
    // Sensible local-dev default; production deployments MUST set this.
    return '/v1';
  }
  return raw.endsWith('/') ? raw.slice(0, -1) : raw;
}

export const env = {
  apiBaseUrl: readApiBaseUrl(),
  isDev: import.meta.env.DEV,
} as const;
