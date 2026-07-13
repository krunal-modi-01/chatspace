import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ReconnectingBanner } from './ReconnectingBanner';

describe('ReconnectingBanner', () => {
  it('renders nothing when the connection is open', () => {
    const { container } = render(<ReconnectingBanner status="open" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing during the initial connect attempt', () => {
    const { container } = render(<ReconnectingBanner status="connecting" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing once closed', () => {
    const { container } = render(<ReconnectingBanner status="closed" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders a status banner while reconnecting', () => {
    render(<ReconnectingBanner status="reconnecting" />);
    expect(screen.getByRole('status')).toHaveTextContent(/reconnecting/i);
  });
});
