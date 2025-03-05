import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.core.config import Settings
from app.routes import chat, feedback, health
from app.services.rag_service import RAGService

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
    logger.info("Initializing RAG service...")
    rag_service = RAGService(settings=settings)
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
    description="API for the Bisq Support Assistant chatbot",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware, # type: ignore
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set up Prometheus metrics - simplified approach
instrumentator = Instrumentator()

@app.on_event("startup")
async def startup():
    # Expose metrics at /metrics endpoint
    instrumentator.instrument(app).expose(app)
    logger.info("Metrics endpoint exposed at /metrics")

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
