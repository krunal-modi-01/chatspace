import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createRef } from 'react';
import { describe, expect, it } from 'vitest';
import { Textarea } from './Textarea';

describe('Textarea', () => {
  it('renders a multi-line textbox with a default of 2 rows', () => {
    render(<Textarea aria-label="Message" />);
    const textbox = screen.getByRole('textbox', { name: 'Message' });
    expect(textbox.tagName).toBe('TEXTAREA');
    expect(textbox).toHaveAttribute('rows', '2');
  });

  it('accepts typed input and forwards a ref to the underlying element', async () => {
    const user = userEvent.setup();
    const ref = createRef<HTMLTextAreaElement>();
    render(<Textarea aria-label="Message" ref={ref} />);

    const textbox = screen.getByRole('textbox', { name: 'Message' });
    await user.type(textbox, 'hello there');

    expect(textbox).toHaveValue('hello there');
    expect(ref.current).toBe(textbox);
  });

  it('draws the neutral border by default and the danger border + aria-invalid when hasError is set', () => {
    const { rerender } = render(<Textarea aria-label="Message" />);
    let textbox = screen.getByRole('textbox', { name: 'Message' });
    expect(textbox.className).toContain('border-[var(--color-border)]');
    expect(textbox.className).not.toContain('border-[var(--color-danger)]');

    rerender(<Textarea aria-label="Message" hasError aria-invalid />);
    textbox = screen.getByRole('textbox', { name: 'Message' });
    expect(textbox.className).toContain('border-[var(--color-danger)]');
    expect(textbox).toHaveAttribute('aria-invalid', 'true');
  });

  it('disables the control and applies the disabled treatment', () => {
    render(<Textarea aria-label="Message" disabled />);
    const textbox = screen.getByRole('textbox', { name: 'Message' });
    expect(textbox).toBeDisabled();
    expect(textbox.className).toContain('disabled:cursor-not-allowed');
  });

  it('merges a caller-supplied className with the base treatment', () => {
    render(<Textarea aria-label="Message" className="custom-class" />);
    const textbox = screen.getByRole('textbox', { name: 'Message' });
    expect(textbox.className).toContain('custom-class');
    expect(textbox.className).toContain('resize-none');
  });

  it('lets a caller override the default row count', () => {
    render(<Textarea aria-label="Message" rows={4} />);
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveAttribute('rows', '4');
  });
});
