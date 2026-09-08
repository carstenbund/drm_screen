"""ScreenService — the one long-running service in the stack.

Owns the only display thread, an inbound command queue, and the render loop.
`submit()` is the single non-blocking entry point: clients enqueue a command
batch and move on.  The render thread drains the queue, applies mutations, and
re-composites on the next tick only if something changed (dirty flag).

What draws is now a choice rather than a fact.  `renderer=` selects it, and the
default keeps every existing call site on the path it has always used: pass a
backend and you get the numpy compositor, exactly as before.  A plugin (LVGL,
where the platform has it) is opted into by name, by omitting the backend, or by
`DRM_SCREEN_RENDERER` in the environment — see `drm_screen.renderers`.
"""

import queue
import threading
import time

from .renderers import get_renderer


class ScreenService:
    def __init__(self, backend=None, fps: int = 30, renderer="auto", clock=None,
                 renderer_options: dict | None = None):
        self.renderer = get_renderer(renderer, backend=backend, **(renderer_options or {}))
        # Kept because they are part of the vocabulary: `service.composer` is
        # how callers reach layer state, and on the RGBA path it is still the
        # same Composer holding the same numpy buffers.
        self.composer = getattr(self.renderer, "composer", self.renderer)
        self.backend = getattr(self.renderer, "backend", backend)
        self.fps = fps
        self.queue: "queue.Queue[list]" = queue.Queue()
        self.dirty = True
        self._clock = clock
        self._started_at = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()   # guards layer state (render vs hit_test)

    # ── client-facing, non-blocking ──────────────────────────────────────────

    def submit(self, commands) -> None:
        """Enqueue a batch of command records. Returns immediately."""
        self.queue.put(list(commands))

    def hit_test(self, x: int, y: int) -> str | None:
        """Thread-safe topmost-interactive-layer query (called from app thread)."""
        with self._lock:
            return self.renderer.hit_test(x, y)

    # ── render thread internals ──────────────────────────────────────────────

    def _drain(self) -> None:
        while True:
            try:
                batch = self.queue.get_nowait()
            except queue.Empty:
                return
            for cmd in batch:
                self.renderer.apply(cmd)
            self.dirty = True

    def scene_time_ms(self) -> float:
        """What time the picture is at.  A renderer that draws scenes evaluates
        them against this; pass `clock=` to hand it a shared one."""
        if self._clock is not None:
            return float(self._clock())
        return (time.monotonic() - self._started_at) * 1000.0

    def render_once(self, scene_time_ms: float | None = None) -> None:
        with self._lock:
            self._drain()
            # A renderer holding a scene is never finished: the picture is a
            # function of time, so "nothing was submitted" does not mean
            # "nothing changed".
            animating = getattr(self.renderer, "animating", False)
            if not (self.dirty or animating):
                return
            self.renderer.present(
                self.scene_time_ms() if scene_time_ms is None else scene_time_ms
            )
            self.dirty = False

    def _run(self) -> None:
        interval = 1.0 / self.fps
        while not self._stop.is_set():
            self.render_once()
            time.sleep(interval)

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the render loop on its own thread (production / debug daemon)."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self.renderer.close()
