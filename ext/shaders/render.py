"""
Render settings for the ray-traced path, and the scene checks it needs.

Pixel values are signal values, so every setting that changes a value for a
better-looking picture must be off:

- Cycles is the engine, because it traces the reflections.
- No tone mapping: view transform Standard, no look, exposure 0, gamma 1.
- No sample clamping. Cycles clamps indirect light to 10 by default, and a
  signal is often much larger, so the clamp would cut the reflections.
- No Filter Glossy, which blurs reflections for less noise but adds bias.
- No denoising, which changes pixel values. Use more samples instead.
- Enough bounces. In a closed space the missing energy is about
  (1 - eps) ** (bounces + 1), so low emissivity needs more bounces.
- An opaque film, so the background signal is in the image.
"""

from typing import List

from bpy.types import Scene

from ..constants import TEMPERATURE_ATTR_NAME

# Lower limit for the bounce counts. A higher value set by the user is kept.
MIN_BOUNCES = 8

# Number of object names a warning lists before it shortens.
_NAMES_SHOWN = 5


def apply_ray_render_settings(scene: Scene) -> None:
    """ Set the render settings that keep pixel values equal to signal. """
    scene.render.engine = 'CYCLES'
    scene.render.film_transparent = False

    view = scene.view_settings
    view.view_transform = 'Standard'
    view.look = 'None'
    view.exposure = 0.0
    view.gamma = 1.0

    cycles = scene.cycles
    cycles.film_exposure = 1.0
    cycles.sample_clamp_direct = 0.0    # 0 disables the clamp
    cycles.sample_clamp_indirect = 0.0
    cycles.blur_glossy = 0.0
    cycles.use_denoising = False
    cycles.use_preview_denoising = False
    for name in ('max_bounces', 'diffuse_bounces', 'glossy_bounces'):
        setattr(cycles, name, max(getattr(cycles, name), MIN_BOUNCES))


def ray_scene_warnings(scene: Scene) -> List[str]:
    """ Conditions that make the ray-traced image wrong. The scene is not
    changed: the user decides what to do.
    """
    warnings = []

    lights = [
        obj for obj in scene.objects
        if obj.type == 'LIGHT' and not obj.hide_render
    ]
    if lights:
        warnings.append(
            f"{len(lights)} light(s) add visible-light radiance to the thermal "
            f"image ({_names(lights)}). Disable them in renders."
        )

    unbaked = [
        obj for obj in scene.objects
        if obj.type == 'MESH' and not obj.hide_render
        and obj.data.attributes.get(TEMPERATURE_ATTR_NAME) is None
    ]
    if unbaked:
        warnings.append(
            f"{len(unbaked)} mesh(es) are not baked and keep their own "
            f"materials, which other surfaces reflect ({_names(unbaked)}). "
            f"Bake them or disable them in renders."
        )
    return warnings


def _names(objects) -> str:
    """ The first object names, and a count of the others. """
    names = ", ".join(repr(obj.name) for obj in objects[:_NAMES_SHOWN])
    more = len(objects) - _NAMES_SHOWN
    return f"{names} and {more} more" if more > 0 else names
