import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Avatar } from './Avatar';

describe('Avatar', () => {
  it('renders an <img> when avatarUrl is set (R28)', () => {
    render(<Avatar firstName="Ada" lastName="Lovelace" avatarUrl="https://example.test/ada.png" />);
    const img = screen.getByRole('img', { name: 'Ada Lovelace' });
    expect(img.tagName).toBe('IMG');
    expect(img).toHaveAttribute('src', 'https://example.test/ada.png');
  });

  it('falls back to first+last initials when avatarUrl is null (R28)', () => {
    render(<Avatar firstName="Ada" lastName="Lovelace" avatarUrl={null} />);
    expect(screen.getByRole('img', { name: 'Ada Lovelace' })).toHaveTextContent('AL');
  });

  it('falls back to the username initial when no first/last name is available', () => {
    render(<Avatar username="grace" avatarUrl={null} />);
    expect(screen.getByRole('img', { name: 'grace' })).toHaveTextContent('G');
  });

  it('falls back to "?" when no identity information is available at all', () => {
    render(<Avatar avatarUrl={null} />);
    expect(screen.getByRole('img', { name: 'Unknown user' })).toHaveTextContent('?');
  });
});
