"""ScreenService — the one long-running service in the stack.

Owns the only display thread, an inbound command queue, and the render loop.
`submit()` is the single non-blocking entry point: clients enqueue a command
batch and move on.  The render thread drains the queue, applies mutations, and
re-composites on the next tick only if something changed (dirty flag).
"""

import queue
import threading
import time

from .composer import Composer
from .commands import apply_command


class ScreenService:
    def __init__(self, backend, fps: int = 30):
        self.backend = backend
        self.composer = Composer(backend.width, backend.height)
        self.fps = fps
        self.queue: "queue.Queue[list]" = queue.Queue()
        self.dirty = True
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
            return self.composer.hit_test(x, y)

    # ── render thread internals ──────────────────────────────────────────────

    def _drain(self) -> None:
        while True:
            try:
                batch = self.queue.get_nowait()
            except queue.Empty:
                return
            for cmd in batch:
                apply_command(self.composer, cmd)
            self.dirty = True

    def render_once(self) -> None:
        with self._lock:
            self._drain()
            if self.dirty:
                frame = self.composer.render()
                self.backend.write(frame)
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
        self.backend.close()
