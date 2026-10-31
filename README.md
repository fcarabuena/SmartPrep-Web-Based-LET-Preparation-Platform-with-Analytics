# Smart Prep: Web-Based LET Preparation Platform with Analytics

MIT capstone project for LET (Licensure Examination for Teachers, Philippines) reviewees of
**Romblon State University – Cajidiocan Campus**. Smart Prep combines a question bank, mock exams,
adaptive practice, gamification and analytics. It is built to run **100% free** on one Render free
web service with a Neon free PostgreSQL database.

**Stack:** Python 3.12 · FastAPI · Jinja2 · Bootstrap 5 · Chart.js · FullCalendar · SQLAlchemy 2 · Alembic ·
psycopg 3 · PostgreSQL (Neon) / SQLite (local) · pytest

## Build status

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: models, migrations, auth (register/verify/login/reset/2FA/Google), roles, layout, admin users | ✅ |
| 2 | Content: categories/courses/topics, question bank, review queue, import, resources | ✅ |
| 3 | Assessments: exams/quizzes, timer, results, grades | ✅ |
| 4 | Recommendations, adaptive practice, study plan, gamification | ✅ |
| 5 | Analytics & reports | ✅ |
| 6 | Notifications, inbox, calendar, goals, forum | ✅ |
| 7 | Web scraping & optional Gemini generation | ⏳ |
| 8 | Hardening, demo data, docs | ⏳ |

## Local setup (Windows 11)

Requires Python 3.12+ (3.12 is what Render uses) and Git.

