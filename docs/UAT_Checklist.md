# Smart Prep — User Acceptance Testing (UAT) Checklist

**System:** Smart Prep: Web-Based LET Preparation Platform with Analytics
**Site:** Romblon State University – Cajidiocan Campus
**Tester:** ______________________ **Role tested:** ☐ Student ☐ Faculty ☐ Admin **Date:** ____________

Before testing, load demo data (`python scripts/seed_demo.py`) or use real accounts.
Demo passwords: admin `Admin12345`, faculty `Faculty123`, students `Student123` (accounts `@smartprep.demo`).
Mark each item **P** (pass) or **F** (fail) and write remarks for failures.

## 1. Login

| ID | Scenario | Steps | Expected result | P/F | Remarks |
|---|---|---|---|---|---|
| L-01 | Student registration | Open **Create account**, fill name, email, major, password ×2, submit | Account created; verification email sent (or auto-verified when email is not configured) | | |
| L-02 | Registration validation | Submit an invalid email, short password and mismatched confirmation | Clear error messages; no account created | | |
| L-03 | Email verification | Open the link from the verification email | "Email verified" message; sign-in works | | |
| L-04 | Student sign-in | Sign in with a valid student account | Student dashboard opens | | |
| L-05 | Wrong password | Sign in with a wrong password | "Invalid email or password"; no detail about which is wrong | | |
| L-06 | Account lockout | Enter a wrong password 5 times | Account temporarily locked for 15 minutes | | |
| L-07 | Keep me signed in | Sign in with **Keep me signed in**, close and reopen the browser | Still signed in | | |
| L-08 | Faculty 2FA setup | First faculty/admin sign-in | Asked to scan a QR code and enter a 6-digit code before reaching the dashboard | | |
| L-09 | Faculty 2FA sign-in | Sign in again as faculty | Asked for the authenticator code; wrong code is rejected | | |
| L-10 | Forgot password | Use **Forgot password?** and the emailed link | New password works; old password does not; link cannot be reused | | |
| L-11 | Sign out | Click profile menu › **Sign out** | Returned to login; protected pages redirect to login | | |
| L-12 | Google sign-in (if configured) | Click **Continue with Google** | Signed in / account created as student | | |

## 2. User Profile Management

| ID | Scenario | Steps | Expected result | P/F | Remarks |
|---|---|---|---|---|---|
| P-01 | View profile | Profile menu › **My Profile** | Name, email, role, major, level, badges shown | | |
| P-02 | Update details | Change full name, major and bio; save | "Profile updated"; sidebar/topbar shows new name; Major Core content follows the new major | | |
| P-03 | Change password | Enter current + new password | Success; other devices signed out | | |
| P-04 | Optional student 2FA | Set up 2FA from profile, then disable with a code | 2FA turns on and off | | |
| P-05 | Admin: create user | Admin › Users › **New user** (faculty role) | User created; temporary password shown once if none entered | | |
| P-06 | Admin: edit / deactivate / delete | Edit role, deactivate, then delete a user | Changes saved; deactivated user cannot sign in | | |
| P-07 | Admin: reset 2FA / unlock | Use the row menu on a locked or 2FA user | User can sign in again / set up 2FA again | | |
| P-08 | Role restrictions | As a student, open `/admin/users` | "Access denied" (403) page | | |

## 3. Adaptive Learning System

| ID | Scenario | Steps | Expected result | P/F | Remarks |
|---|---|---|---|---|---|
| A-01 | Study Plan | Student › **Study Plan** | Weakest topics first with mastery %, level and resources | | |
| A-02 | Topic practice | Click **Start practice** on a weak topic | 10-item practice set from that topic begins | | |
| A-03 | Adaptive review | Click **Adaptive review (15 items)** | Mixed set weighted to weak topics | | |
| A-04 | Regenerate Questions | On a result page click **Regenerate Questions** | New set in the same scope, avoiding recently seen items; does not use up graded attempts | | |
| A-05 | Difficulty by mastery | Compare sets for a weak (<75%) and strong (≥85%) topic | Weak topic gets more easy/medium items; strong topic gets more hard items | | |
| A-06 | LET readiness | Dashboard / Progress | Readiness score with band (Not ready / Developing / Ready) and category breakdown | | |
| A-07 | Progress analytics | **Progress** page, filter by category and course | Charts, Study Hot Zones (topics and Exam 1/2/3), tables and trends update | | |

## 4. Content Recommendations

