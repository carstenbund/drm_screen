"""Backend adapter around drm-display — the ONLY channel-order boundary.

Everything above this point is RGBA.  drm-display's canonical buffer is BGRA
(XRGB8888 little-endian), so the single RGBA->BGRA conversion in the whole stack
lives in `write()`, right before `Screen.show()`.
"""

import numpy as np


class DrmDisplayBackend:
    def __init__(self, device=None, width=None, height=None):
        from drm_display import Screen
        # device=None -> auto-detect (card0 -> card1 -> fb0 -> dummy)
        # device="dummy" -> force the headless backend (safe for dev/tests)
        self.screen = Screen(device=device, width=width, height=height)
        self.width, self.height = self.screen.get_screen_size()

    def write(self, frame_rgba: np.ndarray):
        # RGBA -> BGRA: the one and only conversion in the stack.
        bgra = np.ascontiguousarray(frame_rgba[:, :, [2, 1, 0, 3]])
        self.screen.show(bgra)

    def snapshot_rgba(self) -> np.ndarray | None:
        """Return the last shown frame as RGBA (for headless verification)."""
        bgra = self.screen.copy()
        if bgra is None:
            return None
        return bgra[:, :, [2, 1, 0, 3]]

    def close(self):
        self.screen.close()