```powershell
git clone https://github.com/fcarabuena/SmartPrep-Web-Based-LET-Preparation-Platform-with-Analytics.git
cd SmartPrep-Web-Based-LET-Preparation-Platform-with-Analytics
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env          # optional; defaults work for local SQLite
alembic upgrade head            # creates smartprep.db (SQLite) when DATABASE_URL is empty
python scripts\seed.py          # categories/courses/topics, 100 sample questions, resources, badges
python scripts\create_admin.py --email admin@example.com --name "Site Admin"
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. Admin and faculty accounts must set up an authenticator app
(Google Authenticator, Microsoft Authenticator, Authy…) on first sign-in.

If PowerShell blocks `activate`, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once,
or call tools directly: `.venv\Scripts\python -m uvicorn app.main:app --reload`.

### Run tests

```powershell
.venv\Scripts\python -m pytest
```

Tests use an in-memory SQLite database and never touch the network.

## Features by module

### Content (Phase 2)
- **Categories › Courses › Topics** (`/content/categories`): General Education, Professional Education and
  Specialization (Major Core). Major courses are only visible to students of that major.
- **Question bank** (`/questions`): search, filters (category, topic, difficulty, status, source), bulk actions,
  live duplicate detection (normalized stem hash + similar-stem search). Students only ever see **approved** items.
- **Review queue** (`/questions/review`): approve/reject pending items (scraped, AI-generated and imported).
- **CSV/Excel import** (`/questions/import`): downloadable templates, preview with row-level errors, duplicate
  skipping, server-side re-validation on confirm.
- **Resources** (`/resources`): links, videos, articles and small uploads (PDF/DOCX/PPTX/images, max 5 MB, type and
  content checked) stored in the database. Students browse and search them at `/materials`; every open is tracked.
- **Seed content**: 100 original LET-style questions (10 per sample topic, each with a rationalization).

### Assessments (Phase 3)
- **Types:** practice quiz, mock exam (LET simulation), timed quiz game, quiz bee. Scope by category, course and/or
  topics; auto-draw by difficulty or manual pick; randomized questions and choices; time limit; access code;
  open/due dates; max attempts; points per correct answer and pass bonus (`/assessments`).
- **Examinations** page with Prof Ed / Major Core / Gen Ed tabs, instructions, time limit, due date and "Past Due";
  **Quizzes** page grouped by category and course.
- **Taking:** one question at a time, question navigator, autosave every 15 s and on every answer, per-question time
  tracking. The timer is enforced on the server (`deadline_at`); late saves and page loads auto-submit expired attempts
  (no cron needed).
- **Pass thresholds:** 75% (attempt 1), 80% (attempt 2), 85% (attempt 3+), configurable in `/admin/settings`; the
  threshold used is stored on each attempt.
- **Results:** score, pass/fail, chosen vs correct answer with rationalization for every item, Retake.
- **Grades** (`/grades`): Passed / Failed / Missing / Not attempted with category/course filters, print stylesheet
  and PDF export. Faculty see every attempt under `/submissions`.

### Adaptive learning & gamification (Phase 4)
- **Recommendations** (results page): resources per topic proportional to wrong answers (1 wrong → 1, 3 wrong → 3,
  capped in settings), topic practice first, then videos/articles; level by mastery (<75% foundational, 75–84%
  standard, ≥85% advanced and fewer items).
- **Regenerate Questions:** adaptive set for the same scope; topic weight = 1 − mastery, difficulty mix by mastery,
  avoids questions seen in the last 7 days. Adaptive sets never use up graded attempts.
- **Study Plan** (`/study-plan`): weakest topics first with mastery bars, leveled resources and "Start practice".
- **Points ledger** (correct answers, completion, pass + bonus, perfect score, improvement, quiz series, recommended
  resource views with a daily cap, daily streak) and **levels** (level n starts at step·n(n−1)/2 points).
- **Badges** are data-driven rules (accuracy, improvement, category mastery, perfect, streak, first quiz, points,
  quizzes completed, manual). Defaults: Accuracy Ace, Persistence Pro, Master of Categories, Perfect Score, Streak 7,
  First Steps. Staff add badges and award manual ones at `/badges`; students get a notification.
- **Leaderboards** (`/leaderboards`): overall (points), by category, by course and by game/assessment. Ties go to
  first-attempt passers, then less time. Faculty can hide leaderboards from students.
- **Games:** faculty-created timed quiz games and quiz bees, plus an instant "Quick Quiz Bee" (15 random questions
  across all subjects, 5 minutes).

### Analytics (Phase 5)
- **LET Readiness Score** = weighted category mastery. Secondary: Gen Ed 20%, Prof Ed 40%, Specialization 40%;
  Elementary: Gen Ed 40%, Prof Ed 60% (configurable). Bands: Not ready / Developing (≥60) / Ready (≥75).
- **Student Progress** (`/progress`): mastery by category, rank, badges, questions answered, time spent, quiz and
  exam completion donuts, **Study Hot Zones** heatmap (courses × topics or Exam 1/2/3; green ≥85, yellow 75–84,
  red <75, values always printed), progress by category (Exam 1/2/3 + improvement) and by course (correct %,
  incorrect %, improvement, minutes), attempted vs correct, 8-week trend, strengths/weaknesses, recommendations.
- **Faculty:** class KPIs (average score, pass rate, participation), category performance, weekly trend,
  most-missed topics, **at-risk students** (low readiness or inactive N days), per-student drill-down with
  "Send feedback", **item analysis** (difficulty index p, discrimination index D from upper/lower 27% on first
  attempts, distractor counts, retain/revise/reject flags).
- **Admin:** DAU/WAU/MAU, logins/registrations/submissions per day, peak-activity heatmap (weekday × hour, PH time),
  average session length, popular content, content access by type, questions by source with approval rate,
  **system health** (uptime, request counts, recent errors, DB size, table sizes).
- **Report builder** (`/reports`): user activity, performance, content usage, engagement; date range + filters;
  preview; export CSV / Excel / PDF.
- Aggregations run as grouped SQL (dialect-aware for PostgreSQL and SQLite); heavy views are cached for 60 s.

### Communication & planning (Phase 6)
- **Notifications** (bell + `/notifications`): new approved questions/resources, assessment published, due within
  24 h, faculty feedback, badges, goals reached, forum replies, announcements. Deduplicated per event.
  Deadline reminders are checked lazily on page load (at most every 10 minutes per session) — no cron job.
- **Announcements** (`/announcements`): target roles, students who can see a course, or specific students; optional
  email through Brevo.
- **Inbox** (`/inbox`): direct messages between students, faculty and admins with threads, Inbox / Sent / Unread /
  Drafts, course filter and search. Faculty feedback lands here.
- **Calendar** (`/calendar`, FullCalendar): month / week / agenda views with a Today button; assessment due dates,
  goal deadlines, personal events and class-wide events (staff).
- **Goals** (`/goals`): targets for questions answered, quizzes passed, average score, points, readiness or category
  mastery with automatic progress; shown on the dashboard and calendar.
- **Forum** (`/forum`): threads per category/course, replies, search; faculty pin, lock and delete.

## Configuration

| Variable | Required | Purpose |
|---|---|---|
| `SECRET_KEY` | yes (prod) | Signs session cookies and tokens |
| `DATABASE_URL` | yes (prod) | Neon connection string. `postgres://` is normalized to psycopg 3 with `sslmode=require`. Empty → local SQLite |
| `ENV` | no | `production` enables secure cookies, HSTS and hides API docs |
| `BASE_URL` | no | Public URL for email links (falls back to the request URL) |
| `BREVO_API_KEY`, `MAIL_FROM`, `MAIL_FROM_NAME` | no | Email via Brevo HTTP API. Without a key, emails are printed to the console and new accounts are auto-verified |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | no | "Continue with Google" button (hidden when unset) |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | no | AI question generation (hidden when unset) |

## Project layout

```
app/
  main.py            FastAPI app, middleware, error handlers, /healthz
  config.py          settings (pydantic-settings) + DATABASE_URL normalization
  db.py              engine/session (Postgres or SQLite)
  deps.py            current user, require_role, CSRF
  sessions.py        signed-cookie sessions ("keep me signed in")
  security.py        argon2 hashing, one-time tokens, TOTP, CSRF tokens
  models/            SQLAlchemy models (users, content, assessments, gamification, comms, system)
  routers/           page routes
  services/          business logic (email, settings, curriculum, ...)
  templates/         Jinja2 templates (Bootstrap 5)
  static/            CSS, JS, images
alembic/             migrations
scripts/             create_admin.py, seed.py
tests/               pytest suite
docs/                manuals and checklists
```

## Security notes

- Passwords hashed with Argon2; login rate limit (10 per 5 min per IP) and account lockout (5 failures → 15 min).
- TOTP 2FA mandatory for admin and faculty; optional for students.
- CSRF token on every POST (form field or `X-CSRF-Token` header).
- Security headers and a Content-Security-Policy that only allows `cdn.jsdelivr.net`.
- Session cookies are `HttpOnly`, `SameSite=Lax` and `Secure` in production.
