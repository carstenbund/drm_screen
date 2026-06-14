#!/usr/bin/env python3
"""drm_screen prototype — exercises the full service path, headless.

Forces the dummy backend so it never touches a real display.  Simulates the
command batch drm_composer would emit for a small scene, submits it through the
in-process target, lets the render thread composite, then saves the result.
"""

import os
import sys
import time

# Make the sibling drm_screen package importable without installing it.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image, ImageDraw

from drm_screen import DrmDisplayBackend, ScreenService, InProcessTarget
from drm_screen.assets import solid_rgba
from drm_screen.commands import (
    CreateLayer, PlaceRawBuffer, SetZ, HideLayer, ShowLayer,
    to_wire, from_wire,
)

W, H = 800, 480
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frame.png")


def text_bitmap(text, w, h, fg=(255, 255, 255, 255)) -> np.ndarray:
    """Stand-in for drm_composer's painter: rasterize text to an RGBA array."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((12, h // 2 - 8), text, fill=fg)
    return np.asarray(img, dtype=np.uint8)


def raw(name, rgba, x=0, y=0):
    h, w = rgba.shape[:2]
    return PlaceRawBuffer(
        name=name, width=w, height=h,
        data=np.ascontiguousarray(rgba).tobytes(), x=x, y=y,
    )


def main():
    # 1. Service with the headless backend (safe: never writes to a real screen).
    backend = DrmDisplayBackend(device="dummy", width=W, height=H)
    service = ScreenService(backend, fps=30)
    target = InProcessTarget(service)
    service.start()
    print(f"service started: {backend.width}x{backend.height} (headless)")

    # 2. A scene, as the command batch drm_composer would produce.
    #    background (z=0) -> translucent status card (z=10) -> text (z=20)
    batch = [
        CreateLayer("background", W, H, z=0),
        raw("background", solid_rgba(W, H, (20, 30, 60, 255))),    # dark blue

        CreateLayer("status", 360, 90, x=40, y=40, z=10),
        raw("status", solid_rgba(360, 90, (0, 0, 0, 170))),        # translucent black box

        CreateLayer("label", 360, 90, x=40, y=40, z=20),
        raw("label", text_bitmap("drm_screen prototype: System ready", 360, 90)),
    ]

    # 3. Prove the batch is serializable (the production socket path).
    round_tripped = [from_wire(to_wire(c)) for c in batch]
    assert all(type(a) is type(b) for a, b in zip(batch, round_tripped)), "wire mismatch"
    print(f"wire round-trip OK ({len(batch)} commands)")

    # 4. Submit (non-blocking) and let the render thread do its thing.
    target.submit(round_tripped)
    time.sleep(0.1)

    # 5. Demonstrate a later mutation: hide then show the status card.
    target.submit([HideLayer("status"), HideLayer("label")])
    time.sleep(0.1)
    target.submit([ShowLayer("status"), ShowLayer("label")])
    time.sleep(0.1)

    # 6. Read back the composited frame and verify a few pixels.
    frame = backend.snapshot_rgba()
    assert frame is not None, "nothing rendered"
    assert frame.shape == (H, W, 4), frame.shape

    bg = frame[300, 600]             # pure background, clear of every layer
    card = frame[120, 370]           # under translucent card, below the text row
    print("background pixel (RGBA):", tuple(int(v) for v in bg))
    print("card pixel      (RGBA):", tuple(int(v) for v in card))
    assert tuple(bg[:3]) == (20, 30, 60), "background color wrong"
    # card is darker than bg because of the translucent black box on top
    assert card[2] < bg[2], "alpha blend did not darken under the card"

    Image.fromarray(frame, "RGBA").save(OUT)
    print(f"saved composited frame -> {OUT}")

    service.stop()
    print("service stopped cleanly")


if __name__ == "__main__":
    main()
