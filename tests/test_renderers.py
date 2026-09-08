"""The renderer seam: does choosing who draws change anything else?

Two claims are under test. The first is that nothing moved: a service given a
backend composites with numpy and produces the pixels it always did. The second
is that a plugin is genuinely a plugin -- it receives the same command records,
it is asked to present at a scene time, and `drm_screen` needs to know nothing
about it beyond the protocol.

No hardware and no plugin is required to run this: the backend is a stub that
keeps the last frame, and the plugin is a class defined in the file.
"""

import numpy as np
import pytest

from drm_screen import commands as cmd
from drm_screen.commands import UnsupportedCommand, from_wire, to_wire
from drm_screen.renderers import (
    CAP_SCENE, RgbaRenderer, available, get_renderer,
)
from drm_screen.service import ScreenService

W, H = 64, 40
RED = (220, 60, 60, 255)


def solid(width, height, rgba):
    buf = np.empty((height, width, 4), dtype=np.uint8)
    buf[:] = np.asarray(rgba, dtype=np.uint8)
    return buf


class StubBackend:
    """`drm_display` without the display."""

    def __init__(self, width=W, height=H):
        self.width, self.height = width, height
        self.frame = None
        self.writes = 0
        self.closed = False

    def write(self, frame_rgba):
        self.frame = frame_rgba.copy()
        self.writes += 1

    def snapshot_rgba(self):
        return self.frame

    def close(self):
        self.closed = True


class FakeLvglRenderer:
    """A plugin, in the shape a real one has: it keeps its own layer state and
    presents at a scene time rather than handing back a frame."""

    name = "fake"
    capabilities = frozenset({"layers", "raw_buffer", "hit_test", CAP_SCENE})

    def __init__(self, width=W, height=H):
        self.width, self.height = width, height
        self.applied = []
        self.presented_at = []
        self.closed = False
        self.animating = False

    def apply(self, command):
        self.applied.append(command)
        if type(command).__name__ == "PlaceScene":
            self.animating = True

    def present(self, scene_time_ms=0.0):
        self.presented_at.append(scene_time_ms)

    def hit_test(self, x, y):
        return "fake"

    def snapshot_rgba(self):
        return None

    def close(self):
        self.closed = True


# -- nothing moved --------------------------------------------------------


def test_the_default_path_is_the_path_it_always_was():
    backend = StubBackend()
    service = ScreenService(backend)

    assert service.renderer.name == "rgba"
    assert service.backend is backend
    assert service.composer is service.renderer.composer

    service.submit([
        cmd.CreateLayer("box", 20, 10, x=4, y=4),
        cmd.PlaceRawBuffer("box", 20, 10, data=solid(20, 10, RED).tobytes()),
    ])
    service.render_once()

    assert backend.writes == 1
    assert tuple(backend.frame[6, 6]) == RED


def test_the_dirty_flag_still_holds_the_loop_still():
    backend = StubBackend()
    service = ScreenService(backend)
    service.submit([cmd.CreateLayer("box", 20, 10)])
    service.render_once()
    service.render_once()

    assert backend.writes == 1


def test_a_renderer_presents_what_the_composer_blends():
    backend = StubBackend()
    renderer = RgbaRenderer(backend=backend)
    renderer.apply(cmd.CreateLayer("box", W, H))
    renderer.apply(cmd.PlaceRawBuffer("box", W, H, data=solid(W, H, RED).tobytes()))

    expected = renderer.composer.render()
    renderer.present()

    np.testing.assert_array_equal(backend.frame, expected)


def test_stopping_the_service_closes_the_renderer():
    backend = StubBackend()
    ScreenService(backend).stop()
    assert backend.closed


# -- choosing ------------------------------------------------------------


def test_rgba_is_always_available():
    assert "rgba" in available()


def test_a_renderer_instance_is_used_as_it_is():
    plugin = FakeLvglRenderer()
    assert get_renderer(plugin) is plugin


def test_an_unknown_renderer_is_refused_by_name():
    with pytest.raises(LookupError, match="fictional"):
        get_renderer("fictional")


