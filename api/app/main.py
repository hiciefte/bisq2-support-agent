"""
FastAPI application for the Bisq Support Assistant.
This module sets up the API server with routes, middleware, and error handling.
"""

import importlib
import ipaddress
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, Dict

from app.channels.bootstrapper import ChannelBootstrapper
from app.channels.lifecycle import create_channel_gateway
from app.channels.models import ChannelCapability
from app.channels.services.live_polling_service import LivePollingService
from app.core.config import Settings, get_settings
from app.core.error_handlers import base_exception_handler, unhandled_exception_handler
from app.core.exceptions import BaseAppException
from app.db.run_migrations import run_migrations
from app.metrics.tor_metrics import (
    update_cookie_security_mode,
    update_tor_service_configured,
)
from app.middleware import TorDetectionMiddleware
from app.middleware.cache_control import CacheControlMiddleware
from app.routes import (
    alertmanager,
    chat,
    escalation_polling,
    feedback_routes,
    health,
    metrics_update,
    onion_verify,
    public_faqs,
)
from app.routes.admin import include_admin_routers
from app.services.bisq_mcp_service import Bisq2MCPService
from app.services.channel_autoresponse_policy_service import (
    ChannelAutoResponsePolicyService,
)
from app.services.faq_service import FAQService
from app.services.feedback_service import FeedbackService
from app.services.mcp.mcp_http_server import router as mcp_router
from app.services.mcp.mcp_http_server import set_bisq_service
from app.services.public_faq_service import PublicFAQService
from app.services.rag.embeddings_provider import LiteLLMEmbeddings
from app.services.rag.learning_engine import LearningEngine
from app.services.simplified_rag_service import SimplifiedRAGService
from app.services.tor_monitoring_service import TorMonitoringService
from app.services.training.comparison_engine import AnswerComparisonEngine
from app.services.training.unified_pipeline_service import UnifiedPipelineService
from app.services.training.unified_repository import UnifiedFAQCandidateRepository
from app.services.wiki_service import WikiService
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_fastapi_instrumentator import metrics as instrumentator_metrics

try:
    import aisuite  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover - exercised in minimal test envs

    class _AisuiteFallback:
        class Client:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

    aisuite = _AisuiteFallback()  # type: ignore[assignment]

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("app.main")

