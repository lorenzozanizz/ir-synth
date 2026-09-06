"""
The Field Operations panel: a vertical column of collapsible sub-panels, one
per stack entry, in the style of Blender's modifier stack.

Expansion state is stored on each entry via layout.panel_prop rather than
keyed on an idname by Blender, so it travels with the entry when the stack is
reordered instead of staying attached to a position.
"""

from bpy.types import Menu, Panel, Context

from ..constants import MAIN_PANEL_NAME
from ..operators.names import Labels
from ..thermal_core.contracts import OpType
from .op_registry import OperationRegistry


class AddOperationMenu(Menu):
    """ Every registered operation, grouped by category.

    Built from OperationRegistry.implemented(), so registering a descriptor is
    all it takes for an operation to appear here.
    """
    bl_idname = Labels.ADD_OPERATION_MENU_.value
    bl_label = "Add Operation"

    def draw(self, context: Context) -> None:
        layout = self.layout

        by_category = {}
        for descriptor in OperationRegistry.implemented():
            by_category.setdefault(descriptor.category, []).append(descriptor)

        for position, (category, descriptors) in enumerate(sorted(by_category.items())):
            if position:
                layout.separator()
            layout.label(text=category)
            for descriptor in descriptors:
                entry = layout.operator(
                    Labels.OP_STACK_ADD.value,
                    text=descriptor.label,
                    icon=descriptor.icon,
                )
                entry.op_type = descriptor.op_type.name


class OperationStackPanel(Panel):
    """ The scene's ordered operation stack.

    Scene-level rather than per-object because ordering across objects is the
    point: it is what lets a user smooth one object before diffusing it onto
    another. The per-object view in MainPanel is a filtered read of this list.
    """
    bl_idname = "THERMAL_PT_operations"
    bl_label = "Field Operations"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = MAIN_PANEL_NAME
    bl_order = 1

    def draw(self, context: Context) -> None:
        layout = self.layout
        entries = context.scene.thermal_stack.entries

        layout.menu(Labels.ADD_OPERATION_MENU_.value, text="Add Operation", icon='ADD')

        if not len(entries):
            column = layout.column(align=True)
            column.separator()
            column.label(text="No operations. The baked field is the", icon='INFO')
            column.label(text="source strategies alone.")
            return

        for index, entry in enumerate(entries):
            self._draw_entry(layout, entry, index, len(entries))

    @staticmethod
    def _draw_entry(layout, entry, index: int, total: int) -> None:
        box = layout.box()
        header, body = box.panel_prop(entry, "expanded")

        OperationStackPanel._draw_header(header, entry, index, total)

        if body is None:
            return

        try:
            OperationRegistry.draw_entry(body, entry, index)
        except NotImplementedError:
            body.label(
                text=f"{OpType[entry.op_type].value} is not implemented yet",
                icon='ERROR',
            )

    @staticmethod
    def _draw_header(header, entry, index: int, total: int) -> None:
        # Mute first: it is the control used most while debugging a stack, and
        # it is editable from the per-object view too.
        header.prop(entry, "enabled", text="")
        header.prop(entry, "name", text="", emboss=False)

        summary = header.row()
        summary.alignment = 'RIGHT'
        summary.label(text=OperationRegistry.describe_entry(entry))

        # Blender's drag handle is C-side and unavailable to Python panels, so
        # reordering is explicit buttons.
        buttons = header.row(align=True)

        up = buttons.row(align=True)
        up.enabled = index > 0
        move = up.operator(Labels.OP_STACK_MOVE.value, text="", icon='TRIA_UP', emboss=False)
        move.index, move.direction = index, -1

        down = buttons.row(align=True)
        down.enabled = index < total - 1
        move = down.operator(Labels.OP_STACK_MOVE.value, text="", icon='TRIA_DOWN', emboss=False)
        move.index, move.direction = index, 1

        duplicate = buttons.operator(
            Labels.OP_STACK_DUPLICATE.value, text="", icon='DUPLICATE', emboss=False,
        )
        duplicate.index = index

        remove = buttons.operator(
            Labels.OP_STACK_REMOVE.value, text="", icon='X', emboss=False,
        )
        remove.index = index
