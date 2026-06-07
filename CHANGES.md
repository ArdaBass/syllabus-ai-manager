# Changes — this turn (features + UI)

All changes are additive. Existing routes, data, and the database are untouched.
Run `python smoke_test.py` after any edit to confirm every page still loads.

## New features
- **Global search** (`/search/global`, "🌐 Search All Courses" in the sidebar):
  searches code/name, syllabus sections, deadlines and announcements across
  every course you have access to, grouped by course. Scoped to your own
  courses only — it can't surface anything you couldn't already see.
- **Upcoming-deadlines countdown** on the dashboard: shows the next 5 future
  deadlines with days remaining, colour-coded by urgency. (It only lists
  deadlines dated today or later — the default seed data is all in the past,
  so add a future-dated deadline to see it populate.)
- **AI chat glow-up** (`/ai`): answers now render as real markdown (sanitized
  with DOMPurify before display), animated typing indicator, one-tap suggested
  questions, plus copy and clear-chat buttons. Backend `/ai/ask` unchanged.

## UI
- Added a **light / dark theme toggle** (top-right, remembered per browser,
  respects your OS preference on first visit).
- Refreshed surfaces (cards, shadows, inputs) to be theme-aware.
- Fixed malformed HTML in `base.html` (`</body>` was closing before `<body>`).
- Basic mobile responsiveness for the dashboard/grids.

## Small fix
- Visiting a non-existent course id used to crash with a 500; those routes now
  redirect to the dashboard instead.

## Files added
- `smoke_test.py` — one-command health check of every route.
- `.gitignore`, `.env.example` — so secrets / the DB / the venv don't get
  committed or passed around if the project moves to git.

---

# Changes — round 2 (exports + overview)

Still all additive; smoke test now covers 30 route checks.

## New features
- **Course at a Glance** (`/overview`, "📊 At a Glance" in the sidebar): a card
  per course with key stats (instructor, credits, delivery, # sections,
  # deadlines, next deadline) and a colour-coded deadline **timeline** (exams
  vs assignments, past dates faded). Dependency-free CSS/Jinja, theme-aware.
- **Calendar export (.ics)**: per-course (`/course/<id>/deadlines.ics`, button on
  the syllabus + deadlines pages) and all-courses (`/calendar.ics`, button on
  the overview page). Opens straight into Google/Apple Calendar.
- **Print / PDF syllabus** (`/course/<id>/syllabus/print`, button on the syllabus
  page): a clean print-formatted document. Uses the browser's native
  "Save as PDF" — no extra libraries, works the same on every machine.

## Files added
- `templates/overview.html`, `templates/print_syllabus.html`

---

# Changes — round 3 (calendar + progress)

Smoke test now covers 35 checks (incl. a progress toggle round-trip).

## New features
- **Month calendar view** (`/calendar`, "🗓 Calendar" in the sidebar): a real
  month grid with deadlines and exams plotted on their dates, colour-coded
  (exam vs assignment), today highlighted, prev/next month navigation. Opens on
  the month nearest to today that actually has events, so demos aren't blank.
- **Progress tracking**: students can check off deadlines on the deadlines page;
  each course shows a live progress bar (done / total / %). Completed items are
  struck through with a green accent. State is per-student and persists.

## Data
- Added a `deadline_progress` table (created idempotently via `CREATE TABLE IF
  NOT EXISTS`, so it appears on next launch without touching existing data).

## Files added
- `templates/calendar.html`

---

# Changes — round 4 (security hardening)

Smoke test now runs 40 checks, including access-control attempts that should fail.

## Security
- **Passwords are now hashed** (werkzeug scrypt). Login verifies against the hash
  instead of a plaintext match. Existing databases auto-migrate on next launch —
  plaintext passwords get hashed in place, so the same logins keep working.
- **Secret key moved out of the source** into the `SECRET_KEY` env variable
  (added to `.env` and `.env.example`), with a dev-only fallback.
- **Access control / fixed the IDOR.** Course routes now enforce ownership and
  enrollment:
  - Instructors can only view/edit/manage their *own* courses.
  - Students can only reach courses they're enrolled in or that are in their
    department.
  - Unauthorized page requests redirect to the dashboard; unauthorized file/data
    requests (.ics, print) return 403.
  - Delete and edit operations are scoped to the owning course, and student
    check-offs are validated against enrollment.

## Still a manual step (cannot be done in code)
- **Rotate the Gemini API key** in Google AI Studio. The old one has travelled in
  zips and should be considered burned. `.env` is already gitignored so the new
  one won't get committed.
