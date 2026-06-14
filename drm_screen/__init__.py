"""drm_screen — stateful screen manager.

Owns persistent layers, composites them, and pushes the frame to drm-display.
RGBA throughout; the single RGBA->BGRA conversion lives in the backend adapter.
"""

from .layer import Layer
from .composer import Composer
from .backend import DrmDisplayBackend
from .service import ScreenService
from .target import InProcessTarget, SocketTarget
from . import commands

from importlib.metadata import version, PackageNotFoundError
try:
    __version__ = version("drm-screen")
except PackageNotFoundError:
    __version__ = "unknown"

__all__ = [
    "Layer",
    "Composer",
    "DrmDisplayBackend",
    "ScreenService",
    "InProcessTarget",
    "SocketTarget",
    "commands",
    "__version__",
]
