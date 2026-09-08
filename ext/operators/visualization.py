"""
Bpy-facing orchestration for building the thermal material and assigning it to
every baked object.

The shading path is resolved from the scene's ThermalRenderSettings, so this
operator holds no knowledge of how any particular material is built.
"""

from typing import List, Optional

import bpy
import numpy as np
from bpy.types import Operator, Object, Material

from .names import Labels
from ..constants import TEMPERATURE_ATTR_NAME, TEMPERATURE_MATERIAL_NAME
from ..thermal_core.contracts import ShadingType
from ..thermal_core.temperature import Conversions, TempUnit
from ..shaders.registry import ShaderRegistry

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

        settings = context.scene.thermal_render
        shading_type = ShadingType[settings.shading_type]

        try:
            descriptor = ShaderRegistry.get(shading_type)
            material = VisualizeTemperatureOperator._get_or_create_material()
            descriptor.build(material, settings)
        except (NotImplementedError, ValueError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}

        # For now, override the current material to display the baked thermal
        # map over the scene.
        for obj in objects_iter:
            VisualizeTemperatureOperator._assign_material(obj, material)


        self.report(
            {'INFO'},
            f"Built '{shading_type.value}' on {len(objects_iter)} object(s). Switch "
            f"viewport shading to Material Preview or Rendered to see it."
        )
        return {'FINISHED'}

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
