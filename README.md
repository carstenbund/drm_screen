# drm_screen

Stateful screen manager. Owns persistent **layers**, composites them into a
single frame, and pushes it to [`drm_display`](../drm_display).

Python package: `drm_screen`.

```
drm_composer  →  drm_screen  →  drm_display
 scene → cmds     layers →         frame →
                  composited       DRM/KMS
                  frame            pixels
```

- Owns layer state (named RGBA buffers: position, z, visibility, opacity)
- Z-ordered alpha composition → one canvas
- Exposes the command API that `drm_composer` targets
- Dirty-flagged render loop

All buffers are **RGBA**; the single RGBA→BGRA conversion happens in the backend
adapter just before `drm_display`. It does **not** parse HTML and does **not**
touch DRM/KMS.

See [outline.md](outline.md) for the design.

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

## License

**GPL-3.0-or-later** (see [LICENSE](LICENSE)). Use it freely under the GPL. For
proprietary/closed use that cannot comply with the GPL, a separate commercial
license is available — contact Carsten Bund <carstenbund@gmail.com>.

Dependencies are permissive (BSD/MIT) and installed separately; their notices
are in [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
