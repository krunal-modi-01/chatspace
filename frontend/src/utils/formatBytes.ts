/** Formats a byte count as a short human-readable size (e.g. `"2.3 MB"`),
 * used by the media upload/download UI (T35) for both the per-kind size-cap
 * messaging and the download affordance's file size. */
export function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size < 0) {
    return '0 B';
  }
  if (size < 1024) {
    return `${size} B`;
  }
  const units = ['KB', 'MB', 'GB', 'TB'];
  let value = size / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}
