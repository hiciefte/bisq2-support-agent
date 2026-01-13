"""
Admin routes package for the Bisq Support API.

This package organizes admin routes by domain:
- auth: Authentication (login, logout)
- feedback: Feedback management (8 endpoints)
- faqs: FAQ CRUD operations (4 endpoints)
- analytics: Dashboard and metrics (2 endpoints)
- vectorstore: Vector store management (2 endpoints)
- queue: Moderator review queue (5 endpoints)
- pending_responses: Simplified pending response endpoints (4 endpoints)
- shadow_mode: Two-phase shadow mode workflow (11 endpoints)
- similar_faqs: Similar FAQ review queue (4 endpoints)
"""

from app.routes.admin import (
    analytics,
    auth,
    faqs,
    feedback,
    pending_responses,
    queue,
    shadow_mode,
    similar_faqs,
    vectorstore,
)
from fastapi import FastAPI


def include_admin_routers(app: FastAPI) -> None:
    """Include all admin routers in the FastAPI application.

    Args:
        app: FastAPI application instance
    """
    # Include authentication router (no auth required for login/logout)
    app.include_router(auth.router)

    # Include protected admin routers (auth required)
    app.include_router(feedback.router)
    app.include_router(faqs.router)
    app.include_router(analytics.router)
    app.include_router(vectorstore.router)
    app.include_router(queue.router)
    app.include_router(pending_responses.router)
    app.include_router(pending_responses.test_router)  # Test endpoints (no auth)
    app.include_router(shadow_mode.router)
    app.include_router(similar_faqs.router)


__all__ = [
    "analytics",
    "auth",
    "faqs",
    "feedback",
    "include_admin_routers",
    "pending_responses",
    "queue",
    "shadow_mode",
    "similar_faqs",
    "vectorstore",
]
