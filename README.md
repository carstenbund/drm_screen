# drm_screen

Stateful screen manager. Owns persistent **layers**, composites them into a
single frame, and pushes it to [`drm_display`](https://github.com/carstenbund/drm_display).

Python package: `drm_screen`.

```
drm_composer  →  drm_screen  →  drm_display
 scene → cmds     layers →         frame →
                  composited       DRM/KMS
                  or drawn         pixels
                  as scenes
```

- Owns layer state (named RGBA buffers: position, z, visibility, opacity)
- Z-ordered alpha composition → one canvas
- Exposes the command API that `drm_composer` targets
- Dirty-flagged render loop
- Chooses a **renderer**: numpy by default; a layer that holds primitives
  rather than pixels needs a plugin that can draw them

All buffers are **RGBA**; the single RGBA→BGRA conversion happens in the backend
adapter just before `drm_display`. It does **not** parse HTML and does **not**
touch DRM/KMS.

See [outline.md](https://github.com/carstenbund/drm_screen/blob/main/outline.md) for the design.

## Renderers

Composition is a choice now, not a fact. The numpy compositor above is the
default and needs nothing extra; a plugin can take over the same layers where a
platform can do better — and one command reaches further than the default can
follow:

| Renderer | Where it comes from | What it adds |
|---|---|---|
| `rgba` | built in | works anywhere numpy does |
| `lvgl` | [`drm-screen-lvgl`](https://github.com/carstenbund/drm_screen_lvgl) | draws only what changed; presents straight to DRM/KMS; layers can hold **scenes** — paths drawn at panel resolution, animated against a clock, never rasterised |

```python
ScreenService(backend)              # unchanged — the numpy compositor
ScreenService(renderer="lvgl")      # installed plugin, same commands
DRM_SCREEN_RENDERER=lvgl python app.py    # an existing app, no code change
```

### `PlaceScene` needs a scene renderer

Every other command works on any renderer.  `PlaceScene` — a layer holding
primitives instead of pixels, which is what `drm_composer` emits for a layer of
`<path>` elements — needs one that declares the `scene` capability.  The
built-in RGBA compositor carries pixels only and raises `UnsupportedCommand`
rather than rasterising the scene behind your back, so on a default install
such a layer is an error, not a quietly different picture:

```bash
pip install drm-screen-lvgl
```

See [docs/renderers.md](https://github.com/carstenbund/drm_screen/blob/main/docs/renderers.md) for the protocol, the
capability list, and how to write one.

## Install

```bash
pip install drm-screen            # also pulls in drm-display
pip install "drm-screen[assets]"  # + pillow, for image/asset loading
```

Standalone — `drm-screen` is all you need to manage layers and drive a display.

## Part of the drm_stack

Each package installs and runs on its own:

| Package | Role |
|---|---|
| [`drm-composer`](https://github.com/carstenbund/drm_composer) | screen-HTML → layer commands |
| **`drm-screen`** | layers → composited frame · *this package* |
| [`drm-display`](https://github.com/carstenbund/drm_display) | frame → DRM/KMS pixels |

Full stack, bootstrap, and integration demo:
[`drm_stack`](https://github.com/carstenbund/drm_stack).

## Changes

```
0.2.2   Packaging.  The Author header was empty -- a {name, email} author maps
        to Author-email alone -- so tools reading Author showed no author at
        all.  The summary still described 0.1: layers and compositing, no
        renderers, no scenes, no pointer input.
0.2.1   Documentation.  PlaceScene needs a renderer with the `scene`
        capability and the README did not say so -- it presented a plugin as
        an upgrade for platforms that can do better, when one command is not
        available without it at all.  Relative links, which 404 on PyPI
        because the README is the project description.  This release history.
0.2.0   Composition became a plugin point: a renderer is chosen rather than
        assumed, with the numpy compositor still the default and `lvgl` an
        installable alternative.  PlaceScene lets a layer hold primitives
        instead of pixels -- the RGBA compositor refuses that command rather
        than rasterising behind your back, so a missing plugin is an error
        and not a silently different picture.  Hit-testing and a pointer
        overlay for touch and mouse input.
0.1.0   initial -- layers, the RGBA compositor, the service, and the command
        contract
```

## License

**GPL-3.0-or-later** (see [LICENSE](https://github.com/carstenbund/drm_screen/blob/main/LICENSE)). Use it freely under the GPL. For
proprietary/closed use that cannot comply with the GPL, a separate commercial
license is available — contact Carsten Bund <carstenbund@gmail.com>.

Dependencies are permissive (BSD/MIT) and installed separately; their notices
are in [THIRD_PARTY_LICENSES.md](https://github.com/carstenbund/drm_screen/blob/main/THIRD_PARTY_LICENSES.md).
