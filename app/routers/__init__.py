from app.routers import admin_users, auth, dashboard, profile

ROUTERS = [
    auth.router,
    dashboard.router,
    profile.router,
    admin_users.router,
]
