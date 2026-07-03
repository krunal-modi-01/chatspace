import type { JSX } from 'react';
import { Link } from 'react-router-dom';

/** Placeholder — the full invite-redemption registration flow (email
 * locked/pre-filled from `GET /v1/invites/{token}`) is built in T30. This
 * skeleton page only proves the public route is reachable and unauthenticated. */
export function RegisterPage(): JSX.Element {
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="max-w-sm space-y-4 text-center">
        <h1 className="text-2xl font-semibold text-gray-900">Registration</h1>
        <p className="text-sm text-gray-600">
          Registration requires a valid invite link and is coming soon.
        </p>
        <Link to="/login" className="font-medium text-indigo-600 hover:text-indigo-500">
          Back to sign in
        </Link>
      </div>
    </div>
  );
}
