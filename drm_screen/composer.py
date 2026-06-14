"""Composer — z-ordered alpha composition of layers into one RGBA canvas.

This is the ONE place pixels are blended, and `render()` is a single pure
function `layers -> canvas` with no side effects.  That isolation is deliberate:
if profiling ever shows the blend is the bottleneck, this is the only function
that moves to a native (Rust/PyO3) implementation — nothing else changes.
"""

import numpy as np

from .layer import Layer


class Composer:
    def __init__(self, screen_width: int, screen_height: int):
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.layers: dict[str, Layer] = {}

    # ── layer management ──────────────────────────────────────────────────────

    def add_layer(self, layer: Layer):
        if layer.buffer is None:
            layer.clear()
        self.layers[layer.name] = layer

    def remove_layer(self, name: str):
        self.layers.pop(name, None)

    def get(self, name: str) -> Layer:
        return self.layers[name]

    # ── composition (pure: layers -> canvas) ──────────────────────────────────

    def render(self) -> np.ndarray:
        canvas = np.zeros(
            (self.screen_height, self.screen_width, 4), dtype=np.uint8
        )
        for layer in sorted(self.layers.values(), key=lambda l: l.z):
            if not layer.visible or layer.buffer is None:
                continue
            self._blend(canvas, layer)
        return canvas

    @staticmethod
    def _blend(canvas: np.ndarray, layer: Layer):
        sw, sh = canvas.shape[1], canvas.shape[0]
        x0, y0 = max(layer.x, 0), max(layer.y, 0)
        x1 = min(layer.x + layer.width, sw)
        y1 = min(layer.y + layer.height, sh)
        if x1 <= x0 or y1 <= y0:
            return
        lx0, ly0 = x0 - layer.x, y0 - layer.y
        lx1, ly1 = lx0 + (x1 - x0), ly0 + (y1 - y0)

        src = layer.buffer[ly0:ly1, lx0:lx1].astype(np.float32)
        dst = canvas[y0:y1, x0:x1].astype(np.float32)
        alpha = (src[..., 3:4] / 255.0) * layer.opacity
        out_rgb = src[..., :3] * alpha + dst[..., :3] * (1.0 - alpha)
        out_a = src[..., 3:4] + dst[..., 3:4] * (1.0 - alpha)
        canvas[y0:y1, x0:x1, :3] = out_rgb.clip(0, 255).astype(np.uint8)
        canvas[y0:y1, x0:x1, 3:4] = out_a.clip(0, 255).astype(np.uint8)
