"""Common interface implemented by vision providers."""

from abc import ABC, abstractmethod


class VisionProviderError(RuntimeError):
    """Raised when a vision provider cannot complete a request."""


class VisionProvider(ABC):
    """Contract implemented by visual verification providers."""

    @abstractmethod
    def verify(self, image_path: str, statement: str) -> bool:
        """Return whether an image satisfies the given statement."""
        raise NotImplementedError
