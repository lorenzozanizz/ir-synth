"""
A mapping repository which from the OpType enum gives everything needed for that
operation to be displayed in the UI ( a propertygroup, its attribute in a thermal op entry
[ see the comment there ] and its draw(9 and build() function )
"""

from abc import ABC, abstractmethod
from dataclasses import replace
from typing import Tuple, Type

from bpy.types import PropertyGroup, UILayout

from ..thermal_core.contracts import OpType, ScopeMode
from ..thermal_core.operations import (
    ClampOp, ContactDiffusionOp, FieldOperation, SmoothOp,
)
from .op_properties import (
    ClampOpProperties, ContactDiffusionOpProperties, OpScopeProperties,
    SmoothOpProperties, ThermalOpEntry,
)


def draw_scope(
    layout: UILayout,
    scope: OpScopeProperties,
    entry_index: int,
    scope_path: str = "scope",
    label: str = "Scope",
) -> None:
    """ Draw one scope block.

    Shared by every descriptor so selection looks identical regardless of how
    many scopes an operation carries.

    :param entry_index: position of the owning entry in the stack. The slot
        operators address their target by index, so they need it.
    :param scope_path: attribute name of this scope on the operation's own
        property group, so a two-scope operation can tell its blocks apart.
    """
    from ..operators.names import Labels

    column = layout.column(align=True)
    column.prop(scope, "mode", text=label)

    mode = ScopeMode[scope.mode]
    if mode is ScopeMode.COLLECTION:
        column.prop(scope, "collection", text="")
        if not scope.collection:
            column.label(text="No collection set", icon='ERROR')

    elif mode is ScopeMode.OBJECTS:
        for object_index, ref in enumerate(scope.objects):
            row = column.row(align=True)
            row.prop(ref, "target", text="")
            remove = row.operator(
                Labels.OP_SCOPE_OBJECT_REMOVE.value, text="", icon='X',
            )
            remove.index = entry_index
            remove.scope_path = scope_path
            remove.object_index = object_index

        add = column.operator(
            Labels.OP_SCOPE_OBJECT_ADD.value, text="Add Object", icon='ADD',
        )
        add.index = entry_index
        add.scope_path = scope_path

        if not len(scope.objects):
            column.label(text="No objects selected", icon='ERROR')


class OperationDescriptor(ABC):
    """ Everything needed to work with one field operation.

    :param op_type: the OpType this descriptor implements.
    :param property_group: PropertyGroup holding this operation's parameters.
    :param attr_name: attribute name on ThermalOpEntry.
    :param label: name shown in the Add menu and as the default entry name.
    :param category: Add menu grouping.
    :param icon: Blender icon identifier for the Add menu.
    """
    op_type: OpType
    property_group: Type[PropertyGroup]
    attr_name: str
    label: str
    category: str = "Filters"

    # Has to be a valid oen from
    # https://docs.blender.org/manual/en/latest/contribute/manual/guides/icons.html
    icon: str = 'MODIFIER'

    @staticmethod
    @abstractmethod
    def draw(layout: UILayout, props: PropertyGroup, entry_index: int) -> None:
        """ Draw this operation's parameters.

        :param entry_index: position of the owning entry, needed by draw_scope
            so its buttons can address the right entry.
        """
        pass

    @staticmethod
    @abstractmethod
    def build(props: PropertyGroup) -> FieldOperation:
        """ Build the operation from its own parameters only.

        enabled and seed live on ThermalOpEntry and are applied by
        OperationRegistry.build_entry, so no descriptor has to handle them.
        """
        pass


