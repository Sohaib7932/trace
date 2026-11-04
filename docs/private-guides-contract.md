# Private learning guides

Private guides are AI instructional material. They are separate from executable
`LessonSpecV1` lessons, trusted verification, reviewed candidates and learner
assignments. They do not grade a learner, award completion, execute code, publish
content or change the +1/+7 retrieval schedule. All examples are unexecuted and
practice is explicitly ungraded. Generated explanations can be wrong; the
response's provenance identifies model wording, not verified correctness.

## Authenticated API

All operations require a current signed-in account with the learner role.
Account status, role, JWT expiry and issuer/subject linkage are freshly checked.
A guest cookie does not grant access. Foreign and missing IDs both return 404.
The root application applies the existing bounded-operation ingress middleware,
request/provider deadlines, per-account admission and no-store responses.

| Operation | Contract |
| --- | --- |
| `POST /api/v1/learning-guides` | Allowed Origin and `X-Trace-Client: learning-web`; UUID `Idempotency-Key`; returns 201 `GuideDetail` |
| `GET /api/v1/learning-guides` | Most recent 50 owned `GuideSummary` objects; empty array is valid |
| `GET /api/v1/learning-guides/{guide_id}` | Owned `GuideDetail`, including content only when ready |

POST body:

```json
{
  "topic": "Python variables",
  "start_level": "beginner",
  "target_level": "intermediate",
  "practical": true,
  "goals": "Understand how assigning a new value changes a name binding",
  "preferences": "Small examples followed by self-directed practice"
}
```

`goals` and `preferences` are optional/null; omit them when empty. Topic is
1–500 characters, goals/preferences 1–600. Levels are `beginner`, `intermediate`
or `advanced`; practical is a strict boolean. Inputs reject extra fields,
HTML/URLs, obvious credentials and direct email addresses. The byte limit is
7,000 UTF-8 bytes. Do not submit private repository content or credentials here.

Summary fields: `id`, `topic`, `status`, `created_at`, `updated_at`, `version`
(`1.0.0`) and `title` (null until ready). Detail adds `request`, `content`,
`content_sha256`, `source` (`ai`, `test_fixture` or null), `generation_version`
(`private-guide-generator-v1`), `ungraded: true` and
`execution_status: "not_executed"`. Account IDs and idempotency keys are not
returned in the public projection or sent to the model.

Content has schema version `private-learning-guide-v1`, title, description,
one to six learning objectives, two to six sections and summary. Each section
has a unique local `id`, title, explanation, nullable example (language, code,
explanation), nullable practice and expected learning outcome. Allowed example
languages are Python, TypeScript, JavaScript, SQL and text. Text is rendered as
text, never executed, trusted HTML or instructions to an agent. The entire
validated content is bounded to 14,000 UTF-8 bytes. Unknown fields, duplicate
IDs, secret-like data, arbitrary links and claims that the provider executed
or verified learner code are rejected.

## Generation and persistence

`BoundedGuideGenerator` uses the existing app-owned shared `BoundedAIClient`
generation capability. It receives a labelled untrusted educational request,
the fixed instructional policy and a strict output schema. It receives no
learner history, account identifiers, private evaluators or runtime authority.
There is no provider SDK/client per request or fallback success content.

The service reserves a unique owner/idempotency-key row in a short transaction,
closes it, invokes the provider, validates structured content, rechecks account
authorization and finalizes in a separate short transaction. No SQLite write
transaction remains open across network work. Content is canonicalized only for
SHA-256 integrity and stored with an immutable version and server policy/model
provenance. This is a content digest, not executable-lesson approval.

States are `generating` → `ready` or `generating` → `unavailable`. Terminal rows
are not overwritten. Successful technical generation never grants executable
publication or assignment. Failed/malformed/timeout outputs produce an honest
persisted unavailable resource without provider text or exception details.

An exact same-key/body retry returns the same resource without another provider
call, including while a request is pending or unavailable. A changed body with
the same key returns 409. A new deliberate attempt requires a new key and the
usual admission budget. Concurrent processes rely on a database uniqueness
constraint; a pending replay can return 201 with `status: "generating"`.

Reservations expire after 60 seconds. A read or replay converts a stale
reservation to unavailable; a late worker cannot then finalize it. This covers
process crashes without silently replaying external work. Clients can poll the
owned GET while generating and show an explicit retry action after failure.

Migration `0010_private_learning_guides` is additive and shared by SQLite and
PostgreSQL paths. It adds only `private_learning_guides`, with foreign key to
users, owner/key uniqueness, state/version/content/source constraints and an
owner/created index. It refuses downgrade while any private guide history exists,
so an ordinary rollback cannot silently delete private user work. It does not
alter learner history. Existing databases must
follow the backup and forward-upgrade procedure; implementation tests only use
disposable databases.

## Verification scope

Deterministic tests cover strict input/output, provider schema rejection,
privacy/authority leakage, owner isolation, idempotency, concurrent replay,
independent writes during provider waiting, expiration/revocation, digest
tampering and disposable migration downgrade/upgrade. Browser fixture transport
has an explicit `test_fixture` guide response for frontend acceptance. None of
those tests prove a genuine Gemini answer. Record genuine provider/browser
acceptance separately; disabled or unavailable modes must remain visibly so.
