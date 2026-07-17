import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PresenceIndicator } from './PresenceIndicator';

describe('PresenceIndicator', () => {
  it('renders nothing when no presence event has been observed', () => {
    const { container } = render(<PresenceIndicator presence={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders "Online" for the online state', () => {
    render(<PresenceIndicator presence={{ state: 'online', lastSeen: null }} />);
    expect(screen.getByText('Online')).toBeInTheDocument();
  });

  it('renders a last-seen label for the offline state', () => {
    render(<PresenceIndicator presence={{ state: 'offline', lastSeen: '2026-07-08T00:00:00.000Z' }} />);
    expect(screen.getByText(/last seen/i)).toBeInTheDocument();
  });
});
