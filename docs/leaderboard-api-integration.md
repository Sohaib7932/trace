# Global leaderboard API integration

Implemented on `codex/leaderboard-backend`, based on `72bcfc329543f8d51e256a15d9be3beca61b7a30`.
That initial checkpoint was saved as `1c019698dc20c53ce8265b2eb0fada6d9c3cb88c`; the current integration review is `codex/trace-backend-logging-integration` on merged main `646b9bf1de05c31139d96682c8901007a7213e5e`. This is backend work awaiting review. No frontend component or live leaderboard client is enabled by this change.

## Endpoint and authentication

`GET /api/v1/leaderboard`

Send the signed-in learner's Supabase access token as `Authorization: Bearer <access-token>`, using the existing authentication flow. An active registered account with the `learner` role is required. An anonymous learner cookie is insufficient. Reading the board does not create a learner or claim guest history.

| Query parameter | Contract |
| --- | --- |
| `limit` | Integer, default 20, minimum 1, maximum 50. |
| `cursor` | Optional nonempty opaque continuation returned by the preceding response; maximum 512 characters. Omit for a fresh board. |

There is no score, account-ID, sort, timeframe or lesson selector accepted from the client. The board is global and all-time. Reads are idempotent, but each request consumes the existing per-account leaderboard request allowance: 30 requests per fixed minute.

Success headers are `Cache-Control: private, max-age=60` and `Vary: Authorization`. Do not put this personalized response in a shared/public cache. `is_me` and `me` depend on the authenticated viewer.

## Authoritative completion source

The backend joins existing registered-account ownership (`account_learners`) to learning sessions and their pinned lesson versions. A problem counts only when:

1. Its session is `completed`, with a completion timestamp.
2. The same session has a finished `passed` verification run.
3. That run contains all five matching evidence categories: HTTP status, API response, validation, row count and stored values.

The existing verification service records these checks and session completion transactionally. Runtime verifiers exercise the actual receiving API and independently read its database. The leaderboard does not execute code, invoke AI or create completion records.

Each canonical `lesson_id` counts once per learner, across repeated sessions, attempts, verification runs, content hashes and lesson versions. The two current eligible problems are `fastapi-payload-mismatch` and `fastapi-nested-payload-transfer`. Custom AI lessons/private guides are practice, not these verified problems. Retrieval/review answers, failed or incomplete sessions, predictions, drafts and submissions alone do not count.

Claimed guest history becomes eligible only through the existing immutable account-to-learner ownership relationship. Unclaimed guests, disabled accounts and accounts without the learner role are excluded. No migration, scoring table or parallel completion ledger is introduced.

## Response

The exact generated contract is `components["schemas"]["LeaderboardResponse"]` in `src/lib/api/schema.d.ts`. Its source is `backend/openapi.json`.

| Field | Type and meaning |
| --- | --- |
| `entries` | Already ranked and ordered `LeaderboardEntry[]`. |
| `next_cursor` | String for the next page, or `null` when finished. |
| `me` | `{ rank: number, verified_count: number }`, even when the viewer is off-page; `null` for zero verified completions. |
| `generated_at` | UTC ISO-8601 snapshot cutoff; retained across continuation pages. |

Each entry always contains:

| Field | Type and meaning |
| --- | --- |
| `rank` | Positive integer, standard competition rank. |
| `user_id` | Stable opaque leaderboard identifier, derived in a separate namespace. It is not an account, learner, Supabase or GitHub identifier. |
| `display_name` | `null`. The backend has no approved public-profile storage. |
| `avatar_id` | `null`. No avatar is invented or copied from private provider metadata. |
| `avatar_url` | `null`. No third-party image request is needed. |
| `verified_count` | Positive integer count of distinct verified problems. |
| `is_me` | Whether this entry belongs to the authenticated viewer. |

Use the existing `Trace learner` and drawn-avatar fallbacks for null profiles. Do not fetch another person's account/profile using the board ID. Emails, auth subjects, account IDs, learner IDs, raw attempts, source code and evaluation data are not included.

Optional fields from the earlier frontend proposal, `total_ranked` and `passable_with_one_more`, are not implemented and are not returned. Display-name editing, public avatars and opt-out preferences remain separate product/API work.

### Synthetic example

The IDs below are fictional documentation values, not account identifiers or stored production records.

```json
{
  "entries": [
    { "rank": 1, "user_id": "synthetic-opaque-board-a", "display_name": null, "avatar_id": null, "avatar_url": null, "verified_count": 2, "is_me": false },
    { "rank": 1, "user_id": "synthetic-opaque-board-b", "display_name": null, "avatar_id": null, "avatar_url": null, "verified_count": 2, "is_me": false },
    { "rank": 3, "user_id": "synthetic-opaque-board-c", "display_name": null, "avatar_id": null, "avatar_url": null, "verified_count": 1, "is_me": true }
  ],
  "next_cursor": null,
  "me": { "rank": 3, "verified_count": 1 },
  "generated_at": "2026-11-05T08:00:00Z"
}
```

