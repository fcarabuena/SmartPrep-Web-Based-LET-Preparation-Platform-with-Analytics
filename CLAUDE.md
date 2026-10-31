# Smart Prep — Project Spec (source of truth)

Build my MIT capstone web app "Smart Prep: Web-Based LET Preparation Platform with Analytics" in this repo (https://github.com/fcarabuena/SmartPrep-Web-Based-LET-Preparation-Platform-with-Analytics). It helps LET (Licensure Examination for Teachers, Philippines) reviewees of Romblon State University Cajidiocan Campus prepare, with progress tracking, gamification and analytics.

## HOW TO WORK
- First, save this whole spec as CLAUDE.md at the repo root so you can re-read it in later sessions.
- Then build phase by phase (list at the bottom). After each phase: run pytest, make sure `uvicorn app.main:app --reload` works, update README, git commit with message "Phase N: <name>", give me a short summary + how to test it, then continue to the next phase. Stop and ask me only if you are truly blocked.
- My laptop is Windows 11. Give Windows venv commands in README.

## HARD CONSTRAINTS (must be 100% free to host)
- Deploy on ONE Render FREE web service (no paid workers, no cron jobs, no persistent disk). Include render.yaml Blueprint: runtime python, plan free, buildCommand "pip install -r requirements.txt && alembic upgrade head", startCommand "uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'", healthCheckPath /healthz, env PYTHON_VERSION=3.12.7, ENV=production, SECRET_KEY generateValue, DATABASE_URL sync:false, optional keys sync:false.
- Database: PostgreSQL on Neon free tier via DATABASE_URL (normalize postgres:// to psycopg driver, sslmode=require). If DATABASE_URL is unset, use SQLite locally. Code must work on both.
- Render free blocks SMTP: send email via Brevo HTTP API (BREVO_API_KEY, MAIL_FROM). If no key, print links to console and auto-verify in development.
- No files on local disk in production. Resources are mostly links; small uploads (PDF/DOCX/PPTX/images, max 5 MB) are stored in Postgres as bytes.
- App must run with only DATABASE_URL and SECRET_KEY. Optional features (Google login, Brevo, Gemini AI) hide themselves when env vars are missing.
- Background work runs inside the web process (FastAPI BackgroundTasks). Deadline reminders are checked lazily on page load (no cron).
- GET /healthz returns 200 without touching the DB. Fast startup; migrations only in build command.
- Never commit .env; keep .env.example updated. Seed data must be ORIGINAL LET-style questions, not copied from copyrighted reviewers.

## TECH STACK
Python 3.12, FastAPI, Uvicorn, Jinja2 templates, Bootstrap 5 (CDN), vanilla JS, Chart.js and FullCalendar (CDN), SQLAlchemy 2 + Alembic, psycopg 3, pydantic-settings, Starlette SessionMiddleware (secure cookies in prod), bcrypt/argon2 password hashing, CSRF on all POST forms, pyotp + qrcode for TOTP 2FA, Authlib for optional Google login, httpx + BeautifulSoup4 for scraping, openpyxl (Excel), reportlab (PDF), pytest.
Layout: app/(main.py, config.py, db.py, models/, routers/, services/, templates/, static/), alembic/, tests/, scripts/, docs/.

## ROLES AND PERMISSIONS (enforce with a require_role dependency on every route)
- Admin: full access; manage users (create/edit/activate/deactivate/delete/assign role), system settings, exam content, notifications/announcements, admin dashboard, system-wide analytics, reports export (PDF/CSV/Excel), system health, backups.
- Faculty: question bank and resources, create/administer quizzes/exams/games, web scraping + review of scraped/AI content, monitor individual and class progress, at-risk students, send feedback messages, faculty dashboard. Limited settings.
- Student: self-register (name, email, password, major) with email verification, dashboard, take quizzes and mock exams, own analytics, gamification, personalized study plan, calendar, inbox, goals, forum, profile.
- Admin and faculty must use TOTP 2FA. Login rate limit + lockout. Forgot/reset password with expiring tokens. "Keep me signed in".

## CONTENT
Categories -> courses -> topics -> questions.
- General Education (English, Filipino, Mathematics, Science, Social Science)
- Professional Education (Foundations of Education, Theories of Learning, Curriculum Development, Assessment of Learning, Classroom Management, Teaching Methods)
- Specialization/Major Core by student major (Mathematics, English, Filipino, Science/Biology, Social Studies, TLE)
Question: 4 choices A-D, correct answer, rationalization (why right + why others wrong), difficulty, competency tag, source_type (manual, csv_import, scraped, ai_generated), source_url, status (draft, pending_review, approved, rejected), created_by, reviewed_by. Students only see APPROVED. Scraped/AI items always go to pending_review.
Resource: title, type (video/article/file/link), url or stored file, topic, level (foundational/standard/advanced), approved, view tracking.

## ASSESSMENTS
- Types: practice quiz, mock exam (LET simulation), timed quiz game, quiz bee (random questions across subjects vs the clock).
- Fields: category/course/topics, question count, manual pick or auto-draw by topic/difficulty, randomize questions and choices, time limit, access code, open/due dates, max attempts, published, points config.
- Pass threshold 75% on attempt 1, 80% on attempt 2, 85% on attempt 3+ (admin-configurable; store threshold used per attempt).
- Timer enforced server-side (started_at); autosave; auto-submit at timeout.
- Results: score, pass/fail, per-question chosen vs correct + rationalization, recommended resources, Retake, "Regenerate Questions" (adaptive set weighted to weak topics, avoiding recently seen).
- Grades page: title, category, due date, status Passed/Failed/Missing/Not attempted, score; filters by category/course; Print Grades (print CSS + PDF).
- Store attempts (user, assessment, attempt_no, start, submit, score, threshold, passed, time) and answers (question, choice, is_correct, time spent).

## RULE-BASED RECOMMENDATIONS AND ADAPTIVE LEARNING
- Resources per topic proportional to wrong answers in that topic (1 wrong = 1, 3 wrong = 3, capped).
- First priority: related practice questions from the same topic; then videos/articles.
- Mastery <75% -> foundational content and easier questions; 75-84% -> standard; >=85% -> fewer recommendations, advanced/harder content.
- Adaptive quiz: topic weight = (1 - mastery), difficulty mix by mastery.
- Track resource views (award points). Personalized Study Plan page: weakest topics first with questions/resources and "Start practice".

## GAMIFICATION
- Points ledger rows with reason: complete quiz, pass, perfect score, improvement, series of quizzes in a time window, viewing recommended resources, daily streak. Levels from total points.
- Data-driven badges: "Accuracy Ace" (>=75% on a quiz), "Persistence Pro" (+20 points improvement over consecutive attempts), "Master of Categories" (>=90% on a quiz in a category), "Perfect Score", "Streak 7", "First Steps". Faculty/admin can add badges. Show on profile, notify when earned.
- Leaderboards: overall, by category, by course, by game, filterable; faculty toggles public visibility; on ties, first-attempt passers rank above re-attempt passers.

## ANALYTICS (core of the capstone, make it polished and correct; aggregate in SQL, index FKs, 60s cache for heavy queries, pages < 3 s)
- Student Progress page: % per category bar chart; my rank, badges, questions answered, time spent; quiz and exam completion donuts; "Study Hot Zones" heatmap (rows courses, columns topics or Exam 1/2/3; green >=85, yellow 75-84, red <75); progress by category table (Exam 1/2/3 + improvement); progress by course table (correct %, incorrect %, improvement, time spent mins); line chart attempted vs correct per category/course; weekly trend; strengths/weaknesses; recommended resources; category/course filters.
- LET Readiness Score: weighted mastery. Defaults Secondary = Gen Ed 20%, Prof Ed 40%, Specialization 40%; Elementary = Gen Ed 40%, Prof Ed 60%; configurable. Bands Not ready / Developing / Ready. Show on student dashboard.
- Faculty: class KPIs (avg score, pass rate, participation), category performance, weekly trend, most-missed topics, at-risk students (low readiness or inactive N days), per-student drill-down with "send feedback", item analysis per question (difficulty index, discrimination index upper/lower 27%, flag bad items).
- Admin: DAU/WAU/MAU, registrations, logins, attempts, popular content, avg session length, logins per day, peak activity heatmap (hour x weekday), content access counts, question counts by source and approval rate, system health (recent errors, request counts, DB size).
- Report builder: type (user activity, performance, content usage, engagement) + date range + filters, preview, export CSV/Excel/PDF.
- activity_log table for logins, page views, durations (lightweight).

## COMMUNICATION AND PLANNING
- Notifications: bell with unread count + page; triggers: new content, assessment published, due in 24h, feedback, badge, admin/faculty announcements (target roles, courses, or students); optional email via Brevo.
- Inbox: direct messages student/faculty/admin, threads, filters by course and Inbox/Sent/Unread/Draft, search.
- Calendar (FullCalendar): month/week/agenda, Today button; due dates, goals, events.
- Goals: student goals with targets and deadlines, auto progress, on dashboard and calendar.
- Discussion forum: threads per category/course, replies, faculty pin/lock/delete.

## CONTENT INPUT
- Manual forms; CSV/Excel import with downloadable template, preview and row-level errors.
- Web scraping for faculty: job with URL(s), CSS-selector parser or "numbered MCQ text" parser, target topic; respect robots.txt, custom User-Agent, 1 req/s, 10 s timeout, max 20 pages; preview/edit extracted rows, save as pending_review; also capture resource links; reminder to scrape only permitted sources.
- Optional AI generation with Google Gemini free API (GEMINI_API_KEY via httpx): generate N questions with rationalizations for a topic/difficulty, or improve wording; strict JSON, validated, saved as pending_review; hidden without key.

## UI AND NON-FUNCTIONAL
- Clean, modern, mobile-responsive Bootstrap UI. Left sidebar: Dashboard, Examinations (tabs Prof Ed / Major Core / Gen Ed, with instructions panel, time limit, due/"Past Due", access code with show toggle), Quizzes (categories with nested courses), Gamification, Progress, Study Plan, Calendar, Inbox, Forum. Top bar with bell and profile. Login page with email/password, forgot password, keep me signed in, Google button (if configured), create account.
- Security headers + CSP allowing only used CDNs, input validation, upload type/size checks, no secrets in logs, 404/403/500 pages, accessible forms.
- Admin backup: download ZIP of CSV exports of core tables.

## PHASES (do in order, commit after each)
1. Foundation: scaffold, requirements.txt (pinned), .gitignore, .env.example, config, DB, ALL models + first Alembic migration, auth (register, verify, login, logout, reset, 2FA, optional Google), roles, base layout, empty dashboards, profile, admin user management, /healthz, CSRF, render.yaml, scripts/create_admin.py and scripts/seed.py (categories/courses/topics), tests.
2. Content: categories/courses/topics CRUD, question bank with filters/search/duplicate check, review queue, CSV/Excel import, resources (links + small DB uploads), student learning materials browser with search, 10 original seed questions per sample topic.
3. Assessments: create/edit, Examinations and Quizzes pages, take-assessment flow with timer, results with rationalizations, thresholds, retakes, grades + print/PDF, faculty submissions view.
4. Recommendations, adaptive Regenerate, Study Plan, points/levels/badges, leaderboards, timed games, quiz bee, gamification settings.
5. Analytics: student progress page and dashboard with readiness, faculty dashboard with at-risk and item analysis, admin dashboard, report builder with CSV/Excel/PDF.
6. Notifications, announcements, inbox, calendar, goals, forum.
7. Web scraping module and optional Gemini question generation (tests use HTML fixtures and a mocked AI client, no live network).
8. Hardening: route-permission test for every role, security headers, N+1 and index review, scripts/seed_demo.py (1 admin, 3 faculty, 60 students, 300+ original questions, 8 weeks of improving attempts, badges, messages, forum posts; with a wipe flag), backups page, error pages, docs/UAT_Checklist.md (Login, User Profile Management, Adaptive Learning System, Content Recommendations, Gamification Features, LET Question Repository, Exam Preparation Module, Content Search), docs/User_Manual.md, docs/FAQ.md, final README with Mermaid architecture diagram, local setup, free deployment steps on Render + Neon, env vars, and free-tier limits (Render sleeps after 15 min idle, ~1 min wake, 750 free hours/month, no disk, no SMTP; Neon 1 GB storage, 100 compute-hours/month, no expiry).

At the very end, tell me exactly what I must do by hand to deploy: create the Neon project and copy its connection string, Render > New > Blueprint > pick this repo > paste DATABASE_URL > Free plan, then run scripts/create_admin.py and scripts/seed_demo.py locally with DATABASE_URL pointing at Neon.

## Dev notes (kept by Claude)
- Local dev machine has Python 3.13 (no 3.12); code must stay 3.12-compatible (Render uses 3.12.7).
- Progress per phase is recorded in git history ("Phase N: <name>") and README "Build status" section.
- FastAPI 0.162 keeps included routers as `_IncludedRouter` wrappers in `app.routes`; always walk routes with
  `app.routing_util.iter_api_routes` (used by `has_route()` for the sidebar and by the permission tests).
- Jinja macros that need `csrf_token` must be imported `with context`. No inline `<script>`/`on*=` handlers (CSP);
  pass data to JS via `<script type="application/json">`.
- Windows shell: run Python edit scripts with `PYTHONUTF8=1`; heredocs containing quotes can break in the Bash tool,
  so write scripts to the scratchpad instead.
- Tests: `.venv\Scripts\python -m pytest` (in-memory SQLite, mocked network, fast Argon2 params in conftest).
