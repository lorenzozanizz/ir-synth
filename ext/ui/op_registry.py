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
from ..thermal_core.operations import ClampOp, FieldOperation
from .op_properties import ClampOpProperties, OpScopeProperties, ThermalOpEntry


class OperationsWidget:

    @staticmethod
    def draw_scope(layout: UILayout, scope: OpScopeProperties, label: str = "Scope") -> None:
        """ Draw one scope block. Shared by every descriptor so the selection
        controls look identical regardless of how many scopes an operation has.
        """
        column = layout.column(align=True)
        column.prop(scope, "mode", text=label)

        mode = ScopeMode[scope.mode]
        if mode is ScopeMode.COLLECTION:
            column.prop(scope, "collection", text="")
        elif mode is ScopeMode.OBJECTS:
            for index, ref in enumerate(scope.objects):
                row = column.row(align=True)
                row.prop(ref, "target", text="")
                # Remove/add buttons are wired in phase 5, once the operators exist.
            if not len(scope.objects):
                column.label(text="No objects selected", icon='ERROR')


class OperationDescriptor(ABC):
    """ Everything needed to work with one field operation

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
    def draw(layout: UILayout, props: PropertyGroup) -> None:
        pass

    @staticmethod
    @abstractmethod
    def build(props: PropertyGroup) -> FieldOperation:
        """ Build the operation from its own parameters only.
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
    def draw_entry(layout: UILayout, entry: ThermalOpEntry) -> None:
        """ Draw one entry's parameters. """
        descriptor = OperationRegistry.get(OpType[entry.op_type])
        descriptor.draw(layout, getattr(entry, descriptor.attr_name))

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
    def draw(layout: UILayout, props: ClampOpProperties) -> None:
        OperationsWidget.draw_scope(layout, props.scope)
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
