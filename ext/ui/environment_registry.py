""" Central mapping from EnvironmentSpecType -> everything needed to draw
one entry of the scene's environmental-factor stack: its property group
class and the attribute it lives under on EnvironmentFactorItem.

"""

from abc import ABC, abstractmethod
from typing import Optional
from bpy.types import PropertyGroup, UILayout
import bpy

from ..thermal_core.contracts import EnvironmentSpecType
from ..thermal_core.specs import EnvironmentFactorSpec, AmbientTemperatureSpec
from ..thermal_core.temperature import TempUnit, Conversions
from .properties import EnvironmentAmbientTemperatureProperties


class EnvironmentFactorDescriptor(ABC):
    """ Everything needed to work with one environmental factor: how to draw
    it, and how to convert its live bpy state into the pure spec dataclass
    consumed on the other side of the conversion boundary.

    :param factor_type: the EnvironmentSpecType this descriptor implements.
    :param property_group: the bpy PropertyGroup class holding this
        factor's parameters.
    :param attr_name: attribute name on EnvironmentFactorItem holding this
        factor's PointerProperty.
    """
    factor_type: EnvironmentSpecType
    property_group: type
    attr_name: str

    @staticmethod
    @abstractmethod
    def draw(ui_layout: UILayout, props: PropertyGroup) -> None:
        pass

    @staticmethod
    @abstractmethod
    def build(props: PropertyGroup) -> EnvironmentFactorSpec:
        pass


class EnvironmentFactorRegistry:

    _REGISTRY = {}

    @staticmethod
    def get(factor_type: EnvironmentSpecType) -> "EnvironmentFactorDescriptor":
        """ Look up the descriptor for a factor. """
        try:
            return EnvironmentFactorRegistry._REGISTRY[factor_type]
        except KeyError:
            raise NotImplementedError(
                f"{factor_type!r} is defined in EnvironmentSpecType but has "
                f"no EnvironmentFactorDescriptor registered yet."
            ) from None

    @classmethod
    def register(cls, factor_type: EnvironmentSpecType):
        def decorator(descriptor_cls):
            cls._REGISTRY[factor_type] = descriptor_cls
            return descriptor_cls
        return decorator


@EnvironmentFactorRegistry.register(factor_type=EnvironmentSpecType.AMBIENT_TEMPERATURE)
class AmbientTemperatureDescriptor(EnvironmentFactorDescriptor):

    factor_type = EnvironmentSpecType.AMBIENT_TEMPERATURE
    property_group = EnvironmentAmbientTemperatureProperties
    attr_name = "ambient_temperature"

    @staticmethod
    def draw(layout: UILayout, props: EnvironmentAmbientTemperatureProperties) -> None:
        layout.prop(props, "value")
        layout.prop(props, "unit")

    @staticmethod
    def build(props: EnvironmentAmbientTemperatureProperties) -> AmbientTemperatureSpec:
        unit = TempUnit[props.unit]
        return AmbientTemperatureSpec(value_k=Conversions.to_kelvin(props.value, unit))


class EnvSearch:

    @staticmethod
    def search(spec_type: EnvironmentSpecType) -> Optional[EnvironmentFactorDescriptor]:
        """ Search for the existence of a configuration in the environment properties """
        for item in bpy.context.scene.thermal_environment.factors:
            if EnvironmentSpecType[item.factor_type] is not spec_type:
                continue
            descriptor = EnvironmentFactorRegistry.get(spec_type)
            return descriptor
        return None