DEFAULT_CHANNEL_PLUGIN_MODULES = [
    "app.channels.plugins.web.channel",
    "app.channels.plugins.matrix.channel",
    "app.channels.plugins.bisq2.channel",
]

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
    app.state.bisq2_live_chat_service = None
    app.state.matrix_channel = None
    app.state.channel_autoresponse_policy_service = None

    # Initialize task metrics persistence and restore values
    logger.info("Initializing task metrics persistence...")
    from app.metrics.task_metrics import restore_metrics_from_database
    from app.utils.task_metrics_persistence import init_persistence

    init_persistence(settings)
    restore_metrics_from_database()
    logger.info("Task metrics persistence initialized and restored")

    logger.info("Initializing WikiService...")
    wiki_service = WikiService(settings=settings)

    logger.info("Initializing FeedbackService...")
    feedback_service = FeedbackService(settings=settings)

    plugin_modules = getattr(
        settings, "CHANNEL_PLUGINS", DEFAULT_CHANNEL_PLUGIN_MODULES
    )
    for module_path in plugin_modules:
        try:
            importlib.import_module(module_path)
        except Exception:
            logger.debug(
                "Skipping channel plugin import '%s'", module_path, exc_info=True
            )

    app.state.channel_autoresponse_policy_service = ChannelAutoResponsePolicyService(
        db_path=os.path.join(settings.DATA_DIR, "feedback.db"),
    )

    logger.info("Initializing FAQService...")
    faq_service = FAQService(settings=settings)

    logger.info("Initializing PublicFAQService...")
    public_faq_service = PublicFAQService(faq_service=faq_service)

    # Initialize Bisq2MCPService for live data integration
    logger.info("Initializing Bisq2MCPService...")
    bisq_mcp_service = Bisq2MCPService(settings=settings)
    app.state.bisq_mcp_service = bisq_mcp_service
    # Set the service for MCP HTTP endpoint
    set_bisq_service(bisq_mcp_service)
    logger.info(
        f"Bisq2MCPService initialized (enabled={settings.ENABLE_BISQ_MCP_INTEGRATION})"
    )

    logger.info("Initializing SimplifiedRAGService...")
    rag_service = SimplifiedRAGService(
        settings=settings,
        feedback_service=feedback_service,
        wiki_service=wiki_service,
        faq_service=faq_service,
        bisq_mcp_service=bisq_mcp_service,
    )

    # Set up the RAG service (loads data, builds vector store)
    await rag_service.setup()

    # Eager load ColBERT reranker if enabled and using Qdrant backend
    if settings.RETRIEVER_BACKEND == "qdrant" and settings.ENABLE_COLBERT_RERANK:
        logger.info("Eager loading ColBERT reranker model...")
        try:
            if rag_service.colbert_reranker:
                rag_service.colbert_reranker.load_model()
                logger.info("ColBERT reranker model loaded successfully")
            else:
                logger.warning("ColBERT reranker not initialized, skipping eager load")
        except Exception as e:
            logger.warning(f"ColBERT eager loading failed (will load lazily): {e}")

    # Assign services to app state
    app.state.feedback_service = feedback_service
    app.state.faq_service = faq_service
    app.state.public_faq_service = public_faq_service
    app.state.rag_service = rag_service
    app.state.wiki_service = wiki_service

    # Create LearningEngine early so it can be wired to EscalationService
    # State will be loaded later when unified_db_path is available
    learning_engine = LearningEngine()
    app.state.learning_engine = learning_engine

    # Embeddings are a startup requirement because AnswerComparisonEngine depends on them.
    embeddings_model = LiteLLMEmbeddings.from_settings(settings)

    # Initialize EscalationService singleton for admin routes, polling, and hooks.
    app.state.escalation_service = None
    app.state.escalation_init_failed = False
    try:
        from app.services.escalation.escalation_repository import EscalationRepository
        from app.services.escalation.escalation_service import EscalationService
        from app.services.escalation.feedback_orchestrator import FeedbackOrchestrator

        esc_db_path = os.path.join(settings.DATA_DIR, "escalations.db")
        esc_repo = EscalationRepository(db_path=esc_db_path)
        await esc_repo.initialize()
        feedback_orchestrator = FeedbackOrchestrator(
            learning_engine=learning_engine,
            weight_manager=feedback_service.weight_manager,
            settings=settings,
        )
        app.state.feedback_orchestrator = feedback_orchestrator

        escalation_service = EscalationService(
            repository=esc_repo,
            response_delivery=None,  # Wired after channel adapters are initialized.
            faq_service=faq_service,  # Required for /generate-faq
            learning_engine=learning_engine,
            settings=settings,
            feedback_orchestrator=feedback_orchestrator,
            embeddings=embeddings_model,
            rag_service=rag_service,
        )
        app.state.escalation_service = escalation_service
        logger.info("EscalationService initialized (singleton)")
    except Exception:
        app.state.escalation_service = None
        app.state.feedback_orchestrator = None
        app.state.escalation_init_failed = True
        logger.critical("EscalationService init failed", exc_info=True)

    # Initialize Channel Gateway with default middleware hooks
    logger.info("Initializing Channel Gateway...")
    channel_gateway = create_channel_gateway(
        rag_service=rag_service,
        register_default_hooks=True,
    )
    from app.channels.hooks.channel_autoresponse_hook import (
        ChannelAIGenerationPolicyHook,
        ChannelAutoResponsePolicyHook,
    )

    channel_gateway.register_pre_hook(
        ChannelAIGenerationPolicyHook(
            policy_service=getattr(
                app.state,
                "channel_autoresponse_policy_service",
                None,
            )
        )
    )
    logger.info("Registered ChannelAIGenerationPolicyHook")

    channel_gateway.register_post_hook(
        ChannelAutoResponsePolicyHook(
            policy_service=getattr(
                app.state,
                "channel_autoresponse_policy_service",
                None,
            )
        )
    )
    logger.info("Registered ChannelAutoResponsePolicyHook")

    # Register EscalationPostHook (only affects chat flow; admin/polling still work without it).
    if getattr(settings, "ESCALATION_ENABLED", False):
        service = getattr(app.state, "escalation_service", None)
        if service is None:
            logger.warning("ESCALATION_ENABLED but escalation_service is not available")
        else:
            from app.channels.hooks.escalation_hook import EscalationPostHook

            channel_gateway.register_post_hook(
                EscalationPostHook(
                    escalation_service=service,
                    channel_registry=None,
                    settings=settings,
                )
            )
            logger.info("Registered EscalationPostHook")
    app.state.channel_gateway = channel_gateway
    logger.info(
        f"Channel Gateway initialized with hooks: {channel_gateway.get_hook_info()}"
    )

    # Bootstrap all enabled channels via plugin architecture.
    bootstrapper = ChannelBootstrapper(
        settings=settings,
        rag_service=rag_service,
        shared_services={
            "feedback_service": feedback_service,
            "channel_autoresponse_policy_service": app.state.channel_autoresponse_policy_service,
            "escalation_service": getattr(app.state, "escalation_service", None),
        },
    )
    bootstrap_result = bootstrapper.bootstrap()
    app.state.channel_runtime = bootstrap_result.runtime
    app.state.channel_registry = bootstrap_result.registry
    for hook in getattr(channel_gateway, "_post_hooks", []):
        if hasattr(hook, "channel_registry"):
            hook.channel_registry = bootstrap_result.registry
    if bootstrap_result.errors:
        for channel_id, error in bootstrap_result.errors:
            logger.exception("Failed to bootstrap channel '%s': %s", channel_id, error)

    start_errors = await bootstrap_result.registry.start_all(continue_on_error=True)
    if start_errors:
        for error in start_errors:
            logger.error("Channel startup error: %s", error)

    # Mirror shared reaction services onto app.state for web route handlers.
    app.state.sent_message_tracker = bootstrap_result.runtime.resolve_optional(
        "sent_message_tracker"
    )
    app.state.reaction_processor = bootstrap_result.runtime.resolve_optional(
        "reaction_processor"
    )
    app.state.feedback_followup_coordinator = bootstrap_result.runtime.resolve_optional(
        "feedback_followup_coordinator"
    )

    # Wire escalation response delivery directly to active channel registry.
    escalation_service = getattr(app.state, "escalation_service", None)
    if escalation_service is not None:
        try:
            from app.services.escalation.response_delivery import ResponseDelivery

            escalation_service.response_delivery = ResponseDelivery(
                bootstrap_result.registry
            )
            app.state.escalation_delivery_registry = bootstrap_result.registry
            logger.info(
                "Escalation response delivery wired for channels: %s",
                bootstrap_result.registry.list_channel_ids(),
            )
        except Exception:
            logger.exception("Failed to initialize escalation response delivery")

    # Start generic polling loops for channels that require polling ingestion.
    app.state.channel_polling_services = {}
    for channel_id in bootstrap_result.registry.list_channel_ids():
        channel = bootstrap_result.registry.get(channel_id)
        if channel is None:
            continue
        if ChannelCapability.POLL_CONVERSATIONS not in channel.capabilities:
            continue
        polling_service = LivePollingService(
            channel=channel,
            autoresponse_policy_service=app.state.channel_autoresponse_policy_service,
            escalation_service=getattr(app.state, "escalation_service", None),
            channel_id=channel_id,
        )
        await polling_service.start()
        app.state.channel_polling_services[channel_id] = polling_service

    # Backward-compatible app.state aliases consumed by existing routes/tests.
    app.state.bisq2_live_chat_service = app.state.channel_polling_services.get("bisq2")
    app.state.matrix_channel = bootstrap_result.registry.get("matrix")

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

    # Initialize AnswerComparisonEngine for real LLM-based answer comparison
    logger.info("Initializing AnswerComparisonEngine...")
    ai_client = aisuite.Client()
    comparison_engine = AnswerComparisonEngine(
        ai_client=ai_client,
        embeddings_model=embeddings_model,
        judge_model="openai:gpt-4o-mini",
    )
    logger.info("AnswerComparisonEngine initialized")

    # Initialize Unified Pipeline Service for unified FAQ training
    logger.info("Initializing UnifiedPipelineService...")
    unified_db_path = os.path.join(settings.DATA_DIR, "unified_training.db")
    unified_pipeline_service = UnifiedPipelineService(
        settings=settings,
        rag_service=rag_service,
        faq_service=faq_service,
        db_path=unified_db_path,
        comparison_engine=comparison_engine,
        aisuite_client=ai_client,
    )
    app.state.unified_pipeline_service = unified_pipeline_service
    logger.info("UnifiedPipelineService initialized")

    # Initialize Matrix alert service for Alertmanager notifications
    logger.info("Initializing MatrixAlertService...")
    from app.channels.plugins.matrix.services.alert_service import MatrixAlertService

    matrix_alert_service = MatrixAlertService(settings)
    app.state.matrix_alert_service = matrix_alert_service
    if matrix_alert_service.is_configured():
        logger.info(
            f"MatrixAlertService initialized, alerts will be sent to {settings.MATRIX_ALERT_ROOM}"
        )
    else:
        logger.info("MatrixAlertService not configured (MATRIX_ALERT_ROOM not set)")

    # Load LearningEngine persisted state from unified training database
    logger.info("Loading LearningEngine state...")
    unified_repo = UnifiedFAQCandidateRepository(unified_db_path)
    learning_engine.load_state(unified_repo)
    logger.info(
        f"LearningEngine state loaded with thresholds: {learning_engine.get_current_thresholds()}"
    )

    # Wire AutoSendRouter with LearningEngine for dynamic thresholds
    from app.services.rag.auto_send_router import AutoSendRouter

    auto_send_router = AutoSendRouter(learning_engine=learning_engine)
    app.state.auto_send_router = auto_send_router

    # Inject the wired router into RAG service so query routing uses learned thresholds
    rag_service.auto_send_router = auto_send_router

    # Yield control to the application
    yield

    # Shutdown
    logger.info("Application shutdown...")

    # Save LearningEngine state before shutdown (P5: wrapped in try-catch)
    if hasattr(app.state, "learning_engine") and app.state.learning_engine:
        try:
            logger.info("Saving LearningEngine state...")
            unified_db_path = os.path.join(settings.DATA_DIR, "unified_training.db")
            unified_repo = UnifiedFAQCandidateRepository(unified_db_path)
            if app.state.learning_engine.save_state(unified_repo):
                logger.info("LearningEngine state saved successfully")
            else:
                logger.warning("LearningEngine state save returned False")
        except Exception as e:
            # P5: Log error but don't crash shutdown
            logger.error(f"Failed to save LearningEngine state during shutdown: {e}")

    # Stop Tor monitoring service
    if hasattr(app.state, "tor_monitoring_service"):
        await app.state.tor_monitoring_service.stop()

    # Stop channel polling services.
    polling_services = getattr(app.state, "channel_polling_services", {}) or {}
    for channel_id, polling_service in list(polling_services.items()):
        try:
            logger.info("Stopping polling service for channel '%s'...", channel_id)
            await polling_service.stop()
        except Exception:
            logger.exception(
                "Failed to stop polling service for channel '%s'",
                channel_id,
            )

    # Stop all started channels via registry.
    channel_registry = getattr(app.state, "channel_registry", None)
    if channel_registry is not None:
        stop_errors = await channel_registry.stop_all()
        for error in stop_errors:
            logger.error("Channel shutdown error: %s", error)

    # Close Matrix alert service
    if hasattr(app.state, "matrix_alert_service") and app.state.matrix_alert_service:
        logger.info("Closing Matrix alert service...")
        await app.state.matrix_alert_service.close()

    # Clean up Bisq MCP service
    if hasattr(app.state, "bisq_mcp_service") and app.state.bisq_mcp_service:
        logger.info("Closing Bisq MCP service...")
        await app.state.bisq_mcp_service.close()

    # Perform any cleanup here if needed
    # For example, rag_service might have a cleanup method
    if hasattr(app.state.rag_service, "cleanup"):
        await app.state.rag_service.cleanup()


