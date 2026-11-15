from ..config import Settings
from .base import BrowserBackend


def get_backend(settings: Settings) -> BrowserBackend:
    """Pick the backend from BROWSER_BACKEND. Imports are lazy so the mock
    backend never needs TinyFish/Playwright installed."""
    name = settings.browser_backend
    if name == "mock":
        from .mock import MockBackend

        return MockBackend()
    if name == "tinyfish":
        from .tinyfish import TinyFishBackend

        return TinyFishBackend(settings)
    raise ValueError(f"Unknown BROWSER_BACKEND: {name!r}")


__all__ = ["BrowserBackend", "get_backend"]
