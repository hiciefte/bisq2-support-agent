"""
FastAPI application for the Bisq Support Assistant.
This module sets up the API server with routes, middleware, and error handling.
"""

import logging
import os
import sys
from contextlib import asynccontextmanager

from app.core.config import get_settings
from app.routes import admin, chat, feedback, health
from app.services.faq_service import FAQService
from app.services.feedback_service import FeedbackService
from app.services.simplified_rag_service import SimplifiedRAGService
from app.services.wiki_service import WikiService
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from prometheus_fastapi_instrumentator import Instrumentator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("app.main")

# Log environment variables (redacting sensitive ones)
logger.info("Environment variables:")
for key, value in sorted(os.environ.items()):
    if key in ["OPENAI_API_KEY", "XAI_API_KEY", "ADMIN_API_KEY"]:
        logger.info(f"  {key}=***REDACTED***")
    else:
        logger.info(f"  {key}={value}")

# Load settings
logger.info("Loading settings...")
try:
    # Use the cached settings function
    settings = get_settings()
    logger.info(f"Settings loaded successfully")
    logger.info(f"CORS_ORIGINS = {settings.CORS_ORIGINS}")
    logger.info(f"Environment: {settings.ENVIRONMENT}")
except Exception as e:
    logger.error(f"Error loading settings: {e}", exc_info=True)
    raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Application startup...")

    # Initialize services
    settings = get_settings()
    app.state.settings = settings

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

    # Yield control to the application
    yield

    # Shutdown
    logger.info("Application shutdown...")
    # Perform any cleanup here if needed
    # For example, rag_service might have a cleanup method
    if hasattr(app.state.rag_service, "cleanup"):
        await app.state.rag_service.cleanup()


# Create FastAPI application
app = FastAPI(
    title=settings.PROJECT_NAME,
    docs_url="/api/docs",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)


# Custom OpenAPI with security scheme
def custom_openapi():
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
    for path in openapi_schema["paths"]:
        if path.startswith("/admin/"):
            for method in openapi_schema["paths"][path]:
                openapi_schema["paths"][path][method]["security"] = [
                    {"AdminApiKeyAuth": []},
                    {"AdminApiKeyQuery": []},
                ]

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set up Prometheus metrics
instrumentator = Instrumentator().instrument(app)


@app.on_event("startup")
async def startup():
    # Initialize the instrumentator but don't expose it
    logger.info("Prometheus metrics instrumentation initialized")


# Create a dedicated metrics endpoint
@app.get("/metrics", include_in_schema=True)
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# Include routers
app.include_router(health.router, tags=["Health"])
app.include_router(chat.router, prefix="/chat", tags=["Chat"])
app.include_router(feedback.router, tags=["Feedback"])
app.include_router(admin.router, tags=["Admin"])
app.include_router(admin.auth_router, tags=["Admin Auth"])


@app.get("/healthcheck")
async def healthcheck():
    return {"status": "healthy"}


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred."},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=settings.DEBUG)
