# Frontend API browser acceptance — 2026-11-03

Status: final default and AI desktop/mobile browser gates passed.
This report does not claim live Gemini, cloud deployment, full frontend-unit or
full backend-regression success.

## Final complete browser gates

| Gate | Executed result | JUnit duration |
| --- | --- | --- |
| Default `playwright.config.ts` | **58 passed, 4 existing mobile skips, 0 failures**; 62 cases discovered | **259.22 seconds** |
| AI `playwright.ai.config.ts` | **6 passed, 0 skipped, 0 failures** | **81.54 seconds**, including the configured production-build startup |

Both configurations used one worker and zero retries. Existing timeouts,
keyboard actions, security assertions and verification assertions were retained.
The four historical mobile skips cover the desktop keyboard Help path,
explicit multi-width Help overlap path, desktop tutor-resize path and keyboard
hub path. No skip was introduced during this work.

The final default run covered the official SDK against controlled Auth,
registration/confirmation, refresh/logout, recovery, explicit guest-history
claiming and ownership rejection, Notes failure/correction/database evidence,
Tasks transfer, persisted +1/+7 retrieval, pinned legacy content, keyboard
editing, responsive layouts and clearly labelled demo features. The AI run then
used fresh separate fixtures to verify owned tutoring, exact sourced support,
guest rejection, provider unavailability and bounded conversational follow-ups.

Final console logs, JUnit XML and machine-readable summaries are retained
outside Git under `playwright-release-final/default` and
`playwright-release-final/ai` in the task's validation artifacts. All six fixture
ports (8000, 8001, 3100, 8100, 8101 and 3200) returned no HTTP response in direct
loopback probes after completion. The development server on port 3000 was not
stopped or used to inspect real account data.

The original `.next` and prior test outputs were copied to a new external
snapshot; neither directory was moved or deleted. The original
`test-results/.last-run.json` bytes remained unchanged. The clock file was absent
before the run and absent afterward; existing tests cleaned their own generated
clock. Process fixture settings were scoped/restored without environment-file
edits. Fixture builds must not be confused with a build using the intended real
runtime configuration; real-runtime restoration is recorded separately.

A fresh boolean-only scan of the final **24 client JavaScript assets** found no
Google-key, private-key or secret-key patterns and no server credential variable
names. This scan did not read private credential values. The earlier actual-value
scan described below is separate evidence.

## Failed runs and diagnosed readiness

Earlier failures remain preserved rather than being replaced by the passing run:

| Artifact group | Observed result | Investigation |
| --- | --- | --- |
| `playwright-default-full` | 55 passed, 3 failed, 4 existing skips; 357.86 seconds | Two timed-transfer cases reached invalid-session UI after the learning-only clock was set before real-time JWT issuance. The baseline real-time default JWT verification clock was restored without relaxing JWT validation. One desktop hub wait remained in loading state. |
| `playwright-default-rerun` | 57 passed, 1 failed, 4 existing skips; 337.11 seconds | Both timed-transfer cases and both hub cases passed. A desktop guest-claim navigation exceeded a five-second wait; the captured snapshot already contained its exact saved prediction. |
| `playwright-guest-isolation` | 3 passed; 34.45 seconds | Three independent unchanged guest-claim repeats passed; this does not establish the earlier loading delay's precise cause. |
| `playwright-default-final` | 57 passed, 1 failed, 4 existing skips; 264.10 seconds | Mobile programmatic keyboard focus ran before the edit control became enabled. This was investigated before changing the test. |
| `keyboard-readiness-diagnostic` | 1 passed; 17.4 seconds | An explicit gate on the real journey refresh reproduced visible locked prediction with a disabled edit button; only boolean readiness/focus facts were captured. |
| `keyboard-readiness-focused` | 2 passed; 25.51 seconds | Desktop/mobile keyboard journeys passed with stronger readiness assertions; the subsequent complete passing run is listed above. |

The keyboard diagnosis follows actual component state: prediction cleanup awaits
both progress and journey refreshes, while the locked prediction can render as
soon as progress arrives. The edit button remains disabled until mutation
cleanup completes. Programmatic `focus()` does not wait for an enabled control,
so global keyboard input could be sent without focus. The boolean diagnostic
observed disabled=true, focus=false and no listbox before refresh completion;
after completion, the same control was enabled and the same keyboard sequence
focused the listbox. No credentials, headers, request/response bodies or input
values were captured. [Playwright actionability documentation](https://playwright.dev/docs/actionability)

The existing keyboard test now additionally asserts enabled and focused states
before its programmatic key sequences. Original failure/success checks,
keyboard-only interactions and five-second assertion limits remain. No frontend
application behavior was changed for this correction. Targeted ESLint passed.

The earlier hub/guest loading delays were not proven to be an application defect
or definitively attributed to machine contention. Both pass in the final full
run, but those earlier timing observations remain part of the evidence. This
single-worker browser gate is not a production load test.

## Earlier AI browser evidence

- `npm run build`: passed on Next.js 16.4.3. Production compilation completed
  in 22.1 seconds, TypeScript in 18.8 seconds and all 14 static pages generated.
  Explicit public loopback fixture settings were supplied; no server credential
  was configured as a frontend variable.
- Existing generated `.next` files were copied to a new external validation
  snapshot before building. No prior output was reset, moved or deleted.
- `playwright test --config playwright.ai.config.ts`: **6 passed in 1.1 minutes**
  on the earlier Phase 3.8 run, one worker and zero retries. The configured production build
  and synthetic loopback auth/backend servers were used.
- Three journeys ran in both desktop Chrome and Pixel 7 viewports: owned tutor
  and source-referenced support HTTP integration; guest support protection and
  provider-timeout unavailable behavior; natural-language conversation with
  bounded follow-up history, explicit unexecuted advice and clear-history UI.
- Legacy shortcut requests retained the single `question` body field and
  `Cache-Control: no-store` response. Conversation requests contained only the
  approved `code`, `history`, `mode`, `question`, `style` fields; no optional code
  was entered, and `code:null` was explicitly verified.
- Boolean-only scan of the final build's **24 client asset files** found no
  locally configured server-secret values, Google-key patterns or server
  credential variable names. No secret values were printed or retained in this
  report.

The first browser run passed four cases and failed the two new conversation
cases because their exact key assertion omitted the schema-approved nullable
`code` field. Source inspection confirmed that `TutorConversationCreate.code`
is optional and the existing real adapter deliberately sends `null`. Only the
new test was corrected to require that null and the exact five-field structure.
No application behavior, timeout, skip, retry or security assertion was weakened.
Failed and passing browser outputs remain separate external artifacts
(`browser-results` and `browser-results-rerun`).

The provider in these browser tests was the explicitly labelled deterministic
fixture transport. The tests establish real frontend/HTTP adapter behavior,
authentication flow and unavailable-state handling; they are not live model
quality or real-account acceptance evidence. Native-user and live-provider
checks are separate.

## Final real-mode restoration

After all fixture servers stopped, `npm run build` ran again with the existing
private `.env.local`, without fixture overrides or file edits. Compilation
passed in 10.5 seconds, TypeScript in 12.6 seconds and all 14 pages generated.
The configured frontend mode was confirmed as `real`. A separate scan of all
24 client JavaScript assets compared actual configured server credentials and
credential patterns internally; no exposure was found and no values were
printed. The approved loopback Gemini launcher was restarted and SQL readiness
returned HTTP 200. Readiness made no provider request.
