"""
Dispatch for ShadingType: which machinery builds the material.

Mirrors InitStrategyRegistry. A ShadingType with no descriptor raises
NotImplementedError rather than silently falling back, so an unfinished path
surfaces as a clear message instead of a wrong image.
"""

from abc import ABC, abstractmethod
from typing import Dict, Tuple, Type

from bpy.types import Material, PropertyGroup, ShaderNodeTree

from ..constants import TEMPERATURE_ATTR_NAME
from ..thermal_core.contracts import ShadingType, TransferType
from ..thermal_core.radiometry import signal_span
from .emissivity import build_apparent_signal
from .nodes import TreeUtils, MathCompositor
from .terminal import build_terminal
from .transfer import TransferNodeRegistry

class ShaderDescriptor(ABC):
    """ Builds one complete material for a ShadingType. """
    shading_type: ShadingType

    @staticmethod
    @abstractmethod
    def build(material: Material, settings: PropertyGroup) -> None:
        """ Rebuild material's node tree from scratch.

        :param settings: the scene's ThermalRenderSettings.
        """


class ShaderRegistry:
    """ The registry containing the strategy to emit each shaded material /
    rendered image starting from the ideal black body emittance computed by the
    transfer. """


    _REGISTRY: Dict[ShadingType, Type[ShaderDescriptor]] = {}

    @classmethod
    def register(cls, shading_type: ShadingType):
        """ Register a shader """
        def decorator(descriptor: Type[ShaderDescriptor]) -> Type[ShaderDescriptor]:
            cls._REGISTRY[shading_type] = descriptor
            return descriptor
        return decorator

    @staticmethod
    def get(shading_type: ShadingType) -> Type[ShaderDescriptor]:
        """ :raises NotImplementedError: no descriptor for shading_type. """
        try:
            return ShaderRegistry._REGISTRY[shading_type]
        except KeyError:
            raise NotImplementedError(
                f"'{shading_type.value}' is not implemented yet."
            ) from None

    @staticmethod
    def implemented() -> Tuple[ShadingType, ...]:
        """ Obtain the implemented shaders """
        return tuple(ShaderRegistry._REGISTRY)

    @staticmethod
    def is_implemented(shading_type: ShadingType) -> bool:
        """ Check if a shader is implemented """
        return shading_type in ShaderRegistry._REGISTRY


def _prepare_tree(material: Material) -> ShaderNodeTree:
    """ Clear material's tree so building is idempotent. """
    material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    return tree



# Locations in the node editor where the builder will put the
# different sections of the shading tree.
_ATTRIBUTE_LOCATION = (-1400.0, 0.0)
_BODY_LOCATION = (-1200.0, 0.0)


@ShaderRegistry.register(ShadingType.TEMPERATURE_SHADER)
class TemperatureShader(ShaderDescriptor):
    """ Emits the baked temperature field with no radiometry.

    A diagnostic view of what was baked, not a thermal image: no transfer, no
    emissivity, no environment. Signal is Kelvin, so a Kelvin display span
    needs no conversion.
    """
    shading_type = ShadingType.TEMPERATURE_SHADER

    @staticmethod
    def build(material: Material, settings: PropertyGroup) -> None:
        """ Build the shader tree for the pure temperature shader """
        tree = _prepare_tree(material)
        temperature = TreeUtils.new_attribute(tree, TEMPERATURE_ATTR_NAME, _ATTRIBUTE_LOCATION)
        build_terminal(
            tree,
            temperature,
            settings,
            (settings.span_min_k(), settings.span_max_k()),
            _BODY_LOCATION,
        )


@ShaderRegistry.register(ShadingType.NODE_SURROGATE_REFLECTION)
class NodeShader(ShaderDescriptor):
    """ Radiometric transfer plus emissivity mix, evaluated as Cycles/EEVEE
    math nodes. No light transport: the environment enters as a constant.
    """
    shading_type = ShadingType.NODE_SURROGATE_REFLECTION

    @staticmethod
    def build(material: Material, settings: PropertyGroup) -> None:
        transfer = TransferNodeRegistry.get(TransferType[settings.transfer_type])
        props = getattr(settings, transfer.attr_name)

        x_stride, _ = MathCompositor.strides()
        spec = transfer.build_spec(props)
        spec.validate()

        tree = _prepare_tree(material)
        temperature = TreeUtils.new_attribute(tree, TEMPERATURE_ATTR_NAME, _ATTRIBUTE_LOCATION)
        signal = build_apparent_signal(
            tree, transfer, props, settings, temperature, _BODY_LOCATION,
        )
        build_terminal(
            tree,
            signal,
            settings,
            signal_span(spec, settings.span_min_k(), settings.span_max_k()),
            (signal.node.location[0] + x_stride, _BODY_LOCATION[1]),
        )
