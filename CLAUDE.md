# TRACE — CLAUDE.md
## Product, Creative Direction, Design System & Engineering Standards

> This document is the single source of truth for designing and developing Trace. Read it fully before making architectural, visual, or functional changes.
>
> **Primary objective:** Build an outstanding, premium, highly polished web application with the visual refinement of a leading creative development studio, while maintaining Trace's genuine learning functionality.
>
> **Design references:**
> - Primary visual reference: The warm orange and white SaaS landing page supplied by the project owner (Pinterest reference).
> - Creative quality reference: https://www.karma.business/
>
> Do not copy either reference literally. Extract their design principles and apply them to Trace's own identity.

---

# 1. PRODUCT UNDERSTANDING

## What is Trace?

Trace is a learning application that helps people become engineers who work effectively with AI coding agents.

Learners practise reading, predicting, modifying, and verifying code, including code an agent might have written, so they can direct agents, review their output, and debug independently.

The problem:

An engineer directs an AI coding agent to build a FastAPI backend, an endpoint, or a database integration.

The code runs, but when the API fails, a database write does not happen, or a bug appears, the engineer may not be able to tell whether the agent's output is correct, or why it fails.

They can ask the agent for another attempt, but cannot yet review, reason about, or modify the implementation confidently themselves.

Trace exists to close this gap.

### Core proposition

**You built it. Now understand it.**

Trace helps engineers who work with AI coding agents learn to:
- Read and understand realistic code, including code an agent wrote.
- Predict how code will behave.
- Identify bugs and misconceptions.
- Make focused code changes.
- Verify actual execution results.
- Review an agent's output before accepting it.
- Give agents clearer direction because they understand the code.
- Apply previously learned concepts independently.

Trace is not an AI agent and does not contain one. It is not an AI code generator, a chatbot, an "AI tutor", a conventional coding quiz platform, or a passive tutorial application.

It is a practice environment focused on understanding real program behavior. Code in a lesson is something the learner reviews and verifies (code from a project, or agent-generated code under review), never something Trace writes for them. Verification is deterministic and backend-driven.

## The learning loop

The core workflow is:

**READ → PREDICT → MODIFY → VERIFY → REVISIT**

### READ
The learner reads a small piece of realistic application code.

### PREDICT
The learner predicts the behavior before seeing the result.

### MODIFY
The learner changes an expression or a small section of code.

### VERIFY
Trace checks the actual behavior using execution results, API responses, or database state.

### REVISIT
Trace presents a related but changed exercise later, helping assess whether the learner retained the underlying concept.

Sessions should typically take approximately 5–10 minutes.

The interface must make these steps immediately understandable.

## Evidence over invented scores

Trace tracks:
- Initial predictions.
- Learner attempts.
- Hint usage.
- Code revisions.
- Verification outcomes.
- Follow-up exercise results.

Do not invent IQ scores, mastery percentages, productivity metrics, or unverified learning claims.

Use evidence such as:

"Correct on first attempt."

"Hint used before revision."

"API returned HTTP 422."

"Database record not created."

"Revisit completed without hints."

The difference between code evidence and learning evidence is fundamental to the product.

---

# 2. DESIGN PHILOSOPHY

## Creative vision

Trace should look like a modern premium technology product designed by an experienced art director and creative frontend engineer.

The visual target combines:

1. Premium editorial typography.
2. Carefully controlled whitespace.
3. Warm atmospheric gradients.
4. Refined nearly white surfaces.
5. High-quality technical product demonstrations.
6. Purposeful motion.
7. Elegant component composition.
8. Clear information architecture.
9. Precise alignment.
10. Strong visual storytelling.

Every section must appear intentionally designed.

The product should feel sophisticated, intelligent, approachable, and technically credible.

## Design concept

**FOLLOW THE SIGNAL**

Trace follows a signal through code:

Input → Execution → Outcome → Understanding.

Represent this idea with:
- Fine connecting lines.
- Subtle active-line highlights.
- Trace paths.
- Numbered learning stages.
- Precise technical labels.
- Carefully animated sequence indicators.
- Clear relationships between code and verified output.

Avoid turning the website into an overly futuristic or cyberpunk dashboard.

The design should remain calm and readable.

## What the reference image teaches us

The supplied Pinterest reference demonstrates a particularly effective composition.

### Outer ambient frame

A thick, rich mesh gradient surrounds the main website, roughly 4–5% of viewport width per side.

- Inset the canvas by `clamp(12px, 3.5vw, 56px)` on all sides.
- Build the gradient from layered, heavily blurred radial gradients with real color variety: rose/magenta `#B9506B` toward the left, crimson `#C8452F` and deep orange `#E8743B` toward the lower corners, amber `#EBA45E` and peach `#F4C6A4` along the top and bottom. Soft colored blobs, still atmospheric. No flat fill.
- A translucent glass rim surrounds the canvas: ~10px ring, 1px `rgba(255,255,255,.55)` border, `rgba(255,255,255,.16)` fill, radius = canvas radius + 12px.
- Canvas: `#FAFAFC`, radius `clamp(24px, 3vw, 40px)`. On ultra-wide screens the frame fills the viewport while content stays within the 1440px container.

### Navigation

