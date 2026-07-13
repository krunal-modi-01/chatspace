import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MessageComposer } from './MessageComposer';

describe('MessageComposer', () => {
  it('disables Send until there is non-whitespace content', async () => {
    const user = userEvent.setup();
    render(<MessageComposer onSend={vi.fn()} />);

    const sendButton = screen.getByRole('button', { name: 'Send' });
    expect(sendButton).toBeDisabled();

    await user.type(screen.getByRole('textbox'), '   ');
    expect(sendButton).toBeDisabled();

    await user.type(screen.getByRole('textbox'), 'hi');
    expect(sendButton).toBeEnabled();
  });

  it('submits on Enter, clears the field, and shows a loading state while sending', async () => {
    const user = userEvent.setup();
    let resolveSend!: () => void;
    const onSend = vi.fn().mockReturnValue(
      new Promise<void>((resolve) => {
        resolveSend = resolve;
      }),
    );
    render(<MessageComposer onSend={onSend} />);

    const textbox = screen.getByRole('textbox');
    await user.type(textbox, 'hello there{Enter}');

    expect(onSend).toHaveBeenCalledWith('hello there');
    expect(screen.getByRole('button', { name: /sending/i })).toBeInTheDocument();

    resolveSend();
    await waitFor(() => expect(textbox).toHaveValue(''));
  });

  it('inserts a newline on Shift+Enter instead of submitting', async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<MessageComposer onSend={onSend} />);

    const textbox = screen.getByRole('textbox');
    await user.type(textbox, 'line one{Shift>}{Enter}{/Shift}line two');

    expect(onSend).not.toHaveBeenCalled();
    expect(textbox).toHaveValue('line one\nline two');
  });

  it('flags content over the 4000-char limit and disables Send', async () => {
    const user = userEvent.setup();
    render(<MessageComposer onSend={vi.fn()} />);

    const textbox = screen.getByRole('textbox');
    await user.click(textbox);
    // paste avoids per-keystroke typing cost for a large string
    await user.paste('a'.repeat(4001));

    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
    expect(screen.getByText('4001/4000')).toBeInTheDocument();
  });

  it('never sends while disabled', () => {
    render(<MessageComposer onSend={vi.fn()} disabled />);
    expect(screen.getByRole('textbox')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
  });
});
