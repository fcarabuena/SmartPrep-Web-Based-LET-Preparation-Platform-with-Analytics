from app.routers import admin_users, auth, content, dashboard, profile, questions, resources

ROUTERS = [
    auth.router,
    dashboard.router,
    profile.router,
    admin_users.router,
    content.router,
    questions.router,
    resources.router,
]
