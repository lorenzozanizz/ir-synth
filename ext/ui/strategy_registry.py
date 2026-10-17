""" Generic registry of strategy descriptors, shared by every per-vertex quantity that resolves
 through Object -> Collection -> Scene (temperature and emissivity for now )
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import ClassVar, Dict, Tuple, Type

from bpy.types import PropertyGroup, UILayout

from ..thermal_core.contracts import SpecScope
from ..thermal_core.specs import SpecBase


class StrategyDescriptor(ABC):
    """ Everything needed to work with one strategy: how to draw its parameters, and
    how to build the pure spec from them.

    :param property_group: the bpy PropertyGroup class holding its parameters
    :param attr_name: attribute name of that group on the owning
        strategy PropertyGroup
    """
    property_group: Type[PropertyGroup]
    attr_name: str

    @staticmethod
    @abstractmethod
    def draw(ui_layout: UILayout, props: PropertyGroup) -> None:
        pass

    @staticmethod
    @abstractmethod
    def build(props: PropertyGroup) -> SpecBase:
        pass


class StrategyRegistryBase:
    """ Maps the members of one strategy enum to their descriptors.
    """

    type_enum: ClassVar[Type[Enum]]
    _REGISTRY: ClassVar[Dict[Enum, Type[StrategyDescriptor]]]

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        # A new table per subclass. Without this, all subclasses would share
        # one inherited dictionary.
        cls._REGISTRY = {}

    @classmethod
    def register(cls, strategy_type: Enum):
        """ Class decorator: register a descriptor for strategy_type """
        if not isinstance(strategy_type, cls.type_enum):
            raise TypeError(
                f"{cls.__name__} registers {cls.type_enum.__name__} members, "
                f"got {strategy_type!r}"
            )
        if strategy_type is cls.type_enum.INHERIT:
            raise ValueError("INHERIT cannot have a StrategyDescriptor")

        def decorator(descriptor_cls: Type[StrategyDescriptor]) -> Type[StrategyDescriptor]:
            cls._REGISTRY[strategy_type] = descriptor_cls
            return descriptor_cls
        return decorator

    @classmethod
    def get_strategy(cls, strategy_type: Enum) -> Type[StrategyDescriptor]:
        """ Look up the descriptor for a strategy.

        :raises ValueError: strategy_type is INHERIT
        :raises NotImplementedError: no descriptor is registered yet.
        """
        if strategy_type is cls.type_enum.INHERIT:
            raise ValueError(
                "INHERIT has no StrategyDescriptor of its own it must be "
                "resolved to a concrete strategy first."
            )
        try:
            return cls._REGISTRY[strategy_type]
        except KeyError:
            raise NotImplementedError(
                f"{strategy_type!r} is defined in {cls.type_enum.__name__} but has no "
                f"StrategyDescriptor registered yet."
            ) from None

    @classmethod
    def strategies_for_scope(cls, scope: SpecScope) -> Tuple[Type[StrategyDescriptor], ...]:
        """ Return the descriptors that are both implemented and legal at the
        given scope, per type_enum.allowed_for_scope().

        :param scope: the scope to look up the strategies for.
        """
        allowed = set(cls.type_enum.allowed_for_scope(scope))
        return tuple(
            descriptor for strategy_type, descriptor in cls._REGISTRY.items()
            if strategy_type in allowed
        )
