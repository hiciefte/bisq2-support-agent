"""
FastAPI application for the Bisq Support Assistant.
This module sets up the API server with routes, middleware, and error handling.
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, Dict

from app.core.config import get_settings
from app.core.error_handlers import base_exception_handler, unhandled_exception_handler
from app.core.exceptions import BaseAppException
from app.core.tor_metrics import (
    update_cookie_security_mode,
    update_tor_service_configured,
)
from app.db.run_migrations import run_migrations
from app.middleware import TorDetectionMiddleware
from app.routes import chat, feedback_routes, health, onion_verify
from app.routes.admin import include_admin_routers
from app.services.faq_service import FAQService
from app.services.feedback_service import FeedbackService
from app.services.simplified_rag_service import SimplifiedRAGService
from app.services.tor_monitoring_service import TorMonitoringService
from app.services.wiki_service import WikiService
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from prometheus_fastapi_instrumentator import Instrumentator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("app.main")

# Settings will be lazily initialized when first accessed
# No module-level initialization to avoid side effects during imports/testing

# Environment variable logging removed due to secret leakage risk
# For local debugging, manually inspect specific variables as needed


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Application startup...")

    # Initialize services
    settings = get_settings()
    app.state.settings = settings

    # Create data directories (avoid import-time I/O)
    logger.info("Creating data directories...")
    settings.ensure_data_dirs()

    # Run database migrations before initializing services
    logger.info("Running database migrations...")
    db_path = os.path.join(settings.DATA_DIR, "feedback.db")
    run_migrations(db_path)
    logger.info("Database migrations completed")

    logger.info("Initializing WikiService...")
    wiki_service = WikiService(settings=settings)

    logger.info("Initializing FeedbackService...")
    feedback_service = FeedbackService(settings=settings)

    logger.info("Initializing FAQService...")
    faq_service = FAQService(settings=settings)

    logger.info("Initializing SimplifiedRAGService...")
    rag_service = SimplifiedRAGService(
        settings=settings,
        feedback_service=feedback_service,
        wiki_service=wiki_service,
        faq_service=faq_service,
    )

    # Set up the RAG service (loads data, builds vector store)
    await rag_service.setup()

    # Assign services to app state
    app.state.feedback_service = feedback_service
    app.state.faq_service = faq_service
    app.state.rag_service = rag_service
    app.state.wiki_service = wiki_service

    # Initialize Tor metrics
    logger.info("Initializing Tor metrics...")
    tor_configured = bool(settings.TOR_HIDDEN_SERVICE)
    update_tor_service_configured(tor_configured, settings.TOR_HIDDEN_SERVICE)
    update_cookie_security_mode(settings.COOKIE_SECURE)
    logger.info(
        f"Tor metrics initialized - Configured: {tor_configured}, Cookie Secure: {settings.COOKIE_SECURE}"
    )

    # Initialize and start Tor monitoring service
    logger.info("Initializing Tor monitoring service...")
    tor_monitoring_service = TorMonitoringService(settings=settings)
    app.state.tor_monitoring_service = tor_monitoring_service
    await tor_monitoring_service.start()
    logger.info("Tor monitoring service started")

    # Yield control to the application
    yield

    # Shutdown
    logger.info("Application shutdown...")

    # Stop Tor monitoring service
    if hasattr(app.state, "tor_monitoring_service"):
        await app.state.tor_monitoring_service.stop()

    # Perform any cleanup here if needed
    # For example, rag_service might have a cleanup method
    if hasattr(app.state.rag_service, "cleanup"):
        await app.state.rag_service.cleanup()


# Create FastAPI application
settings = get_settings()
app = FastAPI(
    title=settings.PROJECT_NAME,
    docs_url="/api/docs",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)


# Custom OpenAPI with security scheme
def custom_openapi() -> Dict[str, Any]:
    """Generate custom OpenAPI schema with admin authentication.

    Returns:
        OpenAPI schema dictionary with security schemes configured
    """
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    # Add security schemes to the OpenAPI schema
    openapi_schema["components"] = openapi_schema.get("components", {})
    openapi_schema["components"]["securitySchemes"] = {
        "AdminApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": "Enter the token with the `Bearer ` prefix, e.g. `Bearer abcdef12345`",
        },
        "AdminApiKeyQuery": {
            "type": "apiKey",
            "in": "query",
            "name": "api_key",
            "description": "API key for admin authentication as a query parameter",
        },
    }

    # Apply security to admin routes
    for path, operations in openapi_schema["paths"].items():
        if not path.startswith("/admin/"):
            continue
        for method, operation in operations.items():
            if method == "parameters" or not isinstance(operation, dict):
                continue
            operation["security"] = [
                {"AdminApiKeyAuth": []},
                {"AdminApiKeyQuery": []},
            ]

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add Tor detection middleware
app.add_middleware(TorDetectionMiddleware)
logger.info("Tor detection middleware registered")

# Set up Prometheus metrics
instrumentator = Instrumentator().instrument(app)
logger.info("Prometheus metrics instrumentation initialized")


# Create a dedicated metrics endpoint
@app.get("/metrics", include_in_schema=False)
async def metrics(request: Request):
    """
    Prometheus metrics endpoint (internal-only via nginx).

    This endpoint updates all feedback analytics metrics before exposing them.
    Access is restricted to internal networks (127.0.0.1, Docker networks) via nginx.
    Defense-in-depth: Also enforces IP allowlist in production to fail closed if nginx misconfigured.
    """
    # Import here to avoid circular dependency
    from app.routes.admin.analytics import (
        FEEDBACK_HELPFUL,
        FEEDBACK_HELPFUL_RATE,
        FEEDBACK_TOTAL,
        FEEDBACK_UNHELPFUL,
        ISSUE_COUNT,
        SOURCE_HELPFUL,
        SOURCE_HELPFUL_RATE,
        SOURCE_TOTAL,
    )
    from app.routes.admin.feedback import KNOWN_ISSUE_TYPES, get_feedback_analytics

    # Defense-in-depth: restrict in-app in production
    _s = get_settings()
    if str(_s.ENVIRONMENT).strip().lower() in {"production", "prod"}:
        client_ip = (request.client.host if request.client else "") or ""
        is_private = (
            client_ip.startswith(("10.", "172.", "192.168.", "127.", "::1"))
            or client_ip == "localhost"
        )
        if not is_private:
            raise HTTPException(status_code=404)

    try:
        # Get feedback analytics without authentication (internal endpoint)
        analytics = await get_feedback_analytics()

        # Update Gauge metrics with current values
        FEEDBACK_TOTAL.set(analytics["total_feedback"])
        FEEDBACK_HELPFUL.set(analytics["helpful_count"])
        FEEDBACK_UNHELPFUL.set(analytics["unhelpful_count"])
        FEEDBACK_HELPFUL_RATE.set(
            analytics["helpful_rate"] * 100
        )  # Convert to percentage

        # Update source metrics
        for source_type, stats in analytics["source_effectiveness"].items():
            SOURCE_TOTAL.labels(source_type=source_type).set(stats["total"])
            SOURCE_HELPFUL.labels(source_type=source_type).set(stats["helpful"])

            helpful_rate = (
                stats["helpful"] / stats["total"] if stats["total"] > 0 else 0
            )
            SOURCE_HELPFUL_RATE.labels(source_type=source_type).set(
                helpful_rate * 100
            )  # Convert to percentage

        # Update issue metrics with controlled vocabulary to prevent high-cardinality
        # First clear any existing metrics to ensure removed issues don't persist
        for issue_type in [*KNOWN_ISSUE_TYPES.values(), "other"]:
            ISSUE_COUNT.labels(issue_type=issue_type).set(0)

        # Now set the new values
        for issue_type, count in analytics["common_issues"].items():
            ISSUE_COUNT.labels(issue_type=issue_type).set(count)
    except Exception as e:
        # Log error but continue to expose other metrics
        logger.error(f"Failed to update feedback metrics: {e}", exc_info=True)

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# Include routers
app.include_router(health.router, tags=["Health"])
app.include_router(chat.router, prefix="/chat", tags=["Chat"])
app.include_router(feedback_routes.router, tags=["Feedback"])
include_admin_routers(app)  # Include all admin routers from the admin package
app.include_router(onion_verify.router, tags=["Onion Verification"])


@app.get("/healthcheck")
async def healthcheck():
    return {"status": "healthy"}


# Register exception handlers
# Register specific application exceptions first
app.add_exception_handler(BaseAppException, base_exception_handler)
# Then register generic exception handler as fallback
app.add_exception_handler(Exception, unhandled_exception_handler)


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    # Bind to 0.0.0.0 only in DEBUG mode (container/development)
    # Otherwise bind to 127.0.0.1 for local security
    host = "0.0.0.0" if settings.DEBUG else "127.0.0.1"

    uvicorn.run(
        "app.main:app",
        host=host,
        port=8000,
        reload=settings.DEBUG,
    )
