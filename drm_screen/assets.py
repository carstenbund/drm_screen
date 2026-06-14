"""Asset loading — files/raw bytes -> RGBA uint8 arrays.

Always returns RGBA (no BGRA here).  Kept tiny and optional: the core service
never imports this unless asked to load a file.
"""

import numpy as np


def load_image_rgba(path: str) -> np.ndarray:
    from PIL import Image  # lazy: only when actually loading a file
    img = Image.open(path).convert("RGBA")
    return np.asarray(img, dtype=np.uint8)


def solid_rgba(width: int, height: int, rgba) -> np.ndarray:
    """A flat RGBA fill — handy for boxes/backgrounds and tests."""
    buf = np.empty((height, width, 4), dtype=np.uint8)
    buf[:] = np.asarray(rgba, dtype=np.uint8)
    return buf
