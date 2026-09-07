"""
Operators that edit the scene's operation stack: add, remove, reorder,
duplicate, and the object-slot editing inside an operation's scope.
"""

from bpy.types import Operator, PropertyGroup
from bpy.props import EnumProperty, IntProperty, StringProperty

from .names import Labels
from ..thermal_core.contracts import OpType
from ..ui.op_registry import OperationRegistry


def copy_property_group(source: PropertyGroup, target: PropertyGroup) -> None:
    """ Recursively copy every writable property from source onto target.

    Blender offers no deep copy for PropertyGroups, so duplication walks the
    RNA definition. Collections are cleared and rebuilt so the copy does not
    inherit stale entries.
    """
    for prop in source.bl_rna.properties:
        if prop.identifier == "rna_type" or prop.is_readonly:
            continue

        name = prop.identifier
        value = getattr(source, name)

        if prop.type == 'COLLECTION':
            destination = getattr(target, name)
            while len(destination):
                destination.remove(0)
            for item in value:
                copy_property_group(item, destination.add())
        elif prop.type == 'POINTER':
            # An ID pointer (Object, Collection) is assigned directly; a
            # nested PropertyGroup is recursed into.
            if isinstance(value, PropertyGroup):
                copy_property_group(value, getattr(target, name))
            else:
                setattr(target, name, value)
        else:
            setattr(target, name, value)


class StackAddressing:
    """ Shared index resolution for every operator in this module. """

    @staticmethod
    def entries(context):
        """ Get the entries for a stack """
        return context.scene.thermal_stack.entries

    @staticmethod
    def entry(context, index: int):
        """ Returns the entry at index, or None if out of range. """
        entries = StackAddressing.entries(context)
        return entries[index] if 0 <= index < len(entries) else None

    @staticmethod
    def scope(context, index: int, scope_path: str):
        """ One OpScopeProperties inside an entry.

        :param scope_path: attribute name of the scope on the operation's own
            property group. Named rather than assumed because a scene-level
            operation may carry several ("source", "receiver").
        :return: the scope, or None if the entry or attribute is missing.
        """
        entry = StackAddressing.entry(context, index)
        if entry is None:
            return None
        try:
            return getattr(OperationRegistry.properties_for(entry), scope_path)
        except (NotImplementedError, AttributeError):
            return None


class AddOperationOperator(Operator):
    """ Append an operation of the chosen type to the end of the stack. """
    bl_idname = Labels.OP_STACK_ADD.value
    bl_label = "Add Operation"
    bl_description = "Add a field operation to the end of the scene's stack"
    bl_options = {'REGISTER', 'UNDO'}

    op_type: EnumProperty(                                              # type: ignore
        name="Type",
        items=[(m.name, m.value, "") for m in OpType],
        default=OpType.CLAMP.name,
    )
    # Set by the per-object shortcut, which scopes the new operation to one
    # object rather than to everything.
    target_object: StringProperty(default="")                           # type: ignore
    scope_path: StringProperty(default="scope")                         # type: ignore

    def execute(self, context):
        """ Add a scene level operation to the scene. The operation will require
        further configuration. """
        op_type = OpType[self.op_type]
        try:
            descriptor = OperationRegistry.get(op_type)
        except NotImplementedError:
            self.report({'ERROR'}, f"{op_type.value} has no implementation yet")
            return {'CANCELLED'}

        entry = StackAddressing.entries(context).add()
        entry.op_type = self.op_type
        entry.name = descriptor.label
        entry.expanded = True

        if self.target_object:
            self._scope_to_object(context, entry)

        return {'FINISHED'}

    def _scope_to_object(self, context, entry) -> None:
        """ Point the new operation's scope at a single named object. """
        obj = context.scene.objects.get(self.target_object)
        if obj is None:
            return
        scope = getattr(OperationRegistry.properties_for(entry), self.scope_path, None)
        if scope is None:
            return
        scope.mode = 'OBJECTS'
        scope.objects.add().target = obj