## Ranking, pagination and empty states

Ranks are calculated over the entire eligible board before pagination, using SQL `RANK()` over completion count alone. Equal scores share a rank: `1, 1, 3`, not `1, 2, 3` or dense `1, 1, 2`. An internal stable secondary order prevents arbitrary reordering within a tie; it does not break the tie rank. The frontend must not recompute or sort these values.

Use `next_cursor` unchanged, with the same chosen page size. The cursor carries only a UTC cutoff and bounded offset, not a private account ID. It is a continuation marker, not an authentication credential. Invalid encodings, duplicate/unknown fields, naive/future timestamps and invalid offsets are rejected. Never construct cursors yourself.

Completion/run timestamps, registrations and guest-history claims after the cutoff do not alter the ongoing pagination snapshot. Page and off-page `me` are read in the same database snapshot. Disabling an account or removing its learner role takes effect immediately for privacy. Restart pagination after such membership changes; continuation stability does not override account removal. A new first-page request includes newly eligible completions/accounts.

Only positive-count users are listed, consistent with the existing frontend empty-board and `me: null` contract. Registered users with no verified completion are not displayed as zero-score rows. If nobody is eligible:

```json
{ "entries": [], "next_cursor": null, "me": null, "generated_at": "2026-11-05T08:00:00Z" }
```

If another person has a score but the viewer does not, `entries` contains that person's entry and `me` is still null. With only two eligible problems, ties and scores of one or two are expected.

## Errors and frontend behavior

Errors use the existing envelope:

```json
{ "error": { "code": "validation_error", "message": "Invalid leaderboard cursor.", "request_id": "synthetic-request-id", "details": [] } }
```

| HTTP status | Meaning and handling |
| --- | --- |
| 401 | Missing, invalid or expired Bearer token. Use the existing token-refresh/sign-in flow. Do not substitute guest access. |
| 403 | Disabled account or missing learner role. Show access unavailable; do not retry automatically. |
| 422 | Invalid query/cursor. Discard a stale or malformed cursor and request page one. Validation details contain field locations/codes, not raw submitted values. |
| 429 | Existing per-account allowance exhausted. Show the returned wait-a-minute message and avoid immediate retry loops. This endpoint does not currently promise a `Retry-After` header. |
| 503 | Database/dependency unavailable. Keep any existing results visible and offer a bounded retry. |
| 500 | Unexpected sanitized server failure. Show support details using `error.request_id`; do not expose raw errors. |

Use loading and load-more states separately; deduplicate any repeated presentation rows by opaque `user_id`. After pagination completes, hide load-more. Use `is_me` to highlight a visible viewer and `me` for the account rank card, without searching only the loaded page. Respect browser private caching and the existing few-minute visible-page refetch policy.

### TypeScript request example

```ts
import type { components } from "@/lib/api/schema";

type Leaderboard = components["schemas"]["LeaderboardResponse"];

async function loadLeaderboard(
  apiBaseUrl: string,
  accessToken: string,
  cursor?: string | null,
  signal?: AbortSignal,
): Promise<Leaderboard> {
  const url = new URL("/api/v1/leaderboard", apiBaseUrl);
  url.searchParams.set("limit", "20");
  if (cursor) url.searchParams.set("cursor", cursor);
  const response = await fetch(url, {
    headers: { Authorization: `Bearer ${accessToken}` },
    signal,
  });
  if (!response.ok) throw await response.json(); // Use the project's ApiError adapter in app code.
  return response.json() as Promise<Leaderboard>;
}
```

This example is an integration handoff, not activated frontend code. Sohaib must replace the intentional unavailable implementation in `src/lib/leaderboard/client.ts` with the authenticated request using the existing API/auth/error helpers. The labeled demo adapter remains separate; do not pass demo rows off as server results. No frontend components were implemented in this workstream.

## Validation scope

Backend tests create real Notes/Tasks verification histories in disposable migrated SQLite databases. Coverage includes canonical duplicates/versions, all five evidence categories, tampered or missing checks, failed/error/pending/abandoned sessions, guest claims and cutoff ownership, disabled accounts, role denial, ties, stable pages, zero/empty states, privacy, quota, strict query validation and database failures. No developer database or GitHub App credentials are used. PostgreSQL SQL execution has not been validated by this workstream; portable SQLAlchemy/window expressions and existing consistent-read behavior are used.
