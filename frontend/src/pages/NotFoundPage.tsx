import type { JSX } from 'react';
import { Link } from 'react-router-dom';

export function NotFoundPage(): JSX.Element {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-2 px-4 text-center">
      <h1 className="text-2xl font-semibold text-gray-900">Page not found</h1>
      <Link to="/" className="font-medium text-indigo-600 hover:text-indigo-500">
        Go home
      </Link>
    </div>
  );
}
