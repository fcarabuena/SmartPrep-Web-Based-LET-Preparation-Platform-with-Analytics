"""Create (or promote) an admin account, or recover an account's two-factor authentication.

Usage (Windows):
    .venv\\Scripts\\python scripts\\create_admin.py --email admin@example.com --name "Site Admin"
        Create or promote an admin. You will be prompted for a password unless --password is given.
        The admin must set up an authenticator app (TOTP) at first sign-in.

    .venv\\Scripts\\python scripts\\create_admin.py --email admin@example.com --reset-2fa
        Lost phone? Removes the account's authenticator link and unlocks it (password unchanged).
        The next sign-in shows a new QR code to scan.

Set DATABASE_URL to the Neon connection string first to act on the live database.
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password, password_problems  # noqa: E402


def reset_2fa(email: str) -> int:
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(func.lower(User.email) == email))
        if user is None:
            print(f"No account with email {email}. Check DATABASE_URL points at the right database.")
            return 1
        user.totp_secret = None
        user.totp_enabled = False
        user.failed_logins = 0
        user.locked_until = None
        user.session_version += 1  # signs out existing sessions
        db.commit()
        print(f"2FA reset for {email} ({user.role}). Sign in with your password and scan the new QR code.")
        return 0
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or promote a Smart Prep admin user, or reset 2FA")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="Administrator")
    parser.add_argument("--password", help="omit to be prompted")
    parser.add_argument("--reset-2fa", action="store_true",
                        help="only remove the authenticator link (and lockout) of an existing account")
    args = parser.parse_args()
    email = args.email.strip().lower()

    if args.reset_2fa:
        return reset_2fa(email)

    password = args.password or getpass.getpass("Password: ")
    problems = password_problems(password)
    if problems:
        print("\n".join(problems))
        return 1

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(func.lower(User.email) == email))
        if user:
            user.role = "admin"
            user.password_hash = hash_password(password)
            user.is_active = True
            user.email_verified = True
            user.must_change_password = False
            user.session_version += 1
            action = "promoted/updated"
        else:
            user = User(email=email, full_name=args.name, role="admin", password_hash=hash_password(password),
                        is_active=True, email_verified=True)
            db.add(user)
            action = "created"
        db.commit()
        print(f"Admin {email} {action}. Sign in at /login and set up 2FA with an authenticator app.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
