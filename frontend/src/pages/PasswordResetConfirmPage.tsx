import type { JSX } from 'react';
import { Link } from 'react-router-dom';
import { ErrorBanner } from '../components/ErrorBanner';
import { usePasswordResetConfirmForm } from '../hooks/usePasswordResetConfirmForm';

/** Sets a new password from a reset-link token. Renders a clear "link
 * expired, request a new one" message for a stale/used/unknown token. */
export function PasswordResetConfirmPage(): JSX.Element {
  const { newPassword, setNewPassword, error, isSubmitting, isTokenStale, submit } =
    usePasswordResetConfirmForm();

  if (isTokenStale) {
    return (
      <div className="flex min-h-screen items-center justify-center px-4">
        <div className="w-full max-w-sm space-y-4 text-center">
          <h1 className="text-2xl font-semibold text-gray-900">Reset link expired</h1>
          <p className="text-sm text-gray-600">
            This password reset link is expired, already used, or no longer valid. Please request a
            new one.
          </p>
          <Link
            to="/password-reset"
            className="font-medium text-indigo-600 hover:text-indigo-500"
          >
            Request a new reset link
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm space-y-6">
        <h1 className="text-center text-2xl font-semibold text-gray-900">Choose a new password</h1>

        {error !== null && <ErrorBanner error={error} />}

        <form className="space-y-4" onSubmit={submit} noValidate>
          <div>
            <label htmlFor="newPassword" className="block text-sm font-medium text-gray-700">
              New password
            </label>
            <input
              id="newPassword"
              name="newPassword"
              type="password"
              autoComplete="new-password"
              required
              minLength={6}
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              aria-describedby="new-password-hint"
            />
            <p id="new-password-hint" className="mt-1 text-xs text-gray-500">
              At least 6 characters, with at least one letter and one digit.
            </p>
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-md bg-indigo-600 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {isSubmitting ? 'Saving…' : 'Set new password'}
          </button>
        </form>

        <p className="text-center text-sm text-gray-500">
          <Link to="/login" className="font-medium text-indigo-600 hover:text-indigo-500">
            Back to sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