- Logo at left, links immediately beside it (left-aligned, not centered), actions at right: the orange "Try Trace" button, plus "Sign in" only if a real route exists.
- About 78% of the canvas width (max ~1100px), 56–60px high, 14px radius, white, 1px border, very soft shadow, 16–20px below the canvas top.
- Links 14px, medium weight, secondary text color.

### Hero composition

- The headline sits in the visual center, in deep graphite, with one phrase highlighted orange.
- The eyebrow is a small rounded pill badge: white, 1px border, 12px uppercase text, .08em tracking, with a small orange arrow chip at the end.
- Description 16–18px, secondary text color, max-width ~520px, centered.
- Buttons are 44px high with 10–12px radius (not full pills). Order: secondary white-outline button on the left, primary orange on the right. The primary has a subtle vertical gradient (`#FF934F` → `#FF7A2E`), a faint inner top highlight, and a soft orange shadow. Its label uses graphite text: white on this orange is ~2.6:1 and fails AA.

### Product demonstration

A large application preview appears below the hero.

**Vertical light streaks** are the signature element: a band of 30–50 soft vertical beams (6–60px wide, varied height and opacity, orange-to-peach, blurred 4–12px) behind the hero content. They are strongest where they meet the top edge of the showcase window and fade to transparent upward, reaching about the CTA row. A horizontal mask fades them toward the sides; the band spans ~85% of the canvas width. Pure CSS/SVG, aria-hidden, static (at most a very slow opacity drift when motion is allowed). A soft warm glow sits under the window.

The window itself is airy and light: white, 1px border, 20–24px radius, large soft shadow, ~80% of the canvas width (max ~1100px). At 1440×900 its header bar and the start of its panels sit above the fold.

For Trace, this preview must depict a realistic interactive learning experience, not a banking dashboard.

### Supporting sections

Sections are composed with strong hierarchy and consistent spacing.

Feature cards contain original, purpose-made visuals.

The design uses repetition where useful, but not identical cards everywhere.

**Do not reproduce the original brand, copy, icons, logos, or product screenshots.**

---

# 3. VISUAL DESIGN SYSTEM

## Color palette

Use CSS variables for all colors.

```css
:root {
  --ambient-base: #C88D81;
  --background: #FAFAFC;
  --surface: #FFFFFF;
  --surface-muted: #F4F5F7;

  --foreground: #151923;
  --text-secondary: #717784;
  --text-tertiary: #9196A1;

  --border: #E5E7EC;

  --primary: #FF8139;
  --primary-hover: #E96E29;
  --primary-soft: #FFF0E6;

  --editor-background: #1A1E27;
  --editor-foreground: #E8EAF0;

  --success: #227953;
  --error: #BD4B4B;
  --warning: #A46D2B;
}
```

### Color rules

- Most of the interface must remain nearly white.
- Graphite should be used for primary text.
- Orange is a signature accent, not the color of every element.
- Use orange for important actions and selective highlighted text.
- Ambient gradients should be atmospheric rather than dominant.
- Semantic success and error colors must remain distinguishable.
- Do not use orange to indicate successful verification.
- Maintain WCAG-compliant text contrast.

Avoid:
- Generic purple-blue AI gradients.
- Neon colors.
- Excessive glassmorphism.
- Randomly colored cards.
- Glowing borders around everything.
- Saturated orange sections without a compositional reason.

## Typography

Preferred fonts:

**Display:** Geist Sans or Plus Jakarta Sans.

**Body:** Geist Sans or Inter.

**Code:** Geist Mono or JetBrains Mono.

Use `next/font` wherever supported.

### Hero typography

```css
font-size: clamp(2.5rem, 4.4vw, 4.5rem);
line-height: 1.06;
letter-spacing: -0.035em;
font-weight: 600;
```

Letters must never touch. At 1440px the longest line spans roughly half the canvas width. On mobile the headline sits at 2.4–2.8rem.

(The earlier values, 7vw and -0.055em, made the headline cramped and oversized.)

The highlighted word uses `--primary-display` (`#E5631C`, 3.2:1), not `--primary` (`#FF8139`, 2.4:1), because large text still needs 3:1.

A compelling hero does not require oversized text for its own sake. The headline should feel balanced within the viewport.

### Section headings

Small pill label, then a left-aligned large heading, then one muted line of subtext.

```css
font-size: clamp(2rem, 3.6vw, 3.25rem);
line-height: 1.1;
letter-spacing: -0.03em;
font-weight: 600;
```

### Body text

- Base size: 16–18px.
- Line-height: 1.5–1.7.
- Comfortable reading width.
- Strong distinction between titles, paragraphs, labels, and supporting details.

### Code

- 13–15px on desktop.
- Approximately 1.6 line-height.
- Maintain indentation and whitespace.
- Use proper syntax highlighting.
- Avoid tiny code text to fit more content.
- The homepage showcase uses a light code surface (`#F7F7FA`) with syntax colors that pass AA on it. The dark editor tokens are kept for the real lesson workspace.

## Spacing

Use a consistent spacing scale:

4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96, 120, 160.

Avoid arbitrary margins and padding across unrelated components.

## Containers

