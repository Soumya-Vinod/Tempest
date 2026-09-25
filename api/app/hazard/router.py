"""Re-export hazard router from routes.py for backwards compatibility."""

from app.hazard.routes import router

__all__ = ["router"]