def test_the_environment_can_move_a_deployment(monkeypatch):
    """The no-code-change path: an existing call site, a different renderer."""
    plugin = FakeLvglRenderer()
    monkeypatch.setattr("drm_screen.renderers.available", lambda: {
        "rgba": RgbaRenderer, "fake": lambda **kw: plugin,
    })
    monkeypatch.setenv("DRM_SCREEN_RENDERER", "fake")

    assert get_renderer("auto", backend=StubBackend()) is plugin


# -- the plugin, through the service --------------------------------------


def test_a_plugin_receives_the_commands_and_the_clock():
    now = [1000.0]
    plugin = FakeLvglRenderer()
    service = ScreenService(renderer=plugin, clock=lambda: now[0])

    service.submit([
        cmd.CreateLayer("scene", W, H),
        cmd.PlaceScene("scene", b'{"id": 1}'),
    ])
    service.render_once()
    now[0] = 2500.0
    service.render_once()

    assert [type(c).__name__ for c in plugin.applied] == ["CreateLayer", "PlaceScene"]
    assert plugin.presented_at == [1000.0, 2500.0]
    assert service.hit_test(1, 1) == "fake"


def test_a_scene_keeps_being_drawn_when_nothing_was_submitted():
    """Time is a change even when no command is: the dirty flag alone would
    freeze an animation on its first frame."""
    plugin = FakeLvglRenderer()
    service = ScreenService(renderer=plugin)
    service.submit([cmd.PlaceScene("scene", b"{}")])

    service.render_once(0.0)
    service.render_once(16.0)

    assert plugin.presented_at == [0.0, 16.0]


# -- commands -------------------------------------------------------------


def test_the_rgba_path_refuses_a_scene_rather_than_dropping_it():
    renderer = RgbaRenderer(backend=StubBackend())
    with pytest.raises(UnsupportedCommand, match="scene"):
        renderer.apply(cmd.PlaceScene("scene", b"{}"))


def test_opacity_can_change_after_the_layer_exists():
    renderer = RgbaRenderer(backend=StubBackend())
    renderer.apply(cmd.CreateLayer("box", 10, 10))
    renderer.apply(cmd.SetOpacity("box", 0.25))

    assert renderer.composer.get("box").opacity == 0.25


@pytest.mark.parametrize("scene", [b'{"id": 1}', '{"id": 1}'])
def test_a_scene_survives_the_wire_as_what_it_was(scene):
    """Bitmaps are always bytes; a scene may be text, and must come back as
    text -- a base64 round trip that silently changes the type would break the
    socket transport for one of the two."""
    restored = from_wire(to_wire(cmd.PlaceScene("scene", scene)))

    assert restored.scene == scene
    assert isinstance(restored.scene, type(scene))


def test_a_bitmap_still_survives_the_wire():
    original = cmd.PlaceRawBuffer("box", 2, 1, data=bytes(range(8)))
    restored = from_wire(to_wire(original))

    assert restored == original


def test_a_plugin_can_be_configured_through_the_service():
    """Renderers take arguments the RGBA path never needed -- which display,
    what size -- and the service passes them through rather than knowing them."""
    seen = {}

    def factory(**kwargs):
        seen.update(kwargs)
        return FakeLvglRenderer()

    service = ScreenService(renderer=factory(width=320, height=200))
    assert seen == {"width": 320, "height": 200}
    assert service.renderer.name == "fake"


def test_a_plugin_that_cannot_run_here_is_not_offered(monkeypatch):
    """Installed is not usable. A plugin missing its native library must drop
    out of `available()`, or `auto` picks something that cannot be built."""

    class Unusable(FakeLvglRenderer):
        @staticmethod
        def available():
            return False

    class Entry:
        name = "unusable"

        @staticmethod
        def load():
            return Unusable

    monkeypatch.setattr("drm_screen.renderers._entry_point_renderers",
                        lambda: {"unusable": Entry})

    assert "unusable" not in available()
    assert get_renderer("auto").name == "rgba"