```css
:root {
  --page-max: 1440px;
  --content-max: 1200px;
  --reading-max: 720px;
  --gutter: clamp(20px, 4vw, 64px);
  --section-space: clamp(80px, 10vw, 160px);
  --frame: clamp(12px, 3.5vw, 56px);
  --canvas-radius: clamp(24px, 3vw, 40px);
}
```

Use a consistent container system.

Desktop:
- 12-column layout grid.
- Generous whitespace.
- Controlled text widths.
- Strong alignment between sections.

Tablet:
- Six-column or appropriately simplified grid.

Mobile:
- Single-column composition where required.
- Meaningful changes to structure rather than simply shrinking desktop elements.

## Borders and radii

Use:
- Subtle 1px borders.
- 10–16px standard card radii.
- 20–24px hero product preview radius.
- Carefully selected button radii.
- Soft, minimal shadows.

Avoid using the same giant border radius for every component.

---

# 4. PAGE ARCHITECTURE

Trace should have two related but distinct experiences.

## Marketing website

Purpose:
- Explain the problem.
- Establish differentiation.
- Demonstrate the product.
- Encourage visitors to try a lesson.

Characteristics:
- Editorial.
- Spacious.
- Visually immersive.
- Strong typography.
- Sophisticated movement.
- Carefully art-directed.

## Learning application

Purpose:
- Help users complete genuine exercises.
- Preserve readable code.
- Capture predictions.
- Submit changes.
- Verify results.
- Review progress.

Characteristics:
- Focused.
- Precise.
- Accessible.
- Efficient.
- Lower visual density where possible, but enough density for real technical work.

Both experiences must share typography, colors, UI primitives, and product identity.

Do not force the marketing website's atmospheric gradients into the exercise workspace.

---

# 5. MARKETING HOMEPAGE

Build the homepage as a cohesive visual narrative.

## Section 01 — Floating navigation

Include:
- Trace brand.
- Product.
- How it works.
- Learning approach.
- Sign in where supported.
- Primary CTA.

Recommended CTA:

**Try Trace**

Use a compact rounded white navbar with a subtle border and restrained shadow.

The navigation must remain accessible on mobile.

Use real routes or functional in-page links.

Do not create decorative links with no destination.

## Section 02 — Hero

Recommended eyebrow:

THE GAP BETWEEN SHIPPING AND UNDERSTANDING

Recommended headline:

**You can build with AI.  
Now understand the code.**

Highlight "understand" in orange.

Supporting text:

Trace turns real code into short predict, debug, and verify exercises—so you can work through the next bug yourself.

Primary CTA:
**Try a lesson**

Secondary CTA:
**See how Trace works**

Design requirements:
- Large centered headline.
- Carefully controlled line breaks.
- Compact eyebrow.
- Elegant button grouping.
- Soft atmospheric treatment.
- Generous vertical whitespace.
- High-contrast text.
- Immediate clarity about the product.

Do not add unnecessary decorative illustrations around the headline.

## Section 03 — Hero product showcase

This is one of the most important parts of the entire website.

Show an elegant, realistic Trace application interface below the headline.

The preview should include:

**Code excerpt**

A simple JavaScript (Node + Express) example: the shared `POST /notes` route (see "Homepage example" below).

**Prediction question**

Example:

"What happens when the request omits the title field?"

**Response selection**

A learner makes a prediction.

**Code change**

The learner fixes a missing expression or modifies a small section of code.

**Verification evidence**

Display actual outcomes from the application's verification system when available.

Examples:
- HTTP status.
- Test results.
- Response body.
- Database state.

The preview should clearly communicate the learning process.

Visual direction:
- Large rounded application window.
- Refined editor typography.
- Light UI framing.
- Optional dark code panel.
- Delicate line numbers.
- Clear active-state indicators.
- Small technical labels.
- Beautiful but functional controls.
- Subtle shadow.
- Soft ambient glow behind the preview.
- Restrained vertical light accents.

If the preview is only illustrative, label it as a demonstration.

Never show a fabricated result as though it came from a live backend.

## Section 04 — Core principles strip

Communicate four principles:

REAL CODE

PREDICT FIRST

VERIFY WITH EVIDENCE

PRACTISE AGAIN

Use understated typographic treatment with thin separators.

Do not invent partner brands, customer testimonials, or adoption statistics.

## Section 05 — Three feature cards

Create three original, visually sophisticated feature cards.

### Predict what happens

Explain why prediction strengthens understanding.

Visual direction:
- Code excerpt.
- Highlighted execution path.
- Two possible outcomes.
- Delicate directional connectors.

### Make the change

Show a focused code modification.

Visual direction:
- Before and after code fragments.
- Refined diff highlighting.
- A small editable area.
- Meaningful interaction hints.

### See the evidence

Show actual program results.

Visual direction:
- HTTP response.
- Test output.
- Database record state.
- Explicit difference between expected and observed results.

The cards must not all contain the same icon inside a gradient square.

Each needs its own purposeful visual composition.

## Section 06 — Learning loop

Create an engaging visual explanation of:

READ → PREDICT → MODIFY → VERIFY → REVISIT.

Use a connected visual system inspired by tracing the execution of a program.

Each step must clearly explain what the learner does.

Do not overload the section with animation.

## Section 07 — Actual exercise walkthrough

