from app.routers import (
    admin_settings,
    admin_users,
    assessments_admin,
    auth,
    content,
    dashboard,
    exams,
    profile,
    questions,
    resources,
)

ROUTERS = [
    auth.router,
    dashboard.router,
    profile.router,
    admin_users.router,
    admin_settings.router,
    content.router,
    questions.router,
    resources.router,
    assessments_admin.router,
    exams.router,
]
