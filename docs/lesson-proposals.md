# Lesson proposals (not built)

> **Status: PROPOSALS ONLY.** None of these lessons exist. Each one needs a backend
> verifier, published lesson content, request variants and tests before it can appear
> in the app. The UI must never list them as available; the lessons hub shows only
> lessons the backend has published, followed by "More lessons are being written".

For: backend/lesson engineering. Written by the frontend side to suggest what could
come next. Every proposal follows the existing loop and the existing safety model:
**Read → Predict → Modify → Verify → Revisit**, with a constrained, structured change
(never free-form code execution), a private ASGI route, and a fresh-session database
read, like `fastapi-payload-mismatch` and `fastapi-nested-payload-transfer`.

Each proposal lists: id, title, concept, stack, the code the learner reads, the
prediction question, the evidence the verifier would observe, the correction variant,
and what the verifier must check.

To add one to the UI once it's real: publish it in the catalog, then add one entry to
`src/content/lessons.ts` and a route that renders the workspace for it.

---

## 1. `fastapi-wrong-http-method`: "The button that never posts"

- **Concept:** HTTP methods are part of the contract. **Bug type:** Wrong HTTP method.
- **Stack:** Python · FastAPI (client in Python, like the existing lessons).
- **Code the learner reads:**

  ```python
  # request_builder.py
  response = client.get("/bookmarks", params={"url": link.url})
  ```

  ```python
  # routes.py
  @router.post("/bookmarks", status_code=201)
  def create_bookmark(body: BookmarkCreate, db: Session = Depends(get_db)):
      ...
  ```
- **Prediction question:** "The learner clicks Save. What does the server do?"
  Options: saved (201) / rejected because the method isn't allowed (405) / server error (500).
- **Observed evidence (buggy):** HTTP 405, `Allow: POST` header, 0 bookmark rows.
- **Correction variant:** structured choice `{"change_type": "set_http_method", "method": "post"}`
  (options: get, post, put). The verifier builds the request; no learner code runs.
- **Verifier must check:** status 405 and `Allow` header for `get`; for `post`: status
  201, response id matches, exactly 1 row with the fixture URL in a fresh session.
  `put` → 405 as well (teaches that the method must match, not just "not GET").

## 2. `fastapi-missing-await`: "Saved… eventually?"

- **Concept:** an un-awaited coroutine never runs. **Bug type:** Missing `await`.
- **Stack:** Python · FastAPI (async route, async SQLAlchemy session).
- **Code the learner reads:**

  ```python
  @router.post("/comments", status_code=201)
  async def add_comment(body: CommentCreate, db: AsyncSession = Depends(get_db)):
      comment = Comment(text=body.text)
      db.add(comment)
      db.commit()          # ← no await
      return {"saved": True}
  ```
- **Prediction question:** "The API answers. Is the comment in the database?"
  Options: yes, 1 row / no, 0 rows / the request fails with 500.
- **Observed evidence (buggy):** HTTP 201, response `{"saved": true}`, **0 rows** on a
  fresh read (plus a "coroutine was never awaited" warning captured by the verifier, not
  shown raw). The point: a success status is not proof of a save.
