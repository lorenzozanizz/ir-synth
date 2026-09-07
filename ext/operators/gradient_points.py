""" Operators supporting interactive editing of GradientTempSpec's two
world-space points from the 3D viewport. """

from typing import Union

import bpy
from bpy.types import Operator, Context, Object, Collection
from bpy.props import EnumProperty, StringProperty

from .names import Labels
from ..ui.gradient_gpu import gradient_overlay


class _GradientTargetMixin:
    """ Common resolution of the ID datablock (Object or Collection) that
    owns the GradientTempProperties being edited by a given button.

    Kept as a mixin rather than duplicated in both operators below, so a
    future third operator on the same points reuses the same resolution
    logic instead of re-implementing it.
    """
    target_type: str
    target_name: str

    def _resolve_target(self) -> Union[Object, Collection]:
        if self.target_type == 'OBJECT':
            return bpy.data.objects[self.target_name]
        return bpy.data.collections[self.target_name]

    def _resolve_gradient_props(self):
        return self._resolve_target().thermal_init.gradient


class SetGradientPointFromCursorOperator(_GradientTargetMixin, Operator):
    """ Obtain cursor's coordinates: copies the 3D cursor's current world
    position into Point A or Point B of a GradientTempProperties. """
    bl_idname = Labels.GRADIENT_POINT_FROM_CURSOR.value
    bl_label = "Obtain cursor's coordinates"
    bl_description = "Set this point to the 3D cursor's current world position"
    bl_options = {'REGISTER', 'UNDO'}

    target_type: EnumProperty(                                            # type: ignore
        items=[('OBJECT', "Object", ""), ('COLLECTION', "Collection", "")],
    )
    target_name: StringProperty()                                          # type: ignore
    point: EnumProperty(                                                   # type: ignore
        items=[('A', "Point A", ""), ('B', "Point B", "")],
    )

    def execute(self, context: Context) -> set:
        props = self._resolve_gradient_props()
        field_name = "point_a" if self.point == 'A' else "point_b"
        setattr(props, field_name, tuple(context.scene.cursor.location))
        return {'FINISHED'}


class VisualizeGradientPointsOperator(_GradientTargetMixin, Operator):
    """ Visualize Gradient point: toggles a 3D-viewport overlay showing
    Point A, Point B and an arrow between them pointing at the hotter
    endpoint. """
    bl_idname = Labels.VISUALIZE_GRADIENT_POINTS.value
    bl_label = "Visualize Gradient point"
    bl_description = "Show/hide Point A, Point B and the gradient direction in the viewport"

    target_type: EnumProperty(                                            # type: ignore
        items=[('OBJECT', "Object", ""), ('COLLECTION', "Collection", "")],
    )
    target_name: StringProperty()                                          # type: ignore

    def execute(self, _context: Context) -> set:
        from ..ui.init_registry import InitGradient  # local import: avoids a
                                                       # ui<->operators circular import

        props = self._resolve_gradient_props()
        spec = InitGradient.build(props)

        if gradient_overlay.is_active():
            gradient_overlay.hide()
        else:
            gradient_overlay.show(spec)
        return {'FINISHED'}
