"""Router exports."""

from .calendar_router import router as calendar_router
from .chat_router import router as chat_router
from .day_router import router as day_router
from .evaluation_router import router as evaluation_router
from .model_router import router as model_router
from .page_router import router as page_router
from .routines_router import router as routines_router

__all__ = [
    "page_router",
    "calendar_router",
    "day_router",
    "routines_router",
    "model_router",
    "chat_router",
    "evaluation_router",
]
