"""
Admin routes package for the Bisq Support API.

This package organizes admin routes by domain:
- auth: Authentication (login, logout)
- feedback: Feedback management (8 endpoints)
- faqs: FAQ CRUD operations (4 endpoints)
- analytics: Dashboard and metrics (2 endpoints)
- vectorstore: Vector store management (2 endpoints)
- training: Auto-training pipeline management (9 endpoints)
- escalations: Escalation learning pipeline (7 endpoints)
"""

from app.routes.admin import (
    analytics,
    auth,
    escalations,
    faqs,
    feedback,
    training,
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
    app.include_router(training.router)
    app.include_router(escalations.router)


__all__ = [
    "analytics",
    "auth",
    "escalations",
    "faqs",
    "feedback",
    "include_admin_routers",
    "training",
    "vectorstore",
]
