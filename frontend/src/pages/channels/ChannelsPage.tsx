import type { JSX } from 'react';
import { useNavigate } from 'react-router-dom';
import { ErrorBanner } from '../../components/ErrorBanner';
import { AlertBanner } from '../../components/ui/AlertBanner';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { FormField } from '../../components/ui/FormField';
import { useChannelBrowse } from '../../hooks/useChannelBrowse';
import { ApiError } from '../../api/problem';
import type { PublicChannelSummary } from '../../api/types';

/** Maps the exact spec copy for a channel-name collision; falls back to the
 * generic `ErrorBanner` for anything else (422 invalid charset, etc. — those
 * already surface via the inline field error). */
function createErrorMessage(error: unknown): string | null {
  if (error instanceof ApiError && error.status === 409) {
    return 'A channel with this name already exists.';
  }
  return null;
}

function ChannelRow({
  channel,
  isBusy,
  onJoin,
}: {
  channel: PublicChannelSummary;
  isBusy: boolean;
  onJoin: (id: string) => void;
}): JSX.Element {
  return (
    <tr className="border-b border-[var(--color-border)] last:border-0">
      <td className="px-4 py-3 text-body text-[var(--color-text-primary)]">{channel.name}</td>
      <td className="px-4 py-3 text-caption text-[var(--color-text-tertiary)]">
        {channel.member_count} {channel.member_count === 1 ? 'member' : 'members'}
      </td>
      <td className="px-4 py-3 text-right">
        <Button
          type="button"
          variant="secondary"
          className="w-auto"
          isLoading={isBusy}
          loadingText="Joining…"
          onClick={() => onJoin(channel.id)}
        >
          Join
        </Button>
      </td>
    </tr>
  );
}

/** Channel create + public browse/join screen (T31). Member list, admin
 * management, and leave live on the channel view (`ChannelPage`) once
 * inside a channel. */
export function ChannelsPage(): JSX.Element {
  const navigate = useNavigate();
  const {
    name,
    setName,
    isPrivate,
    setIsPrivate,
    nameError,
    createError,
    isCreating,
    submitCreate,
    channels,
    total,
    offset,
    pageSize,
    isLoading,
    listError,
    hasNextPage,
    hasPreviousPage,
    nextPage,
    previousPage,
    joiningId,
    joinError,
    join,
  } = useChannelBrowse();

  const createMessage = createErrorMessage(createError);

  const handleCreate = async (event: React.FormEvent) => {
    const created = await submitCreate(event);
    if (created) {
      navigate(`/channels/${created.id}`);
    }
  };

  const handleJoin = async (channelId: string) => {
    const joined = await join(channelId);
    if (joined) {
      navigate(`/channels/${channelId}`);
    }
  };

  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = Math.min(offset + pageSize, total);

  return (
    <div className="max-w-4xl space-y-6">
      <h1 className="text-heading text-[var(--color-text-primary)]">Channels</h1>

      <Card>
        <h2 className="text-subheading text-[var(--color-text-primary)]">Create a channel</h2>
        <form className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-end" onSubmit={handleCreate} noValidate>
          <div className="flex-1">
            <FormField
              id="channel-name"
              name="name"
              label="Name"
              autoComplete="off"
              required
              value={name}
              onChange={(event) => setName(event.target.value)}
              error={nameError ?? undefined}
              hint={nameError ? undefined : '1-80 letters, numbers, spaces, hyphens, or underscores.'}
            />
          </div>
          <label className="flex items-center gap-2 pb-2 text-body text-[var(--color-text-primary)]">
            <input
              type="checkbox"
              checked={isPrivate}
              onChange={(event) => setIsPrivate(event.target.checked)}
              className="h-4 w-4 rounded border-[var(--color-border)] text-[var(--color-accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]"
            />
            Private
          </label>
          <Button type="submit" isLoading={isCreating} loadingText="Creating…" className="sm:w-auto">
            Create channel
          </Button>
        </form>
        {createError !== null &&
          (createMessage !== null ? (
            <div className="mt-4">
              <AlertBanner variant="error">{createMessage}</AlertBanner>
            </div>
          ) : (
            <div className="mt-4">
              <ErrorBanner error={createError} />
            </div>
          ))}
      </Card>

      <div>
        <h2 className="text-subheading text-[var(--color-text-primary)]">Browse public channels</h2>
        <p className="mt-1 text-caption text-[var(--color-text-tertiary)]">
          Channels shown here are public and you are not yet a member.
        </p>
      </div>

      {listError !== null && <ErrorBanner error={listError} />}
      {joinError !== null && <ErrorBanner error={joinError} />}

      {isLoading ? (
        <div role="status" aria-live="polite" className="text-body text-[var(--color-text-secondary)]">
          Loading channels…
        </div>
      ) : channels.length === 0 ? (
        <Card className="text-body text-[var(--color-text-secondary)]">
          No public channels to join right now.
        </Card>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-overlay)]">
            <table className="w-full text-left">
              <caption className="sr-only">Public channels</caption>
              <thead>
                <tr className="border-b border-[var(--color-border)] text-caption font-semibold text-[var(--color-text-tertiary)]">
                  <th scope="col" className="px-4 py-2">
                    Name
                  </th>
                  <th scope="col" className="px-4 py-2">
                    Members
                  </th>
                  <th scope="col" className="px-4 py-2" />
                </tr>
              </thead>
              <tbody>
                {channels.map((channel) => (
                  <ChannelRow
                    key={channel.id}
                    channel={channel}
                    isBusy={joiningId === channel.id}
                    onJoin={handleJoin}
                  />
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between text-body text-[var(--color-text-secondary)]">
            <span>
              Showing {rangeStart}-{rangeEnd} of {total}
            </span>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="secondary"
                className="w-auto"
                disabled={!hasPreviousPage}
                onClick={previousPage}
              >
                Previous
              </Button>
              <Button type="button" variant="secondary" className="w-auto" disabled={!hasNextPage} onClick={nextPage}>
                Next
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