# Create FastAPI application
app = FastAPI(
    title=get_settings().PROJECT_NAME,
    docs_url="/api/docs",
    openapi_url=f"{get_settings().API_V1_STR}/openapi.json",
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


app.openapi = custom_openapi  # type: ignore[method-assign]

# Configure CORS
# Toggle credentials off when wildcard is used (Starlette forbids wildcard + credentials)
_origins = get_settings().CORS_ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False if _origins == ["*"] else True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add Tor detection middleware
app.add_middleware(TorDetectionMiddleware)
logger.info("Tor detection middleware registered")

# Add cache control middleware to prevent API response caching
app.add_middleware(CacheControlMiddleware)
logger.info("Cache control middleware registered")

# Set up Prometheus metrics
# Configure Instrumentator to use default REGISTRY and add standard metrics
# DON'T call .expose() - we handle /metrics endpoint ourselves to include task metrics
instrumentator = Instrumentator(
    should_group_status_codes=False,
    should_ignore_untemplated=True,
    should_respect_env_var=False,  # Always enable metrics
    should_instrument_requests_inprogress=True,
    excluded_handlers=["/health", "/healthcheck"],  # Don't instrument health checks
    inprogress_name="http_requests_inprogress",
    inprogress_labels=True,
)

# Add standard metrics to default REGISTRY
instrumentator.add(instrumentator_metrics.default())
instrumentator.add(
    instrumentator_metrics.latency(
        buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60)  # Custom latency buckets
    )
)