- **Correction variant:** `{"change_type": "await_call", "line": "commit", "awaited": true}`.
- **Verifier must check:** for the buggy variant, 201 *and* 0 rows (both required, so
  the lesson can't pass on status alone); for the fix, 201 and exactly 1 row with the
  fixture text. Treat warnings/timeouts as infrastructure errors, not learner mistakes.

## 3. `fastapi-wrong-status-code`: "Created, or just OK?"

- **Concept:** status codes tell clients what happened. **Bug type:** Wrong status code.
- **Stack:** Python · FastAPI, plus a small client check.
- **Code the learner reads:**

  ```python
  @router.post("/invites")
  def create_invite(body: InviteCreate, db: Session = Depends(get_db)):
      invite = save_invite(db, body)
      return JSONResponse({"id": str(invite.id)}, status_code=200)
  ```

  ```python
  # client.py
  if response.status_code == 201:
      show("Invite sent")
  else:
      show("Something went wrong")
  ```
- **Prediction question:** "The invite is saved. What does the user see?"
- **Observed evidence (buggy):** HTTP 200, 1 invite row saved, client branch → "Something
  went wrong". Shows the row *and* the misleading message side by side.
- **Correction variant:** `{"change_type": "set_status_code", "status": 201}` (options 200, 201, 204).
- **Verifier must check:** row count stays 1 in every variant; status and the client
  branch output change. 204 → the client can't read `id` (assert the empty body).

## 4. `fastapi-off-by-one-page`: "Where did the first task go?"

- **Concept:** list slicing and page offsets. **Bug type:** Off-by-one in a list.
- **Stack:** Python · FastAPI.
- **Code the learner reads:**

  ```python
  @router.get("/tasks")
  def list_tasks(page: int = 1, size: int = 3, db: Session = Depends(get_db)):
      tasks = db.scalars(select(Task).order_by(Task.id)).all()
      start = page * size
      return tasks[start:start + size]
  ```
- **Prediction question:** "There are 5 tasks (A–E). What does `GET /tasks?page=1` return?"
  Options: A, B, C / D, E / nothing.
- **Observed evidence (buggy):** HTTP 200 with `["D", "E"]`; the fixture DB has A–E.
- **Correction variant:** `{"change_type": "page_offset", "start": "(page - 1) * size"}`
  (options: `page * size`, `(page - 1) * size`, `page * size - 1`).
- **Verifier must check:** seeded fixture rows (5, fixed order), response list exactly
  equals the expected slice for page 1 *and* page 2, response length ≤ size.

## 5. `fastapi-uncommitted-transaction`: "It said saved"

- **Concept:** a transaction isn't saved until it's committed. **Bug type:** Transaction
  not committed.
- **Stack:** Python · FastAPI, sync SQLAlchemy session.
- **Code the learner reads:**

  ```python
  @router.post("/orders", status_code=201)
  def place_order(body: OrderCreate, db: Session = Depends(get_db)):
      order = Order(item=body.item, quantity=body.quantity)
      db.add(order)
      db.flush()           # gives order.id, but nothing is committed
      return {"id": order.id}
  ```
- **Prediction question:** "The response includes an id. Does a fresh read find the order?"
- **Observed evidence (buggy):** HTTP 201 with an id; a **fresh session** finds 0 rows
  (the request's session is rolled back on close). This is exactly what the existing
  independent readback was built to show.
- **Correction variant:** `{"change_type": "finish_transaction", "call": "commit"}`
  (options: flush, commit, refresh).
- **Verifier must check:** response id present in both variants; fresh-session row count
  0 vs 1; for the fix, stored item/quantity match the fixture.

## 6. `express-missing-json-middleware`: "Empty body, every time"

- **Concept:** a server must parse JSON before reading it. **Bug type:** Missing body
  parser. **Stack:** JavaScript · Node + Express (the language used on the marketing
  site; this would be the first real JavaScript lesson).
- **Code the learner reads:**

  ```js
  const app = express();
  // app.use(express.json());   ← missing
  app.post("/notes", (req, res) => {
    const title = req.body?.title;
    if (!title) return res.status(400).json({ error: "no title" });
    notes.push(title);
    res.status(201).json({ saved: true });
  });
  ```
- **Prediction question:** "The request sends `{"title": "Buy milk"}`. What comes back?"
- **Observed evidence (buggy):** HTTP 400 `{"error":"no title"}`, `notes` stays `[]`,
  even though the request contains a title.
- **Correction variant:** `{"change_type": "enable_middleware", "middleware": "express.json"}`.
- **Verifier must check:** needs a **new verifier runtime**: a sandboxed Node process
  with a fixed app, no network, a time limit, and in-memory state read back after the
  request. This is a larger piece of backend work than the Python lessons; flagged here
  so it's planned, not assumed.

---

## Notes for every proposal

- Keep the existing guarantees: one immutable prediction, append-only attempts,
  idempotent writes, deterministic checks, infrastructure errors never counted as
  learner mistakes, and a fresh-session read for anything about saved data.
- Give each lesson a transfer/revisit variant in new code (like the nested-payload
  lesson) so follow-ups test the idea, not memory of one snippet.
- Frontend needs per lesson (today kept in `src/content/lessons.ts` because the API
  doesn't expose them): concept tag, bug-type label, stack label, duration guidance,
  preview file name, and the prerequisite lesson id. A catalog list endpoint returning
  these would let the hub read them from the API instead (see the report's backend gaps).
