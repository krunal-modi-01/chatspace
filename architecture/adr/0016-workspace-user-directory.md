# ADR-0016: Workspace user directory for member & DM selection

> Owner: `architect` / `api-reviewer`. Indexed in `architecture/adr/README.md`.

- **Status:** Proposed
- **Date:** 2026-07-20
- **Deciders:** product-manager + architect + security-reviewer + human gate
- **Tags:** api, product, ux, privacy

## Context
Two v1 flows require a user to *choose another user*, and neither has a usable way to do so today:

1. **Adding a member to a channel (F32/F33).** The functional spec says a channel admin "adds members" but never specifies how a member is *identified*. The shipped UI (`ChannelPage`) therefore asks the admin to "enter the exact user ID" — a UUIDv7 no human can know — which makes private channels effectively unusable without a second tool. The 2026-07-20 review flagged this as a P1 issue that cannot be fixed in the frontend alone.
2. **Starting a direct message (R12/F46).** A DM is sent to "another distinct active user," but there is no way to look that user up; no DM-initiation read was ever specified.

The only user-listing read in the contract is `GET /v1/admin/users` (R55/F72) — **System-Admin-only**, returning email, `is_active`, `last_seen`, and `role`. Reusing it for member/DM selection is wrong on two counts: it is gated to admins (regular users add members and start DMs), and it exposes fields a member-picker must not leak (another user's email, activity, account status).

The forcing question: **how does an authenticated user find another user to add to a channel or DM, without exposing admin-only fields, and without enabling enumeration of anything sensitive?**

## Decision
We will add a **single, workspace-scoped user-directory search read**, shared by both flows, returning only minimal public identity.

1. **`GET /v1/users/search?q=&limit=&cursor=`** — auth: **any active user** (not admin-gated). `q` matches `username` / `first_name` / `last_name` (case-insensitive, prefix/substring). Cursor-paginated per ADR-0003 (default 50, max 100).
2. **Response rows carry public identity only:** `{ id, username, first_name, last_name, avatar_url }`. It **never** returns `email`, `is_active`, `last_seen`, `role`, or any account/security field — that separation is the whole point, and keeps it distinct from the admin `GET /v1/admin/users` (F72).
3. **One read, two consumers:** the channel add-member picker (F32/F33) and the DM "new message" picker (F46, ADR-0017) both use it. Adding a member still goes through the existing admin-gated membership mutation; the *search* is open, the *action* is authorized as before.
4. **Rate-limited** as a general authenticated read; results are the workspace directory, which authenticated members can already see piecemeal (author names/avatars in channels, presence). Deactivated users MAY be excluded from picker results by default (they cannot be messaged and adding them is pointless) while remaining visible in the admin list; this is a query default, not a new field exposure.

New requirement **R59** (PRD v4) and behavior **F76** (functional spec) record this; F32/F33 acceptance is amended to select members via F76 rather than a raw id.

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| A (chosen) — new scoped `GET /v1/users/search`, minimal public fields, shared by member-add + DM | Right authorization (any active user); leaks nothing beyond what members already see; one endpoint serves both pickers; clean separation from the admin list | One new endpoint + requirement to specify and secure |
| B — reuse `GET /v1/admin/users` for pickers | No new endpoint | Admin-gated (regular users can't use it); exposes email/activity/status/role to anyone — a privacy regression |
| C — keep add-by-raw-user-id, add nothing | Zero backend change | Leaves the product defect: nobody knows a UUID; DMs remain un-startable; the review's P1 stands |
| D — expose the full user list unpaginated/unsearchable to all | Trivial to build | No search at scale; still must decide fields; worse ergonomics than a search read |

## Consequences
- **Positive:** Private channels become usable (search a name, add), DMs become startable, and both share one small, well-scoped read. Privacy is preserved by field minimization, and the admin list keeps its distinct, richer, admin-only contract.
- **Negative / trade-offs:** A new authenticated read that returns the workspace member directory to any active user. This is normal for single-workspace team chat (members are mutually visible), but it is a deliberate, documented exposure — `security-reviewer` signs it off, and it is rate-limited and field-minimized. It slightly widens the v1 API surface.
- **Follow-ups:** PRD R59 + §5c matrix row; FS F76 + amended F32/F33/F46 acceptance; API contract `GET /v1/users/search`; task-breakdown M10 adds the backend read and the two picker consumers. `security-reviewer` verifies no admin-only field is ever returned.

## Compliance / reversibility
Additive within `/v1` (new endpoint, new optional consumers) — backward-compatible per the API contract's versioning rules. Reversible by removing the endpoint (pickers would regress, but no client contract breaks for existing reads). Privacy-relevant → routed through the security gate; field minimization is an acceptance criterion, not a convention. No schema change (reads existing `users`).
