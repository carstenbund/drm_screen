"""Renderers — who turns layers into pixels, and where those pixels go.

`drm_screen` has had exactly one answer to that since it was written: blend the
layer buffers with numpy, convert RGBA→BGRA, hand the frame to `drm_display`.
That answer is correct, portable, and needs nothing but numpy — it stays, and it
stays the default. It is a floor, not a ceiling:

* every change costs a whole-frame blend and a whole-frame colour conversion,
  whatever actually moved;
* a layer can only carry pixels, so by the time content arrives here a stroke is
  already rasterised and can no longer be drawn *half* way.

Some platforms can do better. Where LVGL is available it composites into its own
dirty rectangles and presents through DRM/KMS itself, and a layer there can hold
a *scene* — paths drawn at the panel's resolution, never rasterised into a
buffer that has to be carried anywhere.

So the choice becomes a seam rather than a fact. A renderer:

    name            what to ask for by name, and what appears in logs
    capabilities    what it can honestly do -- checked, not assumed
    apply(cmd)      one command record, applied to layer state
    present()       composite and put the result on the panel
    hit_test(x, y)  topmost interactive layer under a point
    snapshot_rgba() the last presented frame, where that can be read back
    close()

`RgbaRenderer` is that seam wrapped around the code that was already here, so
the default path is the same pixels through the same numpy blend as before.
Anything else is a plugin: installed separately, discovered at import, absent
without consequence. See `docs/renderers.md`.
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

import numpy as np

from .commands import apply_command
from .composer import Composer

__all__ = [
    "CAP_HIT_TEST", "CAP_LAYERS", "CAP_PARTIAL_UPDATE", "CAP_RAW_BUFFER",
    "CAP_SCENE", "CAP_SNAPSHOT", "Renderer", "RgbaRenderer", "available",
    "get_renderer",
]

#: Capabilities. A renderer declares what it can do and a caller may ask; a
#: renderer that cannot honour a command must refuse it rather than skip it.
CAP_LAYERS = "layers"                  #: named, persistent, z-ordered layers
CAP_RAW_BUFFER = "raw_buffer"          #: PlaceRawBuffer -- RGBA bytes into a layer
CAP_HIT_TEST = "hit_test"              #: interactive layers and hit_test()
CAP_SNAPSHOT = "snapshot"              #: the presented frame can be read back
CAP_SCENE = "scene"                    #: PlaceScene -- a layer holds primitives
CAP_PARTIAL_UPDATE = "partial_update"  #: only what changed is drawn and pushed

#: Set DRM_SCREEN_RENDERER=lvgl to move an existing deployment onto a plugin
#: without touching its code, or =rgba to pin it to the path it has always used.
ENV_RENDERER = "DRM_SCREEN_RENDERER"


@runtime_checkable
class Renderer(Protocol):
    """What the service needs from whoever is drawing."""

    name: str
    capabilities: frozenset[str]
    width: int
    height: int

    def apply(self, command) -> None: ...
    def present(self, scene_time_ms: float = 0.0) -> None: ...
    def hit_test(self, x: int, y: int) -> str | None: ...
    def snapshot_rgba(self) -> np.ndarray | None: ...
    def close(self) -> None: ...


class RgbaRenderer:
    """The original path, behind the seam: numpy layers, one blend, one frame.

    Available everywhere numpy is, which is the point of keeping it. It holds
    the same `Composer` it always did, so `service.composer` still means what it
    meant and code reaching into `composer.layers` still finds numpy buffers.
    """

    name = "rgba"
    capabilities = frozenset({CAP_LAYERS, CAP_RAW_BUFFER, CAP_HIT_TEST, CAP_SNAPSHOT})

    def __init__(self, backend=None, device=None, width=None, height=None):
        if backend is None:
            from .backend import DrmDisplayBackend

            backend = DrmDisplayBackend(device=device, width=width, height=height)
        self.backend = backend
        self.width, self.height = backend.width, backend.height
        self.composer = Composer(self.width, self.height)

    def apply(self, command) -> None:
        apply_command(self.composer, command)

    def present(self, scene_time_ms: float = 0.0) -> None:
        # scene_time_ms is meaningless here: nothing on this path animates by
        # itself, because nothing on it is still a description by the time it
        # arrives. Accepted so the two renderers are called the same way.
        self.backend.write(self.composer.render())

    def hit_test(self, x: int, y: int) -> str | None:
        return self.composer.hit_test(x, y)

    def snapshot_rgba(self) -> np.ndarray | None:
        return self.backend.snapshot_rgba()

    def close(self) -> None:
        self.backend.close()


# -- discovery ----------------------------------------------------------------


def _entry_point_renderers() -> dict[str, object]:
    """Renderers other packages have registered.

    A plugin declares, in its own pyproject:

        [project.entry-points."drm_screen.renderers"]
        lvgl = "drm_screen_lvgl:LvglRenderer"

    and needs nothing from this package to be found. Loading is deferred: a
    plugin that fails to import is simply not available, which is the whole
    contract -- `drm_screen` must keep working on a machine that has none.
    """
    from importlib.metadata import entry_points

    found: dict[str, object] = {}
    for entry in entry_points(group="drm_screen.renderers"):
        found[entry.name] = entry
    return found


def available() -> dict[str, object]:
    """Every renderer this machine can actually construct, by name.

    `rgba` is always in it. A plugin is here because it is installed, it
    imports, and -- if it says so -- because the things it needs are present:
    a renderer may expose `available()`, and one that answers False is a
    package sitting on a machine that cannot run it (no native library, no
    display driver), which is not the same as being installed.
    """
    found: dict[str, object] = {"rgba": RgbaRenderer}
    for name, entry in _entry_point_renderers().items():
        try:
            factory = entry.load()
            probe = getattr(factory, "available", None)
            if probe is not None and not probe():
                continue
        except Exception:  # a plugin that cannot import is simply not offered
            continue
        found[name] = factory
    return found


def get_renderer(renderer="auto", backend=None, **kwargs) -> Renderer:
    """Resolve `renderer` to something the service can draw with.

    * a `Renderer` instance is used as it is;
    * a name picks that one and fails loudly if it is not installed;
    * `"auto"` (the default) keeps existing behaviour: a caller that passed a
      backend gets the RGBA path it has always had. Without a backend, the best
      installed plugin is used, and `rgba` is what remains when there is none.

    `DRM_SCREEN_RENDERER` overrides `"auto"`, so an existing deployment can be
    moved onto a plugin -- or pinned off one -- without editing its code.
    """
    if not isinstance(renderer, str):
        return renderer

    found = available()
    if renderer == "auto":
        renderer = os.environ.get(ENV_RENDERER, "").strip() or (
            "rgba" if backend is not None else _preferred(found)
        )

    if renderer not in found:
        offered = ", ".join(sorted(found))
        raise LookupError(f"no renderer named {renderer!r}; installed: {offered}")

    factory = found[renderer]
    if renderer == "rgba":
        return factory(backend=backend, **kwargs)
    return factory(**kwargs)


def _preferred(found: dict[str, object]) -> str:
    """Whichever installed renderer can do the most. Ties go to the one that
    was there first, which is `rgba`."""
    best, best_score = "rgba", -1
    for name, factory in found.items():
        capabilities = getattr(factory, "capabilities", frozenset())
        score = len(capabilities)
        if score > best_score:
            best, best_score = name, score
    return best
