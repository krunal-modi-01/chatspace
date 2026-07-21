import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../api/problem';
import { MessageComposer } from './MessageComposer';

const { uploadMediaMock } = vi.hoisted(() => ({
  uploadMediaMock: vi.fn(),
}));

vi.mock('../../api/mediaApi', () => ({
  uploadMedia: uploadMediaMock,
}));

function problem(status: number, detail: string) {
  return {
    type: 'https://chatspace.example/problems/example',
    title: 'Example problem',
    status,
    detail,
    instance: '/v1/media',
    correlation_id: '01J000EXAMPLE',
  };
}

function makeFile(name: string, type: string, size = 100): File {
  const file = new File(['x'.repeat(size)], name, { type });
  return file;
}

describe('MessageComposer', () => {
  afterEach(() => {
    uploadMediaMock.mockReset();
  });

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

    expect(onSend).toHaveBeenCalledWith('hello there', []);
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

  it('notifies onTyping while composing, throttled to at most once per interval (F56)', () => {
    // Deliberately `fireEvent` + `vi.spyOn(Date, 'now')` here rather than
    // `userEvent.type` + `vi.useFakeTimers()`: that combination hangs
    // indefinitely in this project's installed `@testing-library/user-event`
    // v14 + vitest v4 pairing — reproduced even against a bare `<textarea>`
    // with no application code involved, so it's an environment/tooling
    // incompatibility, not something to work around inside the component.
    // Driving the same onChange path via `fireEvent.change` and controlling
    // only `Date.now()` (what the throttle actually reads) exercises the
    // identical behavior without that hang.
    const nowSpy = vi.spyOn(Date, 'now');
    try {
      // Starts comfortably past the throttle interval (rather than 0) so the
      // very first keystroke — compared against the ref's initial `0` —
      // reliably counts as "due", matching real usage where `Date.now()` is
      // never actually `0`.
      let now = 10_000;
      nowSpy.mockImplementation(() => now);
      const onTyping = vi.fn();
      render(<MessageComposer onSend={vi.fn()} onTyping={onTyping} />);
      const textbox = screen.getByRole('textbox');

      fireEvent.change(textbox, { target: { value: 'hel' } });
      expect(onTyping).toHaveBeenCalledTimes(1);

      fireEvent.change(textbox, { target: { value: 'hello' } });
      expect(onTyping).toHaveBeenCalledTimes(1);

      now += 3_000;
      fireEvent.change(textbox, { target: { value: 'hello!' } });
      expect(onTyping).toHaveBeenCalledTimes(2);
    } finally {
      nowSpy.mockRestore();
    }
  });

  it('does not call onTyping when clearing the field to empty', async () => {
    const user = userEvent.setup();
    const onTyping = vi.fn();
    render(<MessageComposer onSend={vi.fn()} onTyping={onTyping} />);

    const textbox = screen.getByRole('textbox');
    await user.type(textbox, 'a');
    onTyping.mockClear();
    await user.clear(textbox);

    expect(onTyping).not.toHaveBeenCalled();
  });

  it('uploads an attached file, disables Send until it finishes, then sends with its media_id', async () => {
    const user = userEvent.setup();
    let resolveUpload!: (value: { media_id: string; kind: string; content_type: string; filename: string; size: number; created_at: string }) => void;
    uploadMediaMock.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveUpload = resolve;
      }),
    );
    const onSend = vi.fn();
    render(<MessageComposer onSend={onSend} />);

    const file = makeFile('photo.png', 'image/png');
    const input = document.getElementById('message-composer-attach') as HTMLInputElement;
    await user.upload(input, file);

    await user.type(screen.getByRole('textbox'), 'look at this');
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
    expect(screen.getByText(/uploading/i)).toBeInTheDocument();

    resolveUpload({
      media_id: '01J8MEDIA00000000000000000',
      kind: 'image',
      content_type: 'image/png',
      filename: 'photo.png',
      size: 100,
      created_at: '2026-07-02T14:31:07.482Z',
    });

    await waitFor(() => expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled());

    await user.click(screen.getByRole('button', { name: 'Send' }));
    expect(onSend).toHaveBeenCalledWith('look at this', ['01J8MEDIA00000000000000000']);
  });

  it('surfaces a 413/415/429 upload error inline with a retry action and blocks Send', async () => {
    const user = userEvent.setup();
    uploadMediaMock.mockRejectedValueOnce(new ApiError(problem(413, 'Upload exceeds the maximum size allowed.')));
    render(<MessageComposer onSend={vi.fn()} />);

    const file = makeFile('huge.png', 'image/png');
    const input = document.getElementById('message-composer-attach') as HTMLInputElement;
    await user.upload(input, file);

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/exceeds the maximum size/i));
    const retryButton = screen.getByRole('button', { name: 'Retry' });
    expect(retryButton).toBeInTheDocument();
    expect(retryButton).toHaveClass('text-[var(--color-accent)]!');

    await user.type(screen.getByRole('textbox'), 'hi');
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
  });

  it('flags an oversized file client-side without calling uploadMedia', async () => {
    const user = userEvent.setup();
    const file = makeFile('too-big.png', 'image/png', 11 * 1024 * 1024);
    render(<MessageComposer onSend={vi.fn()} />);

    const input = document.getElementById('message-composer-attach') as HTMLInputElement;
    await user.upload(input, file);

    expect(await screen.findByText(/too large/i)).toBeInTheDocument();
    expect(uploadMediaMock).not.toHaveBeenCalled();
  });

  it('removing a failed attachment re-enables Send', async () => {
    const user = userEvent.setup();
    uploadMediaMock.mockRejectedValueOnce(new ApiError(problem(415, 'Disallowed type.')));
    render(<MessageComposer onSend={vi.fn()} />);

    const file = makeFile('bad.png', 'image/png');
    const input = document.getElementById('message-composer-attach') as HTMLInputElement;
    await user.upload(input, file);

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    await user.type(screen.getByRole('textbox'), 'hi');
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Remove' }));
    expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled();
  });
});
