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
