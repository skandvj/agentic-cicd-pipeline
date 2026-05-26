"""Vercel entrypoint for the Agentic CI/CD FastAPI runtime."""

from src.runtime.server import app

__all__ = ["app"]