# Instrument app but DON'T expose /metrics (we have custom endpoint below)
instrumentator.instrument(app)
logger.info("Prometheus metrics instrumentation initialized")


# Create a dedicated metrics endpoint
@app.get("/metrics", include_in_schema=False)
async def metrics(request: Request, settings: Settings = Depends(get_settings)):
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
    _s = settings
    if str(_s.ENVIRONMENT).strip().lower() in {"production", "prod"}:
        client_host = (request.client.host if request.client else "") or ""

        # Parse client IP address (strip IPv6 brackets and port)
        # Treat "localhost" as private
        is_private = False
        if client_host == "localhost":
            is_private = True
        else:
            # Strip IPv6 brackets, split only on last colon to preserve IPv6 addresses
            # e.g., "[2001:db8::1]:8000" → "2001:db8::1", "127.0.0.1:8000" → "127.0.0.1"
            parsed_host = client_host.strip("[]").rsplit(":", 1)[0]
            try:
                ip = ipaddress.ip_address(parsed_host)
                is_private = ip.is_private or ip.is_loopback or ip.is_link_local
            except ValueError:
                # Unparsable address - deny (fail closed)
                is_private = False

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
app.include_router(metrics_update.router, tags=["Metrics"])
app.include_router(
    public_faqs.router, tags=["Public FAQs"]
)  # Public FAQ endpoints (no auth required)
app.include_router(
    escalation_polling.router, tags=["Escalations"]
)  # User polling endpoint (no auth required)
include_admin_routers(app)  # Include all admin routers from the admin package
app.include_router(onion_verify.router, tags=["Onion Verification"])
app.include_router(
    mcp_router, tags=["MCP"]
)  # MCP HTTP endpoint for AISuite integration
app.include_router(
    alertmanager.router, prefix="/alertmanager", tags=["Alertmanager"]
)  # Alertmanager webhook for Matrix notifications


@app.get("/healthcheck")
async def healthcheck():
    return {"status": "healthy"}


# Register exception handlers
# Register specific application exceptions first
app.add_exception_handler(BaseAppException, base_exception_handler)  # type: ignore[arg-type]
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
