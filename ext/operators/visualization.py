"""
Bpy-facing orchestration for building the thermal material and assigning it to
every baked object.

The shading path is resolved from the scene's ThermalRenderSettings, so this
operator holds no knowledge of how any particular material is built.
"""

from typing import List, Optional

import bpy
import numpy as np
from bpy.types import Operator, Object, Material, World

from .names import Labels
from ..constants import (
    EMISSIVITY_ATTR_NAME, TEMPERATURE_ATTR_NAME, TEMPERATURE_MATERIAL_NAME, THERMAL_WORLD_NAME,
)
from ..thermal_core.contracts import EnvironmentSpecType, ShadingType, TransferType
from ..thermal_core.temperature import Conversions, TempUnit
from ..shaders.registry import ShaderRegistry
from ..shaders.render import apply_ray_render_settings, ray_scene_warnings
from ..shaders.transfer import TransferNodeRegistry
from ..shaders.world import build_thermal_world
from ..ui.environment_registry import EnvSearch

from ..ui.color_bar_gpu import left_bottom_color_bar


class VisualizeTemperatureOperator(Operator):
    """ Builds/updates the single shared TEMPERATURE_MATERIAL_NAME material
    scaled to the min/max across every baked mesh object's TEMPERATURE_ATTR_NAME values,
    and assigns it to material slot 0 on each of those objects.

    """
    bl_idname = Labels.VISUALIZE_TEMPERATURE.value
    bl_label = "Visualize Temperature"
    bl_description = (
        "Color every baked object by its temperature attribute, using a "
        "shared min/max scale across the scene"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objects_iter = VisualizeTemperatureOperator._iter_baked_mesh_objects(context)
        if not objects_iter:
            self.report({'WARNING'}, "No baked temperature data found, run Bake first")
            return {'CANCELLED'}

        scene = context.scene
        settings = scene.thermal_render
        shading_type = ShadingType[settings.shading_type]
        traces = shading_type.traces_reflections()

        try:
            descriptor = ShaderRegistry.get(shading_type)
            # Resolved before anything is built, so a missing factor changes
            # nothing in the scene.
            background_k = (
                VisualizeTemperatureOperator._background_temperature_k() if traces else None
            )
            material = VisualizeTemperatureOperator._get_or_create_material()
            descriptor.build(material, settings)
            if traces:
                VisualizeTemperatureOperator._prepare_ray_scene(scene, settings, background_k)
        except (NotImplementedError, ValueError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}

        # For now, override the current material to display the baked thermal
        # map over the scene.
        for obj in objects_iter:
            VisualizeTemperatureOperator._assign_material(obj, material)

        if traces:
            message = (
                f"Built '{shading_type.value}' on {len(objects_iter)} object(s), the "
                f"'{THERMAL_WORLD_NAME}' background and the render settings. Switch "
                f"viewport shading to Rendered to see it."
            )
        else:
            message = (
                f"Built '{shading_type.value}' on {len(objects_iter)} object(s). Switch "
                f"viewport shading to Material Preview or Rendered to see it."
            )

        warnings = []
        # A missing emissivity map reads as 0.0 in the shader since the object
        # shows only the reflected environment. Paths without transfer
        # dont read emissivity.
        missing = VisualizeTemperatureOperator._without_emissivity(objects_iter)
        if missing and shading_type.uses_transfer():
            names = ", ".join(repr(obj.name) for obj in missing[:5])
            more = f" and {len(missing) - 5} more" if len(missing) > 5 else ""
            warnings.append(
                f"{len(missing)} object(s) have no emissivity map and render as "
                f"perfect mirrors ({names}{more}). Bake again."
            )
        if traces:
            warnings.extend(ray_scene_warnings(scene))

        if warnings:
            self.report({'WARNING'}, " ".join([message, *warnings]))
        else:
            self.report({'INFO'}, message)
        return {'FINISHED'}

    @staticmethod
    def _background_temperature_k() -> float:
        """ The background temperature of the ray-traced paths: the scene's
        Ambient Temperature factor, the same single source of truth that the
        Ambient initialization reads.
        """
        spec = EnvSearch.build(EnvironmentSpecType.AMBIENT_TEMPERATURE)
        if spec is None:
            raise ValueError(
                "The ray-traced shading needs a background temperature. Add an "
                "Ambient Temperature factor in Scene Properties > Thermal Environment."
            )
        return spec.value_k

    @staticmethod
    def _prepare_ray_scene(scene, settings, background_k: float) -> None:
        """ Build the thermal World with the materials' transfer, assign it,
        and set the render settings that keep pixel values linear.
        """
        transfer = TransferNodeRegistry.get(TransferType[settings.transfer_type])
        props = getattr(settings, transfer.attr_name)
        world = VisualizeTemperatureOperator._get_or_create_world(scene)
        build_thermal_world(world, transfer, props, background_k)
        apply_ray_render_settings(scene)

    @staticmethod
    def _get_or_create_world(scene) -> World:
        """ The thermal World, assigned to scene. The previous World gets a
        fake user, so Blender does not delete it on save when no other scene
        uses it.
        """
        world = bpy.data.worlds.get(THERMAL_WORLD_NAME)
        if world is None:
            world = bpy.data.worlds.new(name=THERMAL_WORLD_NAME)
        previous = scene.world
        if previous is not None and previous != world:
            previous.use_fake_user = True
        scene.world = world
        return world

    @staticmethod
    def _without_emissivity(objects: List[Object]) -> List[Object]:
        """ The objects that have no baked emissivity map. """
        return [obj for obj in objects if obj.data.attributes.get(EMISSIVITY_ATTR_NAME) is None]

    @staticmethod
    def _read_temperature_values(obj: Object) -> Optional[np.ndarray]:
        """ Reads TEMPERATURE_ATTR_NAME off obj's mesh into a numpy array, or
        None if the object has no such attribute (i.e. hasn't been baked).
        """
        attribute = obj.data.attributes.get(TEMPERATURE_ATTR_NAME)
        if attribute is None:
            return None
        values = np.empty(len(obj.data.vertices), dtype=np.float64)
        attribute.data.foreach_get('value', values)
        return values

    @staticmethod
    def _iter_baked_mesh_objects(context) -> List[Object]:
        """ Returns an iterator to every mesh object in the scene that has already been baked.
        """
        return [
            obj for obj in context.scene.objects
            if obj.type == 'MESH' and obj.data.attributes.get(TEMPERATURE_ATTR_NAME) is not None
        ]

    @staticmethod
    def _get_or_create_material() -> Material:
        material = bpy.data.materials.get(TEMPERATURE_MATERIAL_NAME)
        if material is None:
            material = bpy.data.materials.new(name=TEMPERATURE_MATERIAL_NAME)
        return material

    @staticmethod
    def _assign_material(obj: Object, material: Material) -> None:
        """ Ensures material occupies slot 0 on obj which
        renders by default, since faces default to material_index 0.
        """
        # TODO: Make this non-destructive.
        if len(obj.data.materials) == 0:
            obj.data.materials.append(material)
        else:
            obj.data.materials[0] = material



class FitDisplaySpanOperator(Operator):
    """ Sets the display span to the range of the baked temperature field.

    Equivalent to a camera's automatic gain: convenient for finding something,
    useless for comparing two images. Affects false colour only - a raw render
    is unchanged either way.
    """
    bl_idname = Labels.FIT_DISPLAY_SPAN.value
    bl_label = "Fit Span to Scene"
    bl_description = (
        "Set the display span to the coldest and hottest baked temperatures "
        "in the scene. Display only"
    )
    bl_options = {'REGISTER', 'UNDO'}

    # Half-width applied when every baked value is identical, so the span stays
    # non-empty.
    _DEGENERATE_PAD_K = 0.5

    def execute(self, context):
        objects = FitDisplaySpanOperator._baked_mesh_objects(context)
        if not objects:
            self.report({'WARNING'}, "No baked temperature data found, run Bake first")
            return {'CANCELLED'}

        combined = np.concatenate([FitDisplaySpanOperator._read_temperature_values(obj)
                                   for obj in objects])
        min_k, max_k = float(combined.min()), float(combined.max())

        if max_k - min_k < 1e-3:
            min_k -= FitDisplaySpanOperator._DEGENERATE_PAD_K
            max_k += FitDisplaySpanOperator._DEGENERATE_PAD_K

        settings = context.scene.thermal_render
        unit = TempUnit[settings.span_unit]
        settings.span_min = Conversions.from_kelvin(min_k, unit)
        settings.span_max = Conversions.from_kelvin(max_k, unit)

        self.report(
            {'INFO'},
            f"Span set to {settings.span_min:.1f} - {settings.span_max:.1f} "
            f"{unit.value}. Rebuild the material to apply."
        )
        return {'FINISHED'}

    @staticmethod
    def _read_temperature_values(obj: Object) -> Optional[np.ndarray]:
        """ Reads TEMPERATURE_ATTR_NAME off obj's mesh, or None if unbaked. """
        attribute = obj.data.attributes.get(TEMPERATURE_ATTR_NAME)
        if attribute is None:
            return None
        values = np.empty(len(obj.data.vertices), dtype=np.float64)
        attribute.data.foreach_get('value', values)
        return values

    @staticmethod
    def _baked_mesh_objects(context) -> List[Object]:
        """ Every mesh object in the scene carrying baked temperature data. """
        return [
            obj for obj in context.scene.objects
            if obj.type == 'MESH' and obj.data.attributes.get(TEMPERATURE_ATTR_NAME) is not None
        ]


class ShowColorBarOperator(Operator):
    bl_idname = Labels.SHOW_COLOR_BAR.value
    bl_label = "Show Color Bar"
    bl_description = (
        "Show the currently hidden color bar, adapting to the visualization range"
    )
    def execute(self, context):
        settings = context.scene.thermal_render

        left_bottom_color_bar.show()
        left_bottom_color_bar.update(value_range=(
            settings.span_min,
            settings.span_max
        ))
        return {'FINISHED'}

class HideColorBarOperator(Operator):
    bl_idname = Labels.HIDE_COLOR_BAR.value
    bl_label = "Hide Color Bar"
    bl_description = (
        "Hide the currently displayed color bar"
    )
    def execute(self, context):
        left_bottom_color_bar.hide()
        return {'FINISHED'}
