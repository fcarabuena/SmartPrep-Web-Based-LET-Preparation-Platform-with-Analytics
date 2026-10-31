# Smart Prep — Frequently Asked Questions

### General

**Is Smart Prep free?**
Yes. It runs on Render's free web service and Neon's free PostgreSQL database. Email (Brevo), Google sign-in and AI
generation (Gemini) are optional free-tier services.

**Why is the site slow the first time I open it?**
Render's free plan puts the app to sleep after 15 minutes without visitors. The first visit wakes it up, which takes
about a minute. After that it is fast.

**Does it work on phones?**
Yes. The layout adapts to small screens; tap ☰ to open the menu.

### Accounts and sign-in

**I did not receive the verification email.**
Check spam. Then try to sign in and click **Resend verification email**. If email delivery is not configured on
your installation, accounts are verified automatically.

**My account is locked.**
After 5 wrong passwords the account locks for 15 minutes. Wait, or ask the administrator to unlock it.

**I lost the phone with my authenticator app (faculty/admin).**
Ask the administrator to use **Reset 2FA** on your account; you will set it up again at the next sign-in.
If you are the only administrator, run `scripts\create_admin.py --email <your email> --reset-2fa` from the project
folder with `DATABASE_URL` pointing at the live database.

**I received an account from the administrator. Why must I change my password?**
Accounts created by an administrator start with a temporary password. On your first sign-in you choose your own
password (and set up 2FA if you are faculty or admin) before you can use the system.

**What does "Keep me signed in" do?**
It keeps you signed in for 30 days on that browser. Without it, you are signed out when the browser closes or after
8 hours of inactivity. Do not use it on shared computers.

### Quizzes and exams

**What happens if my internet disconnects during an exam?**
Your answers are saved every few seconds. Reopen the exam to continue. The timer keeps running on the server, so
reconnect quickly.

**What is the passing score?**
75% on the first attempt, 80% on the second and 85% from the third attempt (administrators can change these).

**Why does my grade say "Missing"?**
The due date passed and you have no submitted attempt.

**What is the difference between Retake and Regenerate Questions?**
**Retake** starts a new graded attempt of the same assessment. **Regenerate Questions** creates an adaptive
practice set focused on your weak topics; it does not count as a graded attempt.

**Can I see the correct answers?**
Yes, after you submit: every item shows your answer, the correct answer and the rationalization.

### Progress and analytics

**How is the LET Readiness Score computed?**
It is a weighted average of your mastery (percent correct) per LET area. Secondary: Gen Ed 20%, Prof Ed 40%,
Specialization 40%. Elementary: Gen Ed 40%, Prof Ed 60%. Areas you have not practiced count as 0%.

**What are the Study Hot Zones?**
A color map of your mastery per course and topic (or per Exam 1/2/3): green ≥ 85%, yellow 75–84%, red < 75%. The
percentage is always written in the cell.

**How do I earn badges?**
Examples: Accuracy Ace (≥ 75% on a quiz), Perfect Score (100%), Persistence Pro (improve by 20+ points on a retake),
Master of Categories (≥ 90% on a category quiz), Streak 7 (7 study days in a row), First Steps (first quiz).
Faculty can also award special badges.

### Faculty

**Why are my imported, scraped or AI questions not visible to students?**
They are saved as **pending review**. Approve them in the **Review Queue** first.

**Is web scraping allowed?**
Only for sources that permit it (open educational resources, your institution's pages, or sites whose terms allow
it). Never scrape copyrighted reviewers. The scraper obeys robots.txt, identifies itself, waits 1 second between
requests and fetches at most 20 pages per job.

**How do I read the item analysis?**
*p* (difficulty) is the proportion who answered correctly: below 0.20 is very difficult, above 0.90 very easy.
*D* (discrimination) compares the top and bottom 27% of examinees: 0.40+ very good, 0.30–0.39 good, 0.20–0.29
fair, below 0.20 poor; a negative *D* often means a wrong answer key.

### Administration

**How do I back up the data?**
Admin › **Backups** › **Download ZIP** gives CSV exports of all core tables. Neon also keeps its own history.

**What are the free-tier limits?**
Render: sleeps after 15 minutes idle (about 1 minute to wake), 750 free instance hours per month, no persistent
disk, no outgoing SMTP (use Brevo's HTTP API). Neon: 1 GB storage per project, 100 compute-hours per month, no
expiry. Check System Health for the current database size.
