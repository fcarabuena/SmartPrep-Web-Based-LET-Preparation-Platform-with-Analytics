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
| 2 | Content: categories/courses/topics, question bank, review queue, import, resources | ⏳ |
| 3 | Assessments: exams/quizzes, timer, results, grades | ⏳ |
| 4 | Recommendations, adaptive practice, study plan, gamification | ⏳ |
| 5 | Analytics & reports | ⏳ |
| 6 | Notifications, inbox, calendar, goals, forum | ⏳ |
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
python scripts\seed.py          # categories, courses, topics
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