class OperationRegistry:

    _REGISTRY = {}

    @staticmethod
    def get(op_type: OpType) -> OperationDescriptor:
        """ :raises NotImplementedError: op_type has no descriptor yet. """
        try:
            return OperationRegistry._REGISTRY[op_type]
        except KeyError:
            raise NotImplementedError(
                f"{op_type!r} is defined in OpType but has no "
                f"OperationDescriptor registered yet."
            ) from None

    @staticmethod
    def implemented() -> Tuple[OperationDescriptor, ...]:
        """ Every registered descriptor. This is what the Add menu iterates,
        so registering a descriptor is all it takes to appear there.
        """
        return tuple(OperationRegistry._REGISTRY.values())

    @staticmethod
    def properties_for(entry: ThermalOpEntry) -> PropertyGroup:
        """ The parameter group matching an entry's op_type. """
        descriptor = OperationRegistry.get(OpType[entry.op_type])
        return getattr(entry, descriptor.attr_name)

    @staticmethod
    def draw_entry(layout: UILayout, entry: ThermalOpEntry, entry_index: int) -> None:
        """ Draw one entry's parameters.

        :raises NotImplementedError: the entry's op_type has no descriptor.
        """
        descriptor = OperationRegistry.get(OpType[entry.op_type])
        descriptor.draw(layout, getattr(entry, descriptor.attr_name), entry_index)

    @staticmethod
    def describe_entry(entry: ThermalOpEntry) -> str:
        """ Short summary for an entry's panel header.

        Never raises: a header must draw even when the entry is half-configured
        or names an unimplemented type.
        """
        try:
            return OperationRegistry.build_entry(entry).describe()
        except (NotImplementedError, ValueError):
            return OpType[entry.op_type].value

    @staticmethod
    def build_entry(entry: ThermalOpEntry) -> FieldOperation:
        """ Build the pure operation for one stack entry.

        :raises NotImplementedError: the entry's op_type has no descriptor.
        """
        descriptor = OperationRegistry.get(OpType[entry.op_type])
        operation = descriptor.build(getattr(entry, descriptor.attr_name))
        return replace(operation, enabled=entry.enabled, seed=entry.seed)

    @staticmethod
    def build_stack(stack) -> Tuple[FieldOperation, ...]:
        """ Build every entry in a ThermalStackProperties, in order.

        Entries whose op_type has no descriptor are skipped rather than
        raising, matching how unimplemented init strategies are handled.
        """
        operations = []
        for entry in stack.entries:
            try:
                operations.append(OperationRegistry.build_entry(entry))
            except NotImplementedError:
                continue
        return tuple(operations)

    @classmethod
    def register(cls, op_type: OpType):
        def decorator(descriptor_cls):
            cls._REGISTRY[op_type] = descriptor_cls
            return descriptor_cls
        return decorator


@OperationRegistry.register(op_type=OpType.CLAMP)
class ClampDescriptor(OperationDescriptor):

    op_type = OpType.CLAMP
    property_group = ClampOpProperties
    attr_name = "clamp"
    label = "Clamp"
    category = "Filters"
    icon = 'CON_CLAMPTO'

    @staticmethod
    def draw(layout: UILayout, props: ClampOpProperties, entry_index: int) -> None:
        draw_scope(layout, props.scope, entry_index)
        column = layout.column(align=True)
        column.prop(props, "min_value")
        column.prop(props, "max_value")
        column.prop(props, "unit")

    @staticmethod
    def build(props: ClampOpProperties) -> ClampOp:
        return ClampOp(
            scope=props.scope.to_spec(),
            min_k=props.min_k(),
            max_k=props.max_k(),
        )


@OperationRegistry.register(op_type=OpType.SMOOTH)
class SmoothDescriptor(OperationDescriptor):

    op_type = OpType.SMOOTH
    property_group = SmoothOpProperties
    attr_name = "smooth"
    label = "Smooth"
    category = "Filters"
    icon = 'MOD_SMOOTH'

    @staticmethod
    def draw(layout: UILayout, props: SmoothOpProperties, entry_index: int) -> None:
        draw_scope(layout, props.scope, entry_index)
        column = layout.column(align=True)
        column.prop(props, "iterations")
        column.prop(props, "factor")

    @staticmethod
    def build(props: SmoothOpProperties) -> SmoothOp:
        return SmoothOp(
            scope=props.scope.to_spec(),
            iterations=props.iterations,
            factor=props.factor,
        )


@OperationRegistry.register(op_type=OpType.CONTACT_DIFFUSION)
class ContactDiffusionDescriptor(OperationDescriptor):
    """ The two-scope case. draw_scope is called twice with different
    scope_path values so each block's buttons address the right one.
    """

    op_type = OpType.CONTACT_DIFFUSION
    property_group = ContactDiffusionOpProperties
    attr_name = "contact_diffusion"
    label = "Contact Diffusion"
    category = "Coupling"
    icon = 'MOD_SOFT'

    @staticmethod
    def draw(layout: UILayout, props: ContactDiffusionOpProperties, entry_index: int) -> None:
        draw_scope(layout, props.source, entry_index, "source", label="Sources")
        layout.separator()
        draw_scope(layout, props.receiver, entry_index, "receiver", label="Receivers")
        layout.separator()

        column = layout.column(align=True)
        column.prop(props, "radius")
        column.prop(props, "strength")
        column.prop(props, "falloff")

    @staticmethod
    def build(props: ContactDiffusionOpProperties) -> ContactDiffusionOp:
        return ContactDiffusionOp(
            source=props.source.to_spec(),
            receiver=props.receiver.to_spec(),
            radius=props.radius,
            strength=props.strength,
            falloff=props.falloff,
        )