Show a realistic exercise based on the same simple JavaScript (Node + Express) example.

Explain:
1. What the user is attempting.
2. Which code will execute.
3. What the learner predicts.
4. Which code change is required.
5. What the verification checks reveal.
6. Why the actual behavior occurred.

Use realistic code.

Make the walkthrough understandable even when motion is disabled.

## Section 08 — Learning history

Show concrete evidence of improvement.

Example:
- Original prediction.
- Attempted revision.
- Hint usage.
- Verification outcome.
- Follow-up exercise.
- Independent attempt.

Do not use arbitrary mastery percentages.

A learner's history should describe actual work.

## Homepage example (shared by every section)

All code shown on the marketing site is simple JavaScript (Node + Express). The platform backend remains FastAPI; only the displayed lesson snippets on the marketing site are JavaScript. Those snippets are sample content: the current backend cannot run them live, so their results are always labelled "Sample result".

Use one tiny example everywhere (hero demo, feature cards, steps, flow diagram, walkthrough, learning history), defined once in `src/content/example.ts` and checked by running it on Express 5 and 4:

```js
const express = require("express");
const app = express();
app.use(express.json());
const notes = [];

app.post("/notes", (req, res) => {
  const title = req.body?.title;
  if (!title) {
    return res.status(400).json({ error: "no title" });
  }
  notes.push(title);
  res.status(201).json({
    saved: true,
  });
});
```

- Prediction: a request without `title` gets `400` and `notes` stays `[]`, because `return` stops the function before `notes.push`.
- Modify: add one line to the reply, `count: notes.length,`.
- Verify: show the request body, HTTP status, response body and the contents of `notes`.
- Revisit: the same idea in new code, `POST /tasks` needing a `name`.

Code readability:
- About 14 lines or fewer, lines under about 60 characters, 2-space indentation, meaningful names.
- At most one new idea per sample; highlight the one line that matters.
- One short plain-language caption under each code sample.
- Magnifier targets: 2–3 lines per sample, each with a short plain label.

Sample data: friendly, obvious values ("Buy milk", "Call mom", `title`, `name`). No hashes, UUIDs, long JSON, or numbers that look like statistics. JSON stays at 1–3 short fields.

## Section 09 — Final CTA

Suggested headline:

**Stop just shipping code.  
Start understanding it.**

Supporting text should reinforce Trace's practical learning value.

Include a working primary CTA.

Finish with a refined minimal footer.

---

# 6. APPLICATION USER EXPERIENCE

## Lesson workspace

Prioritize:
- Readability.
- Clarity.
- Fast interaction.
- Clear task progression.
- Immediate access to evidence.

Recommended layout on large screens:

Left:
- Lesson context.
- Code excerpt or editor.

Right:
- Prediction.
- Modification task.
- Feedback.
- Verification state.

Use responsive layouts to prevent cramped code.

## Code editor

Use CodeMirror 6 if an editable code environment is required.

Use syntax highlighting for read-only snippets without loading a large editor engine unnecessarily.

Include:
- Consistent monospace typography.
- Accurate indentation.
- Accessible focus behavior.
- Useful line numbers.
- Relevant code highlighting.
- Clear errors.
- Proper selection behavior.

Avoid making the editor look like a decorative terminal.

## Prediction interface

The learner should commit to a prediction before the outcome is shown.

Do not reveal the answer through premature success styling or hints.

Support clear selections and keyboard interaction.

## Modification interface

Allow focused code changes.

The interface must show:
- What can be modified.
- What is expected.
- How to submit.
- What happens when verification runs.

Do not use fake buttons or pretend that code is executed locally when the actual verification occurs in the backend.

## Verification interface

Separate:

**Expected behavior**

What the learner predicted.

**Observed behavior**

What actually happened.

**Explanation**

Why it happened.

Evidence may include:
- HTTP status.
- JSON response.
- Test output.
- Database state.

Verification must originate from the appropriate deterministic system or clearly identified sample data.

## Review and progress

Present:
- Attempts.
- Revisits.
- Hint usage.
- Corrected misconceptions.
- Independent follow-up outcomes.

Avoid unsupported claims about cognitive ability or mastery.

---

# 7. ANIMATION AND MOTION SYSTEM

Motion should elevate the product rather than interrupt it.

## Recommended stack

Use:

- CSS transitions for simple interactions.
- Motion for React for component transitions.
- GSAP with ScrollTrigger only when advanced choreography genuinely requires it.

Do not use multiple animation libraries for the same task.

## Motion principles

1. Motion must have a purpose.
2. Every animated element must remain understandable.
3. Use consistent easing.
4. Avoid excessive delays.
5. Prioritize opacity and transform animations.
6. Respect reduced-motion preferences.
7. Never make learning depend on an animation.
8. Avoid scroll hijacking.

## Timing guidance

Microinteraction:
120–220ms.

UI state transition:
180–350ms.

Section entrance:
400–700ms.

Large visual reveal:
500–900ms when justified.

These are starting guidelines, not fixed values.

## Hero animation

Suggested sequence:
1. Navbar gently appears.
2. Eyebrow fades in.
3. Headline appears with subtle upward movement.
4. Supporting copy appears.
5. CTAs enter.
6. Product preview reveals.

