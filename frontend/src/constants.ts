/** Shared, contract-derived constants used by more than one module.
 * Single source of truth so a server-side contract change only needs one
 * client-side edit (see T59 code review — this value was previously
 * duplicated as a local `MAX_LENGTH`/`MAX_CONTENT_LENGTH` const in multiple
 * files, risking drift). */

/** Mirrors the DB `CHECK` / `PATCH`+`POST /v1/messages` 422 rule (contract
 * R36): message `content` must be 1–4000 chars, non-whitespace. */
export const MESSAGE_MAX_LENGTH = 4000;
