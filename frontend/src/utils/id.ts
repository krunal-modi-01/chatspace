/** Generates a client-side identifier — used as both the temporary
 * optimistic-message key and the `Idempotency-Key` header value for message
 * send (frozen contract: client-generated UUID, required). Not a security
 * token, so the low-quality `Math.random()`-based fallback (for environments
 * without `crypto.randomUUID`, e.g. non-secure contexts or older browsers) is
 * acceptable — it only needs to be locally unique. It MUST still be
 * UUID-shaped though: the backend strictly parses the `Idempotency-Key`
 * header as a UUID and rejects anything else with a 400, so a non-UUID
 * fallback (e.g. `id-<timestamp>-<random>`) would permanently break sending
 * in any environment that hits this branch. */
export function generateClientId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return uuidV4Fallback();
}

/** RFC 4122-shaped (version 4, variant 1) UUID built from `Math.random()`.
 * Not cryptographically strong — fine here since this is only ever used as a
 * locally-unique identifier, never a security token. */
function uuidV4Fallback(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
    const rand = (Math.random() * 16) | 0;
    const value = char === 'x' ? rand : (rand & 0x3) | 0x8;
    return value.toString(16);
  });
}
