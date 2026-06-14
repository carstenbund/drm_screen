"""Layer model — a named, persistent, offscreen RGBA canvas.

A layer is not a single image: many things can be drawn into one layer, then the
whole layer is shown/hidden/moved as a unit.  All buffers are RGBA uint8,
shape (h, w, 4).  The single RGBA->BGRA conversion happens downstream in the
backend adapter, never here.
"""

from dataclasses import dataclass
import numpy as np


@dataclass
class Layer:
    name: str
    width: int
    height: int
    x: int = 0
    y: int = 0
    z: int = 0
    visible: bool = True
    opacity: float = 1.0
    buffer: np.ndarray | None = None  # RGBA, shape (height, width, 4)

    def clear(self):
        """Reset the layer to fully transparent."""
        self.buffer = np.zeros((self.height, self.width, 4), dtype=np.uint8)

    def blit(self, rgba: np.ndarray, x: int = 0, y: int = 0):
        """Copy an RGBA bitmap into this layer at (x, y), clipped to bounds."""
        if self.buffer is None:
            self.clear()
        h, w = rgba.shape[:2]
        x0, y0 = max(x, 0), max(y, 0)
        x1, y1 = min(x + w, self.width), min(y + h, self.height)
        if x1 <= x0 or y1 <= y0:
            return
        sx0, sy0 = x0 - x, y0 - y
        self.buffer[y0:y1, x0:x1] = rgba[sy0:sy0 + (y1 - y0), sx0:sx0 + (x1 - x0)]
