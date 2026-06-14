drm-screen-service implements layers, while drm-display only writes the final rendered frame.

Minimal structure:

drm_screen_service/
  __init__.py
  service.py        # daemon / API
  compositor.py     # layer composition
  layer.py          # Layer model
  assets.py         # PNG/JPEG/raw loading
  backend.py        # adapter around drm-display

Core idea:

Layer buffers -> compositor -> final NumPy canvas -> drm-display

A first Layer model:

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
    buffer: np.ndarray | None = None  # RGBA, shape: h,w,4
    def clear(self):
        self.buffer = np.zeros((self.height, self.width, 4), dtype=np.uint8)

Compositor:

import numpy as np
class Compositor:
    def __init__(self, screen_width: int, screen_height: int):
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.layers: dict[str, Layer] = {}
    def add_layer(self, layer: Layer):
        if layer.buffer is None:
            layer.clear()
        self.layers[layer.name] = layer
    def set_visible(self, name: str, visible: bool):
        self.layers[name].visible = visible
    def render(self) -> np.ndarray:
        canvas = np.zeros(
            (self.screen_height, self.screen_width, 4),
            dtype=np.uint8,
        )
        for layer in sorted(self.layers.values(), key=lambda l: l.z):
            if not layer.visible or layer.buffer is None:
                continue
            self._blend(canvas, layer)
        return canvas
    def _blend(self, canvas: np.ndarray, layer: Layer):
        x0 = max(layer.x, 0)
        y0 = max(layer.y, 0)
        x1 = min(layer.x + layer.width, self.screen_width)
        y1 = min(layer.y + layer.height, self.screen_height)
        if x1 <= x0 or y1 <= y0:
            return
        lx0 = x0 - layer.x
        ly0 = y0 - layer.y
        lx1 = lx0 + (x1 - x0)
        ly1 = ly0 + (y1 - y0)
        src = layer.buffer[ly0:ly1, lx0:lx1].astype(np.float32)
        dst = canvas[y0:y1, x0:x1].astype(np.float32)
        alpha = (src[..., 3:4] / 255.0) * layer.opacity
        out_rgb = src[..., :3] * alpha + dst[..., :3] * (1.0 - alpha)
        out_a = src[..., 3:4] + dst[..., 3:4] * (1.0 - alpha)
        canvas[y0:y1, x0:x1, :3] = out_rgb.clip(0, 255).astype(np.uint8)
        canvas[y0:y1, x0:x1, 3:4] = out_a.clip(0, 255).astype(np.uint8)

Image placement:

from PIL import Image
import numpy as np
def load_image_rgba(path: str) -> np.ndarray:
    img = Image.open(path).convert("RGBA")
    return np.asarray(img, dtype=np.uint8)

Backend adapter:

class DrmDisplayBackend:
    def __init__(self):
        from drm_display import Screen
        self.screen = Screen()
        self.width, self.height = self.screen.get_screen_size()
    def write(self, frame: np.ndarray):
        self.screen.write(frame)

Service loop:

import time
class ScreenService:
    def __init__(self, backend, fps: int = 30):
        self.backend = backend
        self.compositor = Compositor(backend.width, backend.height)
        self.dirty = True
        self.fps = fps
    def render_once(self):
        frame = self.compositor.render()
        self.backend.write(frame)
    def run(self):
        interval = 1.0 / self.fps
        while True:
            if self.dirty:
                self.render_once()
                self.dirty = False
            time.sleep(interval)

Then your API mutates layers and marks the service dirty:

service.compositor.add_layer(
    Layer(
        name="overlay",
        width=320,
        height=80,
        x=200,
        y=50,
        z=10,
    )
)
service.compositor.layers["overlay"].buffer = load_image_rgba("x.png")
service.dirty = True

I’d make these the first commands:

create_layer(name, width, height, x, y, z)
delete_layer(name)
clear_layer(name)
show_layer(name)
hide_layer(name)
set_layer_position(name, x, y)
set_layer_z(name, z)
place_image(name, path, x=0, y=0)
place_raw_buffer(name, width, height, format, data)
render()

The important part: a layer is not a single image. A layer is its own offscreen canvas. You can draw many things into it, then show/hide the whole layer instantly.

So:

background layer: persistent
main layer: normal content
overlay layer: warnings/status
debug layer: fps/network diagnostics
modal layer: temporary dialogs

HTML can come later as:

HTML -> raster image -> layer.buffer

rather than making the compositor understand DOM directly.
