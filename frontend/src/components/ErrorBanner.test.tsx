import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ErrorBanner } from './ErrorBanner';
import { ApiError } from '../api/problem';

describe('ErrorBanner', () => {
  it('renders the problem title and detail for an ApiError', () => {
    const error = new ApiError({
      type: 'https://chatspace.example/problems/example',
      title: 'Validation failed',
      status: 422,
      detail: 'content must not be empty',
      instance: '/v1/messages',
      correlation_id: '01J000EXAMPLE',
    });

    render(<ErrorBanner error={error} />);

    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText('Validation failed')).toBeInTheDocument();
    expect(screen.getByText('content must not be empty')).toBeInTheDocument();
  });

  it('renders a generic message for a non-ApiError', () => {
    render(<ErrorBanner error={new Error('boom')} />);

    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
    expect(screen.getByText('boom')).toBeInTheDocument();
  });
});
