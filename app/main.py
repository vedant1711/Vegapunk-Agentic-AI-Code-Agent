"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.tasks import router as tasks_router
from app.api.webhooks import router as webhooks_router
from app.config import settings

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    logger.info("Vegapunk starting up...")

    # Check LLM providers
    from llm.provider import llm  # noqa: F401
    if not (settings.has_nvidia or settings.has_gemini):
        logger.warning("No LLM provider configured. Set NVIDIA_API_KEY or GEMINI_API_KEY.")

    # Check GitHub
    if not settings.has_github:
        logger.warning("GITHUB_TOKEN not set - GitHub integration disabled.")

    # Check Docker
    from tools.sandbox import sandbox
    if sandbox.available:
        logger.info("Docker sandbox available.")

    if settings.app_env == "development":
        logger.info(
            "TIP: Run with: uvicorn app.main:app --reload "
            "--reload-exclude 'workspaces/*' --port 8000"
        )
    else:
        logger.warning("Docker not available - using local execution (not sandboxed).")

    # Ensure workspace directory exists
    settings.workspace_path
    logger.info(f"Workspace: {settings.workspace_dir}")

    logger.info("Vegapunk ready.")
    yield

    logger.info("Vegapunk shutting down.")


app = FastAPI(
    title="Vegapunk",
    description=(
        "Vegapunk - Autonomous Coding Agent. Resolves GitHub issues end-to-end "
        "by classifying, planning, writing code, running tests, self-reviewing, "
        "and opening a pull request."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routes
app.include_router(webhooks_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")


@app.get("/")
async def root():
    return {
        "name": "Vegapunk",
        "version": "0.1.0",
        "status": "running",
        "providers": {
            "nvidia_nim": settings.has_nvidia,
            "gemini": settings.has_gemini,
            "github": settings.has_github,
        },
    }


@app.get("/health")
async def health():
    from tools.sandbox import sandbox
    return {
        "status": "healthy",
        "llm": settings.has_nvidia or settings.has_gemini,
        "github": settings.has_github,
        "docker": sandbox.available,
    }
