from ..config import Settings
from .base import WorkspaceBackend


def get_backend(settings: Settings) -> WorkspaceBackend:
    """Pick the backend from WORKSPACE_BACKEND. Imports are lazy so mock mode never needs
    Google libraries or a login."""
    name = settings.workspace_backend
    if name == "mock":
        from .mock import MockBackend

        return MockBackend(settings.timezone)
    if name == "google":
        from .google import GoogleBackend

        return GoogleBackend(settings)
    raise ValueError(f"Unknown WORKSPACE_BACKEND: {name!r}")


__all__ = ["WorkspaceBackend", "get_backend"]
