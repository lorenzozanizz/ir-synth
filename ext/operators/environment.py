""" Operators backing the scene's environmental-factor stack.

"""

from bpy.types import Operator, Context
from bpy.props import EnumProperty, IntProperty

from .names import Labels
from ..thermal_core.contracts import EnvironmentSpecType


class AddEnvironmentFactorOperator(Operator):
    """ Appends one new entry to the scene's environmental-factor stack.

    """
    bl_idname = Labels.ENVIRONMENT_FACTOR_ADD.value
    bl_label = "Add Environmental Factor"
    bl_description = "Add a new environmental condition to the scene"
    bl_options = {'REGISTER', 'UNDO'}

    factor_type: EnumProperty(                                            # type: ignore
        name="Factor",
        items=[(f.name, f.value, "") for f in EnvironmentSpecType],
    )

    def execute(self, context: Context) -> set:
        """ Execute the operation adding it to the global environment """
        settings = context.scene.thermal_environment

        if any(item.factor_type == self.factor_type for item in settings.factors):
            self.report(
                {'WARNING'},
                f'"{EnvironmentSpecType[self.factor_type].value}" is already active on this scene',
            )
            return {'CANCELLED'}

        item = settings.factors.add()
        item.factor_type = self.factor_type
        settings.active_index = len(settings.factors) - 1
        return {'FINISHED'}


class RemoveEnvironmentFactorOperator(Operator):
    """ Removes one entry from the scene's environmental-factor stack. """
    bl_idname = Labels.ENVIRONMENT_FACTOR_REMOVE.value
    bl_label = "Remove Environmental Factor"
    bl_description = "Remove this environmental condition from the scene"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty()                                                  # type: ignore

    def execute(self, context: Context) -> set:
        """ Remove an operation. Checks boundary of env variable index. """
        settings = context.scene.thermal_environment
        entries = settings.factors
        if not 0 <= self.index < len(entries):
            self.report({'WARNING'}, "That operation no longer exists")
            return {'CANCELLED'}
        entries.remove(self.index)
        settings.active_index = min(settings.active_index, max(0, len(entries) - 1))
        return {'FINISHED'}