Keep the entire sequence responsive and avoid making users wait to interact.

Do not hide essential content if JavaScript fails.

## Scroll animation

Use small, intentional reveal transitions.

Suitable effects:
- Opacity changes.
- Slight vertical translation.
- Delicate line drawing.
- Staggered card reveals.
- Progressive trace-path highlighting.

Avoid:
- Constant parallax.
- Excessive blur animations.
- Scroll-controlled text that becomes unreadable.
- Decorative animations competing with the code editor.
- Long unskippable intro sequences.

## Button interactions

Buttons should have:
- Immediate hover feedback.
- Clear focus indicators.
- Short transitions.
- Proper disabled states.
- Loading indicators when needed.

## Lesson transitions

Make state changes purposeful.

Examples:
- Predicted outcome becomes committed.
- Code change becomes highlighted.
- Verification completes.
- Expected and observed outcomes become visible.
- The next learning step becomes available.

Use subtle motion to reinforce cause and effect.

## Reduced motion

Implement `prefers-reduced-motion`.

Do not depend on a moving effect to communicate information.

## Homepage motion system (implemented)

**Libraries.** Motion for React / Motion (`animate`, `inView`) for reveals, sequences and hovers. GSAP + ScrollTrigger only to scrub the two scroll sequences (hero device sequence, learning-loop sticky steps), loaded with a dynamic `import()` inside client effects and only on desktop with motion allowed, so GSAP is never in the first-load bundle. No smooth-scroll libraries; native scroll only.

**Pinning uses CSS `position: sticky`, not GSAP `pin`.** Each sequence is a sticky element inside a taller scroll track whose height is set by CSS from first paint; ScrollTrigger only scrubs. GSAP's pin re-parents the element and offsets it with a large transform on release, which the browser counts as layout shift (measured CLS 0.376 at 1440px) and which blurred focused inputs inside the lesson. Sticky measured CLS 0.0001.

**Tokens.** `src/lib/motion/tokens.ts`, mirrored as CSS custom properties in `globals.css`:
- Easing: entrance `cubic-bezier(.22,1,.36,1)`; hover/UI `cubic-bezier(.2,.8,.2,1)`.
- Durations: micro 180ms, state 300ms, entrance 650ms, heading word 850ms (accent word 1050ms, 70ms apart), large reveal 800ms, connector 500ms, magnifier glide 750ms with a 400ms pause plus 900ms caption reading time, sticky-step swap 550ms.
- End keyframes are explicit (`translateY(0px) scale(1)`), never `none`: inside Motion sequences `none` does not interpolate as identity.
- Stagger: words 70ms, cards 90ms, inner parts 80ms, branches 120ms.
- No ad-hoc values in components.

**Final state is the default.** Server-rendered markup is the readable final state. "From" states apply only under `html.js` (set by an inline script before first paint) and `prefers-reduced-motion: no-preference`. The motion runtime animates in once, then sets `data-revealed` and removes every inline style.