class RemoveOperationOperator(Operator):
    """ Delete one entry from the stack. """
    bl_idname = Labels.OP_STACK_REMOVE.value
    bl_label = "Remove Operation"
    bl_description = "Delete this operation from the stack"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1)                                      # type: ignore

    def execute(self, context):
        """ Remove an operation from the stack"""
        entries = StackAddressing.entries(context)
        if not 0 <= self.index < len(entries):
            self.report({'WARNING'}, "That operation no longer exists")
            return {'CANCELLED'}
        entries.remove(self.index)
        return {'FINISHED'}


class MoveOperationOperator(Operator):
    """ Shift one entry up or down by a single position.

    Order is meaningful: it is what lets a user smooth an object before
    diffusing it onto another.
    """
    bl_idname = Labels.OP_STACK_MOVE.value
    bl_label = "Move Operation"
    bl_description = "Change where this operation runs in the stack"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1)                                      # type: ignore
    direction: IntProperty(default=-1)                                  # type: ignore

    def execute(self, context):
        """ Move an operation up or down in the stack """
        entries = StackAddressing.entries(context)
        destination = self.index + self.direction
        if not (0 <= self.index < len(entries) and 0 <= destination < len(entries)):
            return {'CANCELLED'}
        entries.move(self.index, destination)
        return {'FINISHED'}


class DuplicateOperationOperator(Operator):
    """ Insert a copy of one entry directly below it. """
    bl_idname = Labels.OP_STACK_DUPLICATE.value
    bl_label = "Duplicate Operation"
    bl_description = "Add a copy of this operation just below it"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1)                                      # type: ignore

    def execute(self, context):
        """ Duplicate an operation in the stack """
        entries = StackAddressing.entries(context)
        if not 0 <= self.index < len(entries):
            self.report({'WARNING'}, "That operation no longer exists")
            return {'CANCELLED'}

        copy_property_group(entries[self.index], entries.add())
        entries.move(len(entries) - 1, self.index + 1)
        return {'FINISHED'}


class IsolateOperationOperator(Operator):
    """ Expand one entry and collapse every other.

    A Python-defined panel column cannot be scrolled to programmatically, so
    this is how the per-object shortcut points at an operation: make it the
    only one open.
    """
    bl_idname = Labels.OP_STACK_ISOLATE.value
    bl_label = "Show Operation"
    bl_description = "Expand this operation in the stack and collapse the others"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1)                                      # type: ignore

    def execute(self, context):
        """ Expand one operation """
        entries = StackAddressing.entries(context)
        if not 0 <= self.index < len(entries):
            return {'CANCELLED'}
        for position, entry in enumerate(entries):
            entry.expanded = (position == self.index)
        return {'FINISHED'}


class AddScopeObjectOperator(Operator):
    """ Append an empty object slot to an operation's explicit scope. """
    bl_idname = Labels.OP_SCOPE_OBJECT_ADD.value
    bl_label = "Add Object"
    bl_description = "Add an object slot to this operation's selection"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1)                                      # type: ignore
    scope_path: StringProperty(default="scope")                         # type: ignore

    def execute(self, context):
        """ Add an empty object slot to an operation's explicit scope """
        scope = StackAddressing.scope(context, self.index, self.scope_path)
        if scope is None:
            return {'CANCELLED'}
        scope.objects.add()
        return {'FINISHED'}


class RemoveScopeObjectOperator(Operator):
    """ Delete one object slot from an operation's explicit scope. """
    bl_idname = Labels.OP_SCOPE_OBJECT_REMOVE.value
    bl_label = "Remove Object"
    bl_description = "Remove this object from the operation's selection"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1)                                      # type: ignore
    scope_path: StringProperty(default="scope")                         # type: ignore
    object_index: IntProperty(default=-1)                               # type: ignore

    def execute(self, context):
        """ Remove an object slot from the operation's explicit scope """
        scope = StackAddressing.scope(context, self.index, self.scope_path)
        if scope is None or not 0 <= self.object_index < len(scope.objects):
            return {'CANCELLED'}
        scope.objects.remove(self.object_index)
        return {'FINISHED'}
