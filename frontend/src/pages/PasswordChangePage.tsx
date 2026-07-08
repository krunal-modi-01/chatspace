import type { JSX } from 'react';
import { ErrorBanner } from '../components/ErrorBanner';
import { usePasswordChangeForm } from '../hooks/usePasswordChangeForm';

/** Authenticated in-app password change. The current session stays valid
 * on success; every other session is revoked server-side. */
export function PasswordChangePage(): JSX.Element {
  const {
    currentPassword,
    setCurrentPassword,
    newPassword,
    setNewPassword,
    error,
    isSubmitting,
    succeeded,
    submit,
  } = usePasswordChangeForm();

  return (
    <div className="max-w-sm space-y-6">
      <h1 className="text-xl font-semibold text-gray-900">Change password</h1>

      {error !== null && <ErrorBanner error={error} />}
      {succeeded && (
        <div
          role="status"
          className="rounded-md border border-green-300 bg-green-50 px-4 py-3 text-sm text-green-800"
        >
          Your password has been changed. All other sessions have been signed out.
        </div>
      )}

      <form className="space-y-4" onSubmit={submit} noValidate>
        <div>
          <label htmlFor="currentPassword" className="block text-sm font-medium text-gray-700">
            Current password
          </label>
          <input
            id="currentPassword"
            name="currentPassword"
            type="password"
            autoComplete="current-password"
            required
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>

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
          {isSubmitting ? 'Saving…' : 'Change password'}
        </button>
      </form>
    </div>
  );
}