**Components.**
- `<Reveal>` (server): `up`, `card` (translateY 32px, scale .98) or `fade`; `stagger` reveals `[data-reveal-item]` children 90ms apart and `[data-reveal-inner]` parts after each item.
- `<SplitHeading>` (server): frosted word-by-word reveal. Each word goes from blur(12px), opacity 0 and translateY(18px) to crisp, 70ms apart; opacity is in by 55% of a word's 850ms while the blur keeps resolving, so words come into focus; the accent word resolves last in its line over 1050ms. One canvas-coloured veil per heading sweeps once in the stagger direction (desktop only) and leaves nothing behind. Triggers once at ~85% of the viewport. Full text sits in a visually hidden span; word spans are aria-hidden. The hero and /learn headlines use the same reveal as CSS keyframes at load (held until web fonts are ready, never waiting for hydration).
- Heading performance rules: one native animation per word (all properties in one effect, not one per property); words get `will-change` one frame before animating and lose it when done (load headlines release it on `animationend`); headings over 12 words blur once at heading level while words fade and rise; phones blur 6px, Safari/≤4-core devices 8px. Never replace the effect to make it cheaper.
- `<MotionRuntime>` (client): the single observer that runs all reveals.
- `<CodeWindow>`: macOS-style window used for every code excerpt; optional magnifier lens that renders a real 1.6× copy of the code clipped to a circle (never blurred), gliding between target lines while in view.
- `<DeviceSequence>`: the hero's scrubbed device sequence over a sticky stage (375vh track): tilt, flatten, background panel, settle centred at ≥0.7 scale. Re-measures when the lesson grows so every lesson step stays in view; `#demo` links land mid-sequence where the device is flat.
- `<StickySteps>`: light learning-loop section. From 1024px (motion allowed) a fixed-height two-column block, `max(520px, min(78vh, 680px))`, sticks vertically centred inside a track of exactly that height plus 70vh per step (the track length must be `height`, not padding: sticky only moves within the parent's content box). Left: titles with numbers at the right edge, the active one an elevated white card. Right: one tall 28px-radius warm mesh panel, fixed size, the step's white card centred inside. Buttons with aria-expanded and arrow-key navigation; accordion below 1024px and with reduced motion; every step open without JS.
- `<FlowDiagram>`: sequential node, connector and travelling-dot reveal, with an optional Replay.

**Blur.** `filter: blur` animates only on individual heading words (or one heading, above 12 words) and the magnifier lens edge. Never on large containers.

**Phones (under 768px).** Word blur 6px, no veil, no pinning, no 3D tilt; simple in-view reveals instead. Sticky steps stick only from 1024px. The magnifier lens shows from 768px; below that the line highlight moves and a caption bar sits under the code.

**Reduced motion.** No scrub, no pin, no blur, no movement; final states shown immediately. GSAP parts use `gsap.matchMedia()`.

**Lesson workspace routes** get microinteractions only, never scroll choreography.

---

# 8. NEXT.JS ENGINEERING ARCHITECTURE

Use the existing project architecture where appropriate.

Preferred stack:

- Next.js App Router.
- React.
- TypeScript.
- Tailwind CSS.
- CSS variables for tokens.
- Radix primitives.
- shadcn/ui when useful.
- Motion for React.
- Lucide icons.
- CodeMirror for editable code.
- FastAPI backend.
- SQLite persistence.

Do not introduce packages merely because they are trendy.

## Component philosophy

Components must be reusable, focused, typed, and maintainable.

Separate:
- Global design primitives.
- Marketing components.
- Learning components.
- Data access.
- Verification presentation.
- Animation utilities.

Suggested organization, subject to repository inspection:

```text
src/
  app/
    layout.tsx
    page.tsx
    globals.css
    learn/
    progress/
  components/
    ui/
    layout/
    marketing/
    learning/
    code/
    evidence/
  lib/
    api/
    utils/
    motion/
  hooks/
  styles/
```

This is a conceptual structure.

Do not destroy or unnecessarily reorganize a functioning repository to match it.

## Server and Client Components

Use Server Components by default.

Use Client Components when:
- Local interactive state is required.
- Browser interaction is required.
- Animation needs client-side behavior.
- A code editor is present.
- Interactive lesson controls are required.

Avoid turning the entire application into one client-rendered tree.

## Backend integration

Trace's FastAPI backend is responsible for:
- Lesson interactions.
- Saved attempts.
- Hints and revisions.
- Learning state.
- Verification logic.
- Follow-up practice.
- Persistence.

The frontend should consume the real backend contracts.

Before modifying the integration:
1. Inspect actual endpoints.
2. Inspect request and response models.
3. Inspect authentication or session behavior.
4. Inspect persistence expectations.
5. Check available tests.
6. Preserve known-working behavior.

Do not invent API routes based solely on this document.

Do not replace backend logic with mock frontend state.

## Loading and error states

Every asynchronous interaction needs:
- Loading state.
- Error state.
- Recovery action.
- Appropriate success feedback.
- Stable layout during changes.

Do not show successful verification before the backend reports success.

## Security

Do not put secrets in client components.

Validate and safely render untrusted content.

Avoid injecting unsanitized HTML.

Do not execute learner-submitted code in an unsafe application process or browser context.

Keep code execution and verification in the existing approved backend system.

---

# 9. RESPONSIVE DESIGN

Responsiveness is a design requirement, not a final CSS adjustment.

Review at:

- 320px.
- 360px.
- 390px.
- 768px.
- 1024px.
- 1280px.
- 1440px.
- 1920px.

## Desktop

- Large editorial hero.
- Floating navigation.
- Balanced product preview.
- Generous whitespace.
- Multi-column feature layouts.
- Clear application workspace.

## Tablet

- Reorganize sections intentionally.
- Maintain readable type.
- Prevent code panels from overflowing.
- Avoid overcrowded navigation.

## Mobile

- Reflow hero text naturally.
- Reposition CTAs.
- Simplify atmospheric effects.
- Stack feature compositions.
- Keep code readable with appropriate horizontal scrolling where needed.
- Avoid overflowing images.
- Make navigation genuinely functional.
- Keep important controls reachable.

For the lesson interface, use tabs or a compact segmented view if necessary:

CODE | TASK | RESULT.

Do not shrink code to unreadable sizes.

---

# 10. ACCESSIBILITY

Target WCAG 2.2 AA.

Requirements:
- Semantic HTML.
- Correct heading order.
- Keyboard navigation.
- Visible focus indicators.
- Accessible form labels.
- Adequate color contrast.
- Reduced-motion support.
- Clear validation messages.
- Screen-reader-compatible evidence.
- Accessible dialogs and menus.
- Proper focus restoration.
- Meaningful button labels.
- No color-only status communication.
- Readable code and technical output.

Use appropriate live regions for verification completion.

Do not announce every animation frame.

---

# 11. PERFORMANCE

The goal is a visually sophisticated website that remains fast.

Targets for field Core Web Vitals at the 75th percentile:

- LCP at or below 2.5 seconds.
- INP at or below 200ms.
- CLS at or below 0.1.

Implementation rules:
- Use `next/font`.
- Use `next/image` for suitable image assets.
- Lazy-load expensive below-the-fold elements.
- Avoid unnecessary JavaScript.
- Keep animation transforms GPU-friendly where appropriate.
- Do not animate layout-heavy properties continuously.
- Dynamically load large editor or graphics libraries.
- Avoid excessive blurred layers.
- Prevent layout shifts.
- Optimize SVGs.
- Avoid large background videos unless justified.

The hero should be readable before JavaScript hydration.

Avoid implementing WebGL or Three.js for effects achievable with lightweight CSS or SVG.

---

# 12. ORIGINAL VISUAL ASSETS

Do not fill the website with generic stock artwork.

Preferred visual ingredients:
- Realistic Trace interface previews.
- Original code diagrams.
- Abstract technical line work.
- Execution traces.
- Verification evidence panels.
- Carefully composed SVG graphics.
- Minimal gradients and lighting.
- Structured code diffs.

If custom graphics are needed, create assets consistent with the product's visual language.

Do not use random emoji icons or generic AI illustrations.

The imagery should explain Trace's learning process.

---

# 13. CONTENT AND COPYWRITING

Write clearly and specifically.

Audience:
- Engineers who direct AI coding agents and review their output.
- Early-stage developers learning to work alongside agents.
- People building real applications.
- Learners seeking practical independence.

Positioning in copy:
- Frame the learner as an engineer who directs, reviews, and debugs, not as someone who only prompts.
- Present lesson code as code under review: "code from your project", "agent-generated code under review", "the endpoint your agent wrote". Never imply Trace wrote it.
- Trace teaches; it does not generate, chat, or tutor. Describe what the learner does, not what an AI does for them.

Preferred writing:
- Short, useful sentences.
- Technically accurate statements.
- Clear descriptions of real benefits.
- Specific examples.

Avoid:
- "Unlock your limitless potential."
- "Revolutionize your learning journey."
- "10× your coding skills instantly."
- "Guaranteed mastery."
- "The world's most advanced coding platform."

These claims are either vague or unsupported.

Plain language:
- Short sentences, everyday words, about an 8th-grade reading level.
- Explain a term the first time it appears, in a few words, e.g. "HTTP status (a number that says what happened)".
- Prefer plain words: "checks the input" over "validation", "save" over "persist".

Better:

"You can ship an API. Can you explain why it failed?"

"Predict the result before running the code."

"See what the database actually saved."

"Practise again with fewer hints."

"Understand the code you already built."

"Review what your agent wrote before you ship it."

Also avoid:
- "AI-powered learning."
- "Your AI tutor."
- "Chat with Trace."
- "Trace writes the code for you."

---

# 14. DESIGN QUALITY CONTROL

A website that compiles is not necessarily a finished website.

Before considering a feature or page complete, inspect the rendered result.

Evaluate:

### Typography
- Does the headline have strong visual impact?
- Are line breaks intentional?
- Is letter spacing refined?
- Are paragraph widths controlled?
- Is the hierarchy consistent?

### Composition
- Is the primary focal point clear?
- Are sections appropriately spaced?
- Does each section have a distinct visual purpose?
- Is there a consistent alignment system?
- Is the page balanced?

### Color
- Does orange provide meaningful emphasis?
- Is the background calm?
- Are gradients controlled?
- Are semantic colors correct?

### Components
- Are buttons aligned?
- Are border radii consistent?
- Are shadows subtle?
- Are inputs usable?
- Are states complete?

### Motion
- Does animation support comprehension?
- Is it smooth?
- Is it restrained?
- Does reduced-motion work?

### Product authenticity
- Is code realistic?
- Are examples understandable?
- Are verification outcomes genuine or clearly labeled as illustrative?
- Are CTAs functional?
- Are learning interactions connected to the backend where available?

### Responsiveness
- Does the page work on narrow screens?
- Are navigation and controls accessible?
- Are code panels readable?
- Is there horizontal overflow outside intended code areas?

### Technical quality
- Are tests passing?
- Are there runtime errors?
- Is the build successful?
- Are existing backend flows intact?

---

# 15. COMMON AI-GENERATED DESIGN FAILURES TO AVOID

Do not create a generic SaaS template.

Specifically avoid:

1. Repeating identical icon cards.
2. Random glowing gradient blobs.
3. Excessive glassmorphism.
4. Generic purple hero backgrounds.
5. Excessively rounded everything.
6. Default Tailwind typography.
7. Fake testimonials.
8. Fake user statistics.
9. Generic code screenshots.
10. Placeholder navigation.
11. Buttons without functionality.
12. Meaningless animated particles.
13. Excessive scroll animation.
14. Decorative dashboards without real content.
15. Arbitrary mastery scores.
16. Inconsistent spacing.
17. Tiny low-contrast text.
18. Overcomplicated component abstractions.
19. Unnecessary dependencies.
20. Replacing working backend functionality with frontend simulations.
21. Presenting Trace as an AI agent, chatbot, code generator, or AI tutor.

## Positioning rule: Trace is not an AI agent

- It is not an AI agent, and it does not contain one.
- It is not an AI code generator, a chatbot, or an "AI tutor".
- Do not add chat interfaces, assistant panels, or "AI-powered" claims anywhere in the UI or copy.
- Verification stays deterministic and backend-driven, as already specified.

The visual quality should come from composition, typography, originality, craft, and attention to detail—not from excessive decoration.

---

# 16. IMPLEMENTATION WORKFLOW FOR CLAUDE CODE

When asked to build or redesign a feature, follow this workflow.

## Step 1 — Audit the repository

Inspect:
- Existing framework.
- Next.js version.
- Folder structure.
- Routes.
- Components.
- Styles.
- Fonts.
- Dependencies.
- Backend integration.
- Tests.
- Existing assets.

Do not assume the repository is empty.

## Step 2 — Define the screen's purpose

Determine:
- Who uses it?
- What is the primary action?
- What information is needed?
- What API data is involved?
- What states must be supported?
- What evidence should be displayed?

## Step 3 — Plan visual composition

Before implementation, identify:
- Main visual hierarchy.
- Container width.
- Grid structure.
- Typography scale.
- Section sequence.
- Visual focal points.
- Responsive strategy.
- Necessary interactions.

Do not begin by adding dozens of unrelated cards.

## Step 4 — Establish the system

Build or refine:
- Design tokens.
- Typography.
- Buttons.
- Navigation.
- Containers.
- Panels.
- Inputs.
- Technical labels.
- Code display.
- Motion utilities.

Reuse shared primitives.

## Step 5 — Implement the experience

Create functional UI components.

Preserve the existing backend.

Where possible, build one complete vertical slice from frontend interaction through backend verification to displayed evidence.

## Step 6 — Add motion

Only after the static design works.

Implement:
- Microinteractions.
- Section reveals.
- Product-demo transitions.
- Verification feedback.
- Reduced-motion alternatives.

## Step 7 — Validate

Run available:
- Lint checks.
- TypeScript checks.
- Frontend tests.
- Backend tests.
- Production build.
- Browser interaction checks.
- Responsive screenshot inspections.

If screenshot or browser tooling is available, inspect the actual page.

Fix visible alignment, wrapping, spacing, and interaction problems.

Do not claim a test passed unless it was actually run.

## Step 8 — Report accurately

At completion, state:
- What was implemented.
- Which files changed.
- What interactions work.
- Which tests were executed.
- What remains incomplete.
- Any integration limitations.

Do not provide generic completion claims without verification.

---

# 17. FIRST HOMEPAGE IMPLEMENTATION PRIORITIES

For the initial implementation, prioritize the following in order.

### Priority 1

Establish the Pinterest-inspired visual foundation:
- Ambient outer gradient.
- Inset white website canvas.
- Typography.
- Floating navigation.
- Orange accent system.
- Layout grid.

### Priority 2

Build a polished hero:
- Strong centered headline.
- Clear value proposition.
- Beautiful typography.
- Real CTAs.
- Refined spacing.

### Priority 3

Create an exceptional Trace product showcase:
- Realistic code.
- Prediction controls.
- Modification task.
- Verification evidence.
- Carefully art-directed product frame.

### Priority 4

Build supporting sections:
- Product principles.
- Feature cards.
- Learning loop.
- Exercise walkthrough.
- Learning history.
- Final CTA.

### Priority 5

Refine interactions:
- Entrance animation.
- Hover feedback.
- Scroll reveals.
- Mobile navigation.
- Responsive layouts.
- Reduced-motion alternatives.

### Priority 6

Perform final quality checks:
- Browser inspection.
- Desktop and mobile review.
- Functional testing.
- Backend regression checks.
- Visual refinement.

Do not prioritize decorative complexity over core product functionality.

---

# 18. REFERENCE DOCUMENTATION

Use official documentation and follow the installed versions where possible.

Next.js:
https://nextjs.org/docs/app

Next.js Server and Client Components:
https://nextjs.org/docs/app/getting-started/server-and-client-components

Tailwind CSS:
https://tailwindcss.com/docs

shadcn/ui:
https://ui.shadcn.com/docs

Radix UI:
https://www.radix-ui.com/primitives/docs/overview/accessibility

Motion:
https://motion.dev/docs/react

GSAP:
https://gsap.com/docs/v3/Plugins/ScrollTrigger/

CodeMirror:
https://codemirror.net/

FastAPI:
https://fastapi.tiangolo.com/

Playwright:
https://playwright.dev/docs/intro

WCAG 2.2:
https://www.w3.org/TR/WCAG22/

Web Vitals:
https://web.dev/articles/vitals

Creative quality reference:
https://www.karma.business/

Do not assume any design reference's internal technology stack without evidence.

---

# 19. FINAL PRINCIPLES

Trace must succeed on two dimensions.

## Design quality

The website should have:
- Exceptional typography.
- Premium composition.
- Strong visual storytelling.
- Carefully considered color.
- Refined motion.
- Cohesive components.
- Original product visuals.
- Excellent responsive behavior.

## Product quality

The application should:
- Teach through realistic code.
- Require genuine learner attempts.
- Capture predictions.
- Support code modifications.
- Show verification evidence.
- Preserve progress.
- Support follow-up practice.
- Avoid false learning claims.

A beautiful homepage with a broken learning experience is not successful.

A working learning tool with a generic, poorly composed interface does not meet our design ambition.

## Final decision rule

Whenever a design or engineering decision is ambiguous, ask:

**Does this help the learner understand code, or does it merely make the interface look impressive?**

Choose clarity and correctness first.

Then elevate that experience through outstanding visual design and deliberate interactions.

**The final objective is to make Trace look like a premium modern software product and behave like a rigorous, evidence-based learning tool. Both are required.**
