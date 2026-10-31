"""Import every model so Base.metadata is complete (used by Alembic and tests)."""
from app.models.assessment import (  # noqa: F401
    ASSESSMENT_KINDS,
    Assessment,
    AssessmentQuestion,
    Attempt,
    AttemptAnswer,
    assessment_topics,
)
from app.models.comms import (  # noqa: F401
    GOAL_METRICS,
    Announcement,
    CalendarEvent,
    ForumPost,
    ForumThread,
    Goal,
    Message,
    Notification,
)
from app.models.content import (  # noqa: F401
    Category,
    Course,
    Question,
    Resource,
    ResourceView,
    StoredFile,
    Topic,
)
from app.models.gamification import Badge, PointsLedger, UserBadge  # noqa: F401
from app.models.system import ActivityLog, ErrorLog, ScrapeJob, SystemSetting  # noqa: F401
from app.models.user import MAJORS, ROLES, AuthToken, User  # noqa: F401
