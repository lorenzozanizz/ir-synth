""" Central mapping from EnvironmentSpecType -> everything needed to draw
one entry of the scene's environmental-factor stack: its property group
class and the attribute it lives under on EnvironmentFactorItem.

"""

from abc import ABC, abstractmethod
from typing import Optional
from bpy.types import PropertyGroup, UILayout
import bpy

from ..thermal_core.contracts import EnvironmentSpecType, InitType
from ..thermal_core.specs import (
    EnvironmentFactorSpec, AmbientTemperatureSpec, DefaultInitializationSpec,
)
from ..thermal_core.temperature import TempUnit, Conversions
from .properties import (
    EnvironmentAmbientTemperatureProperties, EnvironmentDefaultInitProperties,
)


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



@EnvironmentFactorRegistry.register(factor_type=EnvironmentSpecType.DEFAULT_INITIALIZATION)
class DefaultInitializationDescriptor(EnvironmentFactorDescriptor):
    """ The scene-wide fallback initialization strategy.

    Draws and builds by delegating to InitStrategyRegistry, so any strategy
    legal at SpecScope.SCENE works here without a second implementation.
    """

    factor_type = EnvironmentSpecType.DEFAULT_INITIALIZATION
    property_group = EnvironmentDefaultInitProperties
    attr_name = "default_initialization"

    @staticmethod
    def draw(layout: UILayout, props: EnvironmentDefaultInitProperties) -> None:
        # Imported here: init_registry imports this module, so a module-level
        # import would be circular.
        from .init_registry import InitStrategyRegistry

        strategy_props = props.init
        layout.prop(strategy_props, "init_type")

        init_type = InitType[strategy_props.init_type]
        try:
            descriptor = InitStrategyRegistry.get_strategy(init_type)
        except NotImplementedError:
            layout.label(text=f'"{init_type.value}" is not implemented yet', icon='ERROR')
            return
        descriptor.draw(layout, getattr(strategy_props, descriptor.attr_name))

    @staticmethod
    def build(props: EnvironmentDefaultInitProperties) -> DefaultInitializationSpec:
        from .init_registry import InitStrategyRegistry

        strategy_props = props.init
        descriptor = InitStrategyRegistry.get_strategy(InitType[strategy_props.init_type])
        return DefaultInitializationSpec(
            init_spec=descriptor.build(getattr(strategy_props, descriptor.attr_name))
        )


class EnvSearch:
    """ Lookup of a configured factor on the active scene's factor stack. """

    @staticmethod
    def find(spec_type: EnvironmentSpecType):
        """ The (descriptor, live props) pair for a configured factor, or None
        if the scene has no entry of that type. """
        for item in bpy.context.scene.thermal_environment.factors:
            if EnvironmentSpecType[item.factor_type] is not spec_type:
                continue
            descriptor = EnvironmentFactorRegistry.get(spec_type)
            return descriptor, getattr(item, descriptor.attr_name)
        return None

    @staticmethod
    def build(spec_type: EnvironmentSpecType) -> Optional[EnvironmentFactorSpec]:
        """ The built spec for a configured factor, or None if absent. """
        found = EnvSearch.find(spec_type)
        if found is None:
            return None
        descriptor, props = found
        return descriptor.build(props)
