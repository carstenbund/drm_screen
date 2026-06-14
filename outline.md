# drm_screen — outline

`drm_screen` is the **stateful screen manager**. It owns persistent layer
buffers, composites them into a single frame, and pushes that frame to
`drm_display`.

It does **not** parse HTML, resolve layout, or rasterize text/shapes — that is
`drm_composer`'s job. It does **not** talk to DRM/KMS — that is `drm-display`'s
job.

## Place in the stack

```
Application
   ↓
drm_composer     scene markup → commands + RGBA bitmaps   (stateless compiler)
   ↓
drm_screen       layers → composited frame                (stateful, this repo)
   ↓
drm-display      RGBA/BGRA frame → DRM/KMS pixels          (hardware)
```

## Responsibilities

`drm_screen` owns:

1. **Layer state** — a named set of persistent offscreen RGBA buffers, each
   with position, z-order, visibility, and opacity.
2. **Composition** — z-ordered alpha blending of visible layers into one canvas.
3. **Output** — handing the composited frame to `drm-display`.
4. **A command API** — the verbs the composer (or any client) calls to mutate
   layer state.
5. **A render loop** — a dirty-flagged service that re-composites and pushes
   only when something changed.

A layer is **not** a single image — it is its own offscreen canvas. Many things
can be drawn into one layer, then the whole layer is shown/hidden/moved as a
unit. Typical layers:

- `background` — persistent
- `main` — normal content
- `overlay` — warnings / status
- `debug` — fps / network diagnostics
- `modal` — temporary dialogs

## Color convention

All layer buffers are **RGBA** `uint8`, shape `(h, w, 4)`. This matches PIL /
imageio / what `drm_composer` produces, so no conversion happens anywhere inside
`drm_screen` or above it.

The **single** RGBA→BGRA conversion happens in the backend adapter, immediately
before calling `drm-display`'s `Screen.show()` (drm-display's canonical buffer is
BGRA / XRGB8888 little-endian). Nothing else in the stack converts channels.

## Package layout

```
drm_screen/
  __init__.py
  layer.py          # Layer model
  composer.py       # Composer — z-ordered alpha blend of layers → RGBA canvas
  assets.py         # PNG/JPEG/raw → RGBA loading
  backend.py        # adapter around drm-display (RGBA→BGRA conversion lives here)
  service.py        # ScreenService — command API + dirty-flag render loop
  server.py         # optional network/IPC front-end onto the command API
```

Data flow:

```
layer buffers (RGBA) → Composer.render() → RGBA canvas → backend (→BGRA) → drm-display
```

## Layer model

```python
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
    buffer: np.ndarray | None = None   # RGBA, shape (h, w, 4)

    def clear(self):
        self.buffer = np.zeros((self.height, self.width, 4), dtype=np.uint8)
```

## Composer

The compositor lives **here**, in `drm_screen` — not in `drm_composer`.
(`drm_composer` only compiles scenes to commands; it never blends a final frame.)

```python
import numpy as np

class Composer:
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
```

## Asset loading

```python
from PIL import Image
import numpy as np

def load_image_rgba(path: str) -> np.ndarray:
    img = Image.open(path).convert("RGBA")
    return np.asarray(img, dtype=np.uint8)   # RGBA — no BGRA here
```

## Backend adapter — the only channel-order boundary

```python
class DrmDisplayBackend:
    def __init__(self):
        from drm_display import Screen
        self.screen = Screen()
        self.width, self.height = self.screen.get_screen_size()

    def write(self, frame_rgba: np.ndarray):
        # RGBA → BGRA, the one and only conversion in the whole stack
        bgra = frame_rgba[:, :, [2, 1, 0, 3]]
        self.screen.show(bgra)             # drm-display expects BGRA
```

Note: `drm-display`'s public method is `Screen.show()`, not `write()`.

## Service — the primary shape

`drm_screen` is a **service from the start**: a long-running process that owns
the only display thread, a command queue, and the render loop. It is the single
async boundary in the stack — clients `submit()` and move on; the service does
everything after that on its own thread.

Clients never touch layer state directly. They enqueue **command batches** via
`submit()`, which appends and returns immediately. The render thread drains the
queue, applies the mutations, and re-composites on the next tick if anything
changed.

```python
import time, queue

class ScreenService:
    def __init__(self, backend, fps: int = 30):
        self.backend = backend
        self.composer = Composer(backend.width, backend.height)
        self.fps = fps
        self.queue = queue.Queue()      # inbound command batches
        self.dirty = True

    # ── client-facing, non-blocking ──────────────────────────────
    def submit(self, commands):
        """Enqueue a batch of mutations. Returns immediately."""
        self.queue.put(commands)

    # ── render thread, owns all layer state ──────────────────────
    def _drain(self):
        while True:
            try:
                batch = self.queue.get_nowait()
            except queue.Empty:
                return
            for cmd in batch:
                cmd.apply(self.composer)    # create_layer / place_raw_buffer / …
                self.dirty = True

    def render_once(self):
        frame = self.composer.render()
        self.backend.write(frame)

    def run(self):
        interval = 1.0 / self.fps
        while True:
            self._drain()
            if self.dirty:
                self.render_once()
                self.dirty = False
            time.sleep(interval)
```

### How it is launched

- **Production / default — standalone daemon.** `drm_screen` runs as its own
  process. `server.py` puts a network/IPC front (e.g. `POST /scene`, or a unix
  socket) onto `submit()`. The render loop runs on a dedicated thread. Clients
  (and `drm_composer`) reach it over the socket. The socket *is* the async
  boundary.

- **Debug only — launched together.** For development, the app, composer, and
  service can run in one process: the service thread is started in-process and
  `submit()` is called directly (no socket). Same `submit()` API, same render
  loop — only the transport differs. This is a convenience for debugging, not a
  deployment mode.

The `submit()` contract is identical in both: enqueue and return. Nothing
upstream blocks on compositing or the DRM push.

## Command API

The stable verb set carried inside a `submit()` batch. Clients build a batch of
these; the render thread applies them in order and flips the dirty flag.

```
create_layer(name, width, height, x, y, z)
delete_layer(name)
clear_layer(name)
show_layer(name)
hide_layer(name)
set_layer_position(name, x, y)
set_layer_z(name, z)
place_image(name, path, x=0, y=0)            # loads to RGBA, blits into layer
place_raw_buffer(name, width, height, data)  # RGBA bytes, blits into layer
```

These are **data**, not direct calls — a command is a serializable record so the
same batch survives the socket hop to the daemon. `submit(batch)` is the single
non-blocking entry point. There is no client-facing `render()`: re-compositing
is the render loop's job, triggered automatically by the dirty flag.

This command surface + `submit()` is the **contract** between `drm_screen` and
`drm_composer`. Keep it stable.
