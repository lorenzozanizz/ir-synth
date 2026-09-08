"""
Builds a radiometric transfer as a Cycles/EEVEE node chain.

A descriptor takes an input socket carrying Kelvin and returns an output
socket carrying signal. This is supposed to be general to allow different transfers
depending on camera model / realism etc...
"""

from abc import ABC, abstractmethod
from typing import Dict, Tuple, Type

from bpy.types import NodeSocket, PropertyGroup, ShaderNodeTree, UILayout

from ..physical_constants import UNDERFLOW_GUARD, MAX_EXPONENT_ARGUMENT
from ..thermal_core.contracts import TransferType
from ..thermal_core.radiometry import (
    MIN_TRANSFER_TEMPERATURE_K, RBFOTransferSpec, TransferSpec, WienTransferSpec,
)
from .nodes import MathCompositor
from .properties import RBFOTransferProperties, WienTransferProperties



class TransferDescriptor(ABC):
    """ Everything needed to work with one transfer at the bpy layer.

    :param transfer_type: the TransferType this descriptor implements.
    :param property_group: PropertyGroup class holding its parameters.
    :param attr_name: attribute name the group lives under on the settings
        group that owns it.
    """
    transfer_type: TransferType
    property_group: Type[PropertyGroup]
    attr_name: str

    @staticmethod
    @abstractmethod
    def draw(layout: UILayout, props: PropertyGroup) -> None:
        pass

    @staticmethod
    @abstractmethod
    def build_spec(props: PropertyGroup) -> TransferSpec:
        pass

    @staticmethod
    @abstractmethod
    def build_nodes(
        tree: ShaderNodeTree,
        temperature_socket: NodeSocket,
        props: PropertyGroup,
        location: Tuple[float, float],
    ) -> NodeSocket:
        """ Append this transfer's nodes to tree and return the socket carrying
        the resulting transformed signal (a function of a raw temperature map across the scene).

        :param tree: node tree to append into.
        :param temperature_socket: input socket supplying Kelvin temperature map.
        :param props: parameter group for this transfer.
        :param location: top-left position for the generated chain (for visual inspection).
        """
        pass


class TransferNodeRegistry:
    """ Maps a TransferType to its TransferDescriptor.
    Keyed on the TransferType enum.
    """

    _REGISTRY: Dict[TransferType, Type[TransferDescriptor]] = {}

    @classmethod
    def register(cls, transfer_type: TransferType):
        def decorator(descriptor: Type[TransferDescriptor]) -> Type[TransferDescriptor]:
            cls._REGISTRY[transfer_type] = descriptor
            return descriptor
        return decorator

    @staticmethod
    def get(transfer_type: TransferType) -> Type[TransferDescriptor]:
        """ Look up a descriptor.

        :raises NotImplementedError: if transfer_type is declared in TransferType
            but has no descriptor yet.
        """
        try:
            return TransferNodeRegistry._REGISTRY[transfer_type]
        except KeyError:
            raise NotImplementedError(
                f"{transfer_type!r} has no TransferDescriptor registered yet."
            ) from None

    @staticmethod
    def implemented() -> Tuple[Type[TransferDescriptor], ...]:
        """ Descriptors with a working implementation for populating the UI. """
        return tuple(TransferNodeRegistry._REGISTRY.values()) # type: ignore
        # ^ I dont know why the IDE highlights this wrong.

    @staticmethod
    def is_implemented(transfer_type: TransferType) -> bool:
        return transfer_type in TransferNodeRegistry._REGISTRY


@TransferNodeRegistry.register(TransferType.RBFO)
class RBFOTransfer(TransferDescriptor):
    """ S = R / (exp(B/T) - F) + O, as seven Math nodes.

    Every operation is GPU-native in both Cycles and EEVEE, and the parameters
    stay live-editable without regenerating the tree.
    """

    transfer_type = TransferType.RBFO
    property_group = RBFOTransferProperties
    attr_name = "rbfo"

    @staticmethod
    def draw(layout: UILayout, props: RBFOTransferProperties) -> None:
        column = layout.column(align=True)
        column.prop(props, "r")
        column.prop(props, "b")
        column.prop(props, "f")
        column.prop(props, "o")

    @staticmethod
    def build_spec(props: RBFOTransferProperties) -> RBFOTransferSpec:
        return RBFOTransferSpec(r=props.r, b=props.b, f=props.f, o=props.o)

    @staticmethod
    def build_nodes(
        tree: ShaderNodeTree,
        temperature_socket: NodeSocket,
        props: RBFOTransferProperties,
        location: Tuple[float, float],
    ) -> NodeSocket:
        chain = MathCompositor(tree, location, temperature_socket)

        # Guard the division, matching the clamp the numpy evaluator applies.
        chain.step('MAXIMUM', MIN_TRANSFER_TEMPERATURE_K, label="Clamp T")
        # B / T, with B in input 0.
        chain.step('DIVIDE', props.b, socket_index=1, label="B / T")
        # this applies min(const, exponent)
        chain.step('MINIMUM', MAX_EXPONENT_ARGUMENT, label="Clamp exponent")
        chain.step_unary('EXPONENT', label="exp")
        chain.step('SUBTRACT', props.f, socket_index=0, label="- F")
        # F > 1 admits a zero denominator so keep it one-sided.
        # this takes max(F, 1e-6) to avoid underflow of the denominator
        chain.step('MAXIMUM', UNDERFLOW_GUARD, label="Guard denominator")
        # R / denominator, with R in input 0.
        chain.step('DIVIDE', props.r, socket_index=1, label="R / denom")
        return chain.step('ADD', props.o, socket_index=0, label="+ O")


@TransferNodeRegistry.register(TransferType.WIEN)
class WienTransfer(TransferDescriptor):
    """ S = R * exp(-B/T) + O, as four Math nodes.

    The Wien approximation of the narrow-band Planck form.
    """

    transfer_type = TransferType.WIEN
    property_group = WienTransferProperties
    attr_name = "wien"

    @staticmethod
    def draw(layout: UILayout, props: WienTransferProperties) -> None:
        column = layout.column(align=True)
        column.prop(props, "r")
        column.prop(props, "b")
        column.prop(props, "o")

    @staticmethod
    def build_spec(props: WienTransferProperties) -> WienTransferSpec:
        return WienTransferSpec(r=props.r, b=props.b, o=props.o)

    @staticmethod
    def build_nodes(
        tree: ShaderNodeTree,
        temperature_socket: NodeSocket,
        props: WienTransferProperties,
        location: Tuple[float, float],
    ) -> NodeSocket:
        chain = MathCompositor(tree, location, temperature_socket)

        # Guard the division, matching the clamp the numpy evaluator applies.
        chain.step('MAXIMUM', MIN_TRANSFER_TEMPERATURE_K, label="Clamp T")
        # B / T, with B in input 0.
        chain.step('DIVIDE', props.b, socket_index=1, label="B / T")
        # Negate before exponentiating: exp(-B/T).
        chain.step('MULTIPLY', -1.0, label="- B / T")
        chain.step_unary('EXPONENT', label="exp")
        # R * exp(-B/T), with R in input 0.
        chain.step('MULTIPLY', props.r, socket_index=0, label="R * exp")
        return chain.step('ADD', props.o, socket_index=0, label="+ O")