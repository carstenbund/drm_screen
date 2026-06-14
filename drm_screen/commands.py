"""Command model — the stable contract between drm_composer and drm_screen.

Commands are *data*, not method calls: each is a serializable record so the same
batch survives the socket hop to the daemon (production) or a direct enqueue
(debug).  Bitmaps travel as raw RGBA bytes plus explicit (w, h, fmt) so a native
consumer can read them without inheriting numpy semantics.

`apply_command()` is the single dispatcher the render thread runs; the Composer
itself stays free of command knowledge.
"""

from dataclasses import dataclass, field, asdict
import base64

import numpy as np

from .layer import Layer
from .composer import Composer


# ── command records ───────────────────────────────────────────────────────────

@dataclass
class CreateLayer:
    name: str
    width: int
    height: int
    x: int = 0
    y: int = 0
    z: int = 0
    visible: bool = True
    opacity: float = 1.0
    interactive: bool = False
    hit_id: str | None = None


@dataclass
class DeleteLayer:
    name: str


@dataclass
class ClearLayer:
    name: str


@dataclass
class ShowLayer:
    name: str


@dataclass
class HideLayer:
    name: str


@dataclass
class SetPosition:
    name: str
    x: int
    y: int


@dataclass
class SetZ:
    name: str
    z: int


@dataclass
class PlaceRawBuffer:
    """Blit raw RGBA bytes into a layer at (x, y)."""
    name: str
    width: int
    height: int
    data: bytes              # width*height*4 RGBA bytes
    x: int = 0
    y: int = 0
    fmt: str = "RGBA8888"

    def to_array(self) -> np.ndarray:
        if self.fmt != "RGBA8888":
            raise ValueError(f"unsupported fmt {self.fmt!r}")
        return np.frombuffer(self.data, dtype=np.uint8).reshape(
            self.height, self.width, 4
        )


@dataclass
class SetInteractive:
    """Mark a layer as hit-testable and give it an id for hit_test()."""
    name: str
    interactive: bool = True
    hit_id: str | None = None


@dataclass
class SetPointer:
    """Move (and show/hide) the autonomous pointer cursor overlay.

    Fed straight to drm_screen's render queue by drm_touch — the INT 33h-style
    cursor that tracks the contact smoothly, independent of the app loop.
    """
    x: int
    y: int
    visible: bool = True


# Reserved pointer overlay — sits above everything; never hit-tested.
_POINTER_NAME = "__pointer__"
_POINTER_Z = 1_000_000
_CURSOR_R = 11


def default_cursor() -> np.ndarray:
    """A simple white ring + red centre dot; hotspot at its centre."""
    s = _CURSOR_R * 2 + 3
    yy, xx = np.ogrid[:s, :s]
    c = s // 2
    dist = np.sqrt((xx - c) ** 2 + (yy - c) ** 2)
    img = np.zeros((s, s, 4), dtype=np.uint8)
    img[(dist >= _CURSOR_R - 1.5) & (dist <= _CURSOR_R + 0.5)] = (255, 255, 255, 255)
    img[dist <= 2.0] = (255, 80, 80, 255)
    return img


def _cursor_hotspot() -> tuple[int, int]:
    c = (_CURSOR_R * 2 + 3) // 2
    return c, c


# ── dispatcher (render-thread side) ───────────────────────────────────────────

def apply_command(composer: Composer, cmd) -> None:
    """Apply one command record to the composer's layer state."""
    if isinstance(cmd, CreateLayer):
        composer.add_layer(Layer(
            name=cmd.name, width=cmd.width, height=cmd.height,
            x=cmd.x, y=cmd.y, z=cmd.z, visible=cmd.visible, opacity=cmd.opacity,
            interactive=cmd.interactive, hit_id=cmd.hit_id,
        ))
    elif isinstance(cmd, DeleteLayer):
        composer.remove_layer(cmd.name)
    elif isinstance(cmd, ClearLayer):
        composer.get(cmd.name).clear()
    elif isinstance(cmd, ShowLayer):
        composer.get(cmd.name).visible = True
    elif isinstance(cmd, HideLayer):
        composer.get(cmd.name).visible = False
    elif isinstance(cmd, SetPosition):
        layer = composer.get(cmd.name)
        layer.x, layer.y = cmd.x, cmd.y
    elif isinstance(cmd, SetZ):
        composer.get(cmd.name).z = cmd.z
    elif isinstance(cmd, PlaceRawBuffer):
        composer.get(cmd.name).blit(cmd.to_array(), cmd.x, cmd.y)
    elif isinstance(cmd, SetInteractive):
        layer = composer.get(cmd.name)
        layer.interactive = cmd.interactive
        layer.hit_id = cmd.hit_id
    elif isinstance(cmd, SetPointer):
        if _POINTER_NAME not in composer.layers:
            cur = default_cursor()
            h, w = cur.shape[:2]
            composer.add_layer(Layer(_POINTER_NAME, w, h, z=_POINTER_Z,
                                     visible=cmd.visible))
            composer.get(_POINTER_NAME).blit(cur, 0, 0)
        hx, hy = _cursor_hotspot()
        layer = composer.get(_POINTER_NAME)
        layer.x, layer.y = cmd.x - hx, cmd.y - hy
        layer.visible = cmd.visible
    else:
        raise TypeError(f"unknown command {cmd!r}")


# ── (de)serialization — the wire format for the socket transport ──────────────

_KINDS = {c.__name__: c for c in (
    CreateLayer, DeleteLayer, ClearLayer, ShowLayer, HideLayer,
    SetPosition, SetZ, PlaceRawBuffer, SetInteractive, SetPointer,
)}


def to_wire(cmd) -> dict:
    d = asdict(cmd)
    d["kind"] = type(cmd).__name__
    if "data" in d and isinstance(d["data"], (bytes, bytearray)):
        d["data"] = base64.b64encode(d["data"]).decode("ascii")
    return d


def from_wire(d: dict):
    d = dict(d)
    kind = d.pop("kind")
    if "data" in d and isinstance(d["data"], str):
        d["data"] = base64.b64decode(d["data"])
    return _KINDS[kind](**d)
