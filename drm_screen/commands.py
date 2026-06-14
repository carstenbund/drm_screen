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


# ── dispatcher (render-thread side) ───────────────────────────────────────────

def apply_command(composer: Composer, cmd) -> None:
    """Apply one command record to the composer's layer state."""
    if isinstance(cmd, CreateLayer):
        composer.add_layer(Layer(
            name=cmd.name, width=cmd.width, height=cmd.height,
            x=cmd.x, y=cmd.y, z=cmd.z, visible=cmd.visible, opacity=cmd.opacity,
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
    else:
        raise TypeError(f"unknown command {cmd!r}")


# ── (de)serialization — the wire format for the socket transport ──────────────

_KINDS = {c.__name__: c for c in (
    CreateLayer, DeleteLayer, ClearLayer, ShowLayer, HideLayer,
    SetPosition, SetZ, PlaceRawBuffer,
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
