"""
Admin routes package for the Bisq Support API.

This package organizes admin routes by domain:
- auth: Authentication (login, logout)
- feedback: Feedback management (8 endpoints)
- faqs: FAQ CRUD operations (4 endpoints)
- analytics: Dashboard and metrics (2 endpoints)
- vectorstore: Vector store management (2 endpoints)
"""

from app.routes.admin import analytics, auth, faqs, feedback, vectorstore
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


__all__ = [
    "analytics",
    "auth",
    "faqs",
    "feedback",
    "include_admin_routers",
    "vectorstore",
]
