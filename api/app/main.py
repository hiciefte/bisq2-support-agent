import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from prometheus_fastapi_instrumentator import Instrumentator

from app.core.config import Settings
from app.routes import chat, feedback, health
from app.services.simplified_rag_service import SimplifiedRAGService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load configuration
settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize services on startup
    logger.info("Initializing Simplified RAG service...")
    rag_service = SimplifiedRAGService(settings=settings)
    await rag_service.setup()

    # FastAPI's app.state is dynamically typed
    app.state.rag_service = rag_service  # type: ignore

    yield

    # Cleanup on shutdown
    logger.info("Shutting down services...")
    await rag_service.cleanup()


# Create FastAPI application
app = FastAPI(
    title="Bisq Support Assistant API",
    description="API for the Bisq Support Assistant chatbot using simplified RAG implementation",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,  # type: ignore
    allow_origins=["*"],  # Allow all origins
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
app.include_router(feedback.router, prefix="/feedback", tags=["Feedback"])

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