| ID | Scenario | Steps | Expected result | P/F | Remarks |
|---|---|---|---|---|---|
| R-01 | Recommendations after a quiz | Finish a quiz with several wrong answers | "Recommended for you" lists missed topics with practice links and resources | | |
| R-02 | Proportional count | Miss 1 item in topic X and 3 in topic Y | About 1 resource for X and 3 for Y (capped by settings) | | |
| R-03 | Level matching | Check the level of recommended resources | Foundational for mastery <75%, standard 75–84%, advanced ≥85% (fewer items) | | |
| R-04 | View tracking & points | Open a recommended resource | View counted; points awarded (daily cap applies) | | |
| R-05 | Faculty adds resource | Faculty › Resources › New (link and a small PDF) | Saved; PDF over 5 MB or wrong type is rejected | | |

## 5. Gamification Features

| ID | Scenario | Steps | Expected result | P/F | Remarks |
|---|---|---|---|---|---|
| G-01 | Points | Complete and pass a quiz | Points for correct answers, completion and passing appear in **Gamification › Recent points** | | |
| G-02 | Levels | Earn enough points | Level and progress bar increase | | |
| G-03 | Badges | Score ≥75% / 100% / improve by 20+ points | Accuracy Ace / Perfect Score / Persistence Pro awarded with a notification | | |
| G-04 | Leaderboards | Open **Leaderboards**: overall, category, course, game | Rankings appear; first-attempt passers rank above re-takers on ties | | |
| G-05 | Visibility toggle | Faculty hides leaderboards | Students see "hidden by your faculty" | | |
| G-06 | Quiz bee / games | **Quick Quiz Bee** and faculty games | Timed set across subjects; auto-submits at 0:00 | | |
| G-07 | Staff badges | Faculty › Badges: create and award a manual badge | Badge appears on the student's profile | | |

## 6. LET Question Repository

| ID | Scenario | Steps | Expected result | P/F | Remarks |
|---|---|---|---|---|---|
| Q-01 | Browse & filter | Faculty › Question Bank; filter by category, topic, difficulty, status, source | Matching items listed | | |
| Q-02 | Create question | New question with 4 choices, key, rationalization | Saved; appears in the bank | | |
| Q-03 | Duplicate check | Type an existing stem | Live "Similar" warning; identical stem is blocked | | |
| Q-04 | Review queue | Approve and reject pending items | Status changes; only approved items reach students | | |
| Q-05 | CSV / Excel import | Download template, fill, upload, preview, confirm | Row-level errors shown; valid rows imported as pending review | | |
| Q-06 | Web scraping | Faculty › Web Scraping with a permitted URL | Polite fetch; editable preview; saved as pending review | | |
| Q-07 | AI generation (if configured) | AI Generator: topic, difficulty, count | Validated items saved as pending review | | |
| Q-08 | Item analysis | Faculty › Item Analysis for an assessment | Difficulty and discrimination indices with flags | | |

## 7. Exam Preparation Module

| ID | Scenario | Steps | Expected result | P/F | Remarks |
|---|---|---|---|---|---|
| E-01 | Create assessment | Faculty › Assessments › New (mock exam) with time limit, due date, attempts, access code | Saved and published | | |
| E-02 | Examinations page | Student › Examinations tabs (Prof Ed / Major Core / Gen Ed) | Exams listed with instructions, time limit, due date / "Past Due" | | |
| E-03 | Access code | Start an exam with a wrong then right code | Wrong code rejected; right code starts the exam | | |
| E-04 | Timer & autosave | Answer some items, refresh the page | Answers kept; timer continues from the server time | | |
| E-05 | Auto-submit | Let the timer reach 0 | Attempt submitted automatically | | |
| E-06 | Results | Submit an exam | Score, pass/fail, chosen vs correct answer and rationalization per item | | |
| E-07 | Thresholds | Take the same exam 3 times | Passing score 75% → 80% → 85% | | |
| E-08 | Max attempts / due date | Exceed max attempts; open after the due date | Start is blocked with a clear message | | |
| E-09 | Grades | **Grades** with filters; **Print Grades** and **PDF** | Passed / Failed / Missing / Not attempted; printable and PDF output | | |
| E-10 | Faculty submissions | Faculty › Submissions | All attempts with scores; can open each result | | |

## 8. Content Search

| ID | Scenario | Steps | Expected result | P/F | Remarks |
|---|---|---|---|---|---|
| S-01 | Learning materials search | Student › Learning Materials: search a keyword | Matching resources by title, topic or course | | |
| S-02 | Filters | Filter by course, type and level | List narrows correctly | | |
| S-03 | Major restriction | Search as a Math major for an English-major resource | Not shown | | |
| S-04 | Question search (staff) | Question Bank search box | Matches on stem and competency | | |
| S-05 | Inbox search | Inbox search by subject or sender | Matching messages | | |
| S-06 | Forum search | Forum search box | Matching threads | | |

## Sign-off

| | Name | Signature | Date |
|---|---|---|---|
| Tester | | | |
| Faculty adviser | | | |
| Proponent | | | |
