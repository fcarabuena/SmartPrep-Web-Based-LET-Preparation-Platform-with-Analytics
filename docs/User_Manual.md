# Smart Prep — User Manual

Smart Prep is a web-based review platform for the Licensure Examination for Teachers (LET). It works on any
modern browser on a phone, tablet or computer.

- [Getting started](#getting-started)
- [For students](#for-students)
- [For faculty](#for-faculty)
- [For administrators](#for-administrators)

---

## Getting started

### Create an account (students)
1. Open the Smart Prep address and click **Create an account**.
2. Enter your full name, email, **program/major** (Elementary or your BSEd major) and a password with letters and
   numbers (at least 8 characters).
3. Open the verification link sent to your email, then sign in.
   If you did not receive it, click **Resend verification email** on the sign-in page after a failed sign-in.

Faculty and administrator accounts are created by the administrator.

### Sign in
- Enter your email and password. Tick **Keep me signed in** on your own device only.
- **Forgot password?** sends a reset link that is valid for one hour.
- Faculty and administrators must use an authenticator app (Google Authenticator, Microsoft Authenticator or
  Authy). On the first sign-in, scan the QR code and type the 6-digit code. After that, enter the current code
  every time you sign in. If you lose your phone, ask the administrator to reset your 2FA.
- After 5 wrong passwords the account is locked for 15 minutes.

### Navigation
The left sidebar lists everything your role can use. On a phone, tap ☰ to open it. The top bar shows your inbox
and notification bell (with unread counts) and your profile menu (**My Profile**, **Sign out**).

---

## For students

### Dashboard
Shows your **LET Readiness Score**, points, level, badges, rank, upcoming deadlines, goals, topics to focus on next
and recent results.

**LET Readiness Score** = weighted mastery of the LET areas:
- Secondary (BSEd): General Education 20%, Professional Education 40%, Specialization 40%
- Elementary (BEEd): General Education 40%, Professional Education 60%

Bands: **Not ready** (below 60%), **Developing** (60–74%), **Ready** (75% and above).

### Examinations (mock exams)
Tabs: **Professional Education**, **Major Core**, **General Education**. Each card shows the number of items, time
limit, due date (or **Past Due**), attempts used and whether an access code is needed. Read the instructions, then
click **Start**.

### Quizzes
Practice quizzes grouped by category and course (also reachable from the sidebar's nested **Quizzes** menu).

### Taking a quiz or exam
- One question at a time; use **Next/Previous** or the numbered navigator.
- Answers are **saved automatically** (every few seconds and whenever you choose an answer).
- The timer is kept by the server. Closing the page does not stop it. When time runs out the attempt is submitted
  automatically.
- Click **Submit** when done.

**Passing score:** 75% on the 1st attempt, 80% on the 2nd, 85% from the 3rd attempt onward.

### Results
You see your score, whether you passed, each item with **your answer**, the **correct answer** and the
**rationalization**, plus **Recommended for you** (topics to practice and resources). Buttons:
- **Retake** – a new graded attempt (if attempts remain and the due date has not passed).
- **Regenerate Questions** – a new adaptive practice set from the same scope that focuses on your weak topics and
  avoids items you saw recently. It does not use up graded attempts.

### Grades
All published assessments with status **Passed**, **Failed**, **Missing** (due date passed without an attempt) or
**Not attempted**, and your best score. Filter by category or course. **Print Grades** prints a clean page;
**PDF** downloads a copy.

### Learning Materials
Search videos, articles and files by keyword, course, type or level. Opening a resource counts as a view;
recommended resources also earn points.

### Progress
Your analytics: mastery per category, rank, badges, questions answered and time spent, quiz and exam completion,
**Study Hot Zones** (green ≥ 85%, yellow 75–84%, red < 75%; switch between topics and Exam 1/2/3), progress tables
by category and by course, attempted vs correct, weekly trend, strengths and weaknesses.

### Study Plan
Your weakest topics first, with mastery, the recommended level, resources and **Start practice**. **Adaptive review**
creates a 15-item set across your weakest topics.

### Gamification
Points, level, daily streak, rank, badges (earned and locked), recent points, faculty games and quiz bees, and the
**Quick Quiz Bee** (15 random questions in 5 minutes). **Leaderboards** rank reviewees overall, by category, by
course and by game (ties go to those who passed on the first attempt).

### Goals
Create goals such as "Answer 150 questions" or "Reach 80% average" with a deadline. Progress updates automatically
and goals appear on your dashboard and calendar.

### Calendar, Inbox, Forum, Notifications
- **Calendar** – due dates, goal deadlines, class events and your own events (Month / Week / Agenda, **Today**).
- **Inbox** – messages with faculty and classmates; folders Inbox, Unread, Sent, Drafts; filter by course; search.
- **Forum** – start or join discussions per category or course.
- **Notifications** – new content, published assessments, items due within 24 hours, feedback, badges, replies and
  announcements.

---

## For faculty

### Content
- **Categories & Topics** – add courses (optionally only for one major) and topics.
- **Question Bank** – search and filter; create or edit items (four choices, key, rationalization, difficulty,
  competency). A live check warns about similar questions; identical stems are blocked. Bulk approve, reject or
  delete.
- **Review Queue** – approve or reject pending items (imported, scraped and AI-generated items always start here).
- **Import Questions** – download the CSV or Excel template, fill one question per row, upload, review row-level
  errors in the preview and confirm.
- **Resources** – add links/videos/articles or upload small files (PDF, DOCX, PPTX, images; max 5 MB); set the topic
  and level (foundational / standard / advanced).
- **Web Scraping** – only for sources that permit it. Enter URLs and a target topic, pick the parser (numbered MCQ
  text or CSS selectors), start the job, edit the preview and save. Everything goes to the review queue.
- **AI Generator** (only if enabled) – generate questions for a topic and difficulty, or use **Improve wording with
  AI** on a question. Results always need review.

### Assessments
**Assessments › New** (practice quiz, mock exam, timed game or quiz bee). Choose category/course/topics, number of
items, auto-draw (by difficulty) or manual pick, randomization, time limit, access code, open/due dates, max
attempts, points and pass bonus, then **Published**. Use **Pick questions** for manual selection and **Preview** to
try it. **Submissions** lists every attempt with a link to the full result.

### Monitoring
- **Class Analytics** – average score, pass rate, participation, category performance, weekly trend, most-missed
  topics and at-risk students (7 / 30 / 90 days / all time).
- **At-Risk Students** – low readiness or inactive for N days. Open a student to see their full progress and click
  **Send feedback** (delivered to their inbox with a notification).
- **Item Analysis** – difficulty index *p*, discrimination index *D* (upper vs lower 27%), choice counts and a
  Retain / Revise / Reject suggestion for each item.
- **Reports** – user activity, performance, content usage or engagement for a date range; preview, then export CSV,
  Excel or PDF.
- **Leaderboards** and **Badges** – hide/show leaderboards for students; create badges and award manual ones.
- **Announcements** – send to roles, to students of a course or to selected students (optionally by email).

---

## For administrators
Everything faculty can do, plus:
- **Users** – **Create user** (name, email, role admin/faculty/student, major for students, temporary password or
  a generated one shown once). The new user must choose their own password at first sign-in, and admin/faculty
  must also set up 2FA. Also edit, change roles, activate/deactivate, unlock, reset 2FA and delete.
- **Lost your own authenticator?** Ask another admin to reset your 2FA, or run
  `scripts\create_admin.py --email <you> --reset-2fa` against the database (see README).
- **System Analytics** – DAU/WAU/MAU, logins and registrations per day, peak activity heatmap, session length,
  popular content, content access, question sources and approval rates.
- **Settings** – pass thresholds, readiness weights and bands, at-risk rules, recommendation cap, gamification
  points and level step, leaderboard visibility and self-registration.
- **System Health** – uptime, request counts, recent errors, database size and table sizes.
- **Backups** – download a ZIP of CSV exports of the core tables (passwords and 2FA secrets are never exported).
