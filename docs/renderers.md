# Renderers — who draws, and how to plug in another one

`drm_screen` owns layers. Until now it also owned the only way to turn them
into pixels: blend the buffers with numpy, convert RGBA→BGRA, hand one frame to
`drm_display`. That path is portable, needs nothing but numpy, and stays the
default.

It is also a floor. Every change costs a whole-frame blend and a whole-frame
colour conversion, whatever actually moved; and a layer can only carry pixels,
so by the time content arrives it is already rasterised and a stroke can no
longer be drawn *half* way.

Where a platform can do better, it should be allowed to — without the layer
model, the command records, or the service changing at all. That is what a
renderer is.

## The seam

```python
class Renderer(Protocol):
    name: str
    capabilities: frozenset[str]
    width: int
    height: int

    def apply(self, command) -> None: ...          # one command record
    def present(self, scene_time_ms: float = 0.0) -> None: ...
    def hit_test(self, x: int, y: int) -> str | None: ...
    def snapshot_rgba(self) -> np.ndarray | None: ...
    def close(self) -> None: ...
```

Two optional members, both honest rather than decorative:

| | |
|---|---|
| `available()` | a classmethod/staticmethod: can this machine actually run it? A plugin whose native library is missing is installed but not usable, and must drop out of `available()` rather than fail at construction. |
| `animating` | True while the renderer holds content that is a function of time (a scene). The service's dirty flag alone would freeze such content on its first frame. |

## Capabilities

A renderer declares what it can do, and **refuses what it cannot** — a screen
that silently drops a command leaves the client believing something is on the
panel that is not.

| Capability | Meaning |
|---|---|
| `layers` | named, persistent, z-ordered layers |
| `raw_buffer` | `PlaceRawBuffer` — RGBA bytes into a layer |
| `hit_test` | interactive layers and `hit_test()` |
| `snapshot` | the presented frame can be read back |
| `scene` | `PlaceScene` — a layer holds primitives, evaluated per frame |
| `partial_update` | only what changed is drawn and pushed |

## Choosing one

```python
ScreenService(backend)                      # unchanged: the numpy compositor
ScreenService(renderer="lvgl")              # by name
ScreenService(renderer=my_renderer)         # an instance
ScreenService(renderer="lvgl", renderer_options={"display": "memory"})
```

`renderer="auto"` is the default and it is deliberately conservative: **a caller
that passes a backend gets the RGBA path it has always had.** Without a backend,
the most capable installed renderer is used, and `rgba` is what remains when
there is none.

`DRM_SCREEN_RENDERER=lvgl` overrides `auto`, so an existing deployment can be
moved onto a plugin — or pinned off one — without editing its code.

## Writing a plugin

A plugin is an ordinary distribution that registers an entry point:

```toml
[project.entry-points."drm_screen.renderers"]
lvgl = "drm_screen_lvgl:LvglRenderer"
```

`drm_screen` imports nothing by name and knows no plugin exists until it looks.
A plugin that fails to import, or answers `available() → False`, is simply not
offered.

Dispatch inside a plugin should be **by command class name, not by identity**:
a record may come from this package, from an older release of it, or across a
socket from a machine with neither, and it means the same thing either way.
Read fields with defaults for the same reason — `CreateLayer` grew
`interactive`/`hit_id` after it shipped.

The first plugin is
[`drm_screen_lvgl`](https://github.com/carstenbund/drm_screen_lvgl): LVGL
composites its own dirty rectangles and presents through DRM/KMS itself, and a
layer there can hold a scene.

## Scenes

```python
service.submit([
    CreateLayer("writing", 1920, 1080, z=10),
    PlaceScene("writing", scene_json),      # paths, not pixels
])
```

A scene is a description — objects and the animations that move their
properties — evaluated by the renderer against `scene_time_ms` every frame. It
is never rasterised into a buffer that has to be carried anywhere: a 1.4 KB
document fills 1920×1080.

The RGBA compositor raises `UnsupportedCommand` for `PlaceScene`, because by the
time content reaches that path it is already pixels. Rasterise it yourself and
send `PlaceRawBuffer`, or install a renderer that declares the `scene`
capability.

`drm_composer` emits `PlaceScene` for a layer of `<path>` elements — see its
`SYNTAX.md`.
