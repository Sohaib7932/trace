# Approved pilot customer-support corpus V1

Status: **approved by Soorej for this pilot on 2 November 2026 at 15:34:07 UTC**.
The 30-day review expires on **2 December 2026 at 15:34:07 UTC**. The exact text is in
[`backend/app/support/corpus.json`](../backend/app/support/corpus.json).
No agent logs, private architecture, environment files, learner submissions or
database contents are included or discoverable through this corpus.

| Source ID | Customer-facing article | Passages |
| --- | --- | --- |
| `trace-overview` | What Trace does | 2 |
| `registration-authentication` | Signing up, signing in and recovering access | 3 |
| `google-authentication` | Google sign-in troubleshooting | 2 |
| `learning-navigation` | Starting and returning to lessons | 2 |
| `prediction-attempts-verification` | Predictions, attempts and verification evidence | 3 |
| `hints-explanations` | Hints and AI-assisted lesson guidance | 2 |
| `progress-retrieval` | Saved progress and follow-up reviews | 2 |
| `daily-availability` | Daily exercise availability | 1 |
| `technical-problems` | Technical problems and safe support questions | 2 |

The 19 passages reconcile the existing draft support package with the merged
account-only frontend and the current bounded tutor implementation. Facts were
checked against the actual account/learning/retrieval routes, session transition
rules, verification services, public catalog and current frontend. They do not
claim that hosted Google login, email delivery, daily assignment, generated
lesson delivery or a human support service is operational.

The pilot tutor uses Gemini to select approved explanatory text, rather than
letting provider prose introduce answers or new correctness claims. That limit
is explicit in the proposed article. No support contact or SLA is invented.

The owner explicitly approved this exact package and a 30-day review window in
the current chat. Per-document canonical digests bind the approved text. Content
changes, missing reviews or review expiration make the package unavailable until
reviewed again. No human escalation destination was approved or invented.

The application must remain unavailable while the package is draft or has
missing/expired/conflicting reviews. Existing source-readiness validation is
reused on every request. A model may select only retrieved passage IDs; the
server returns exact supporting quotations. Clients cannot choose documents
or supply source text. Unsupported questions receive no invented answer.
