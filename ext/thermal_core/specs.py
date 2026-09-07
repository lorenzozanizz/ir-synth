"""
Pure data contracts describing how an object's/collection's initial
temperature field is specified.

"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Dict, Optional, Type, Tuple, Union

from .temperature import Conversions
from .contracts import InitType, EnvironmentSpecType


@dataclass(frozen=True)
class TempInitSpec(ABC):
    """ Base class for a single temperature-initialization strategy.

    Concrete subclasses correspond 1:1 with an `ObjectTempInitType` member
    (excluding INHERIT, which is a resolution-time concept, not a spec - by
    the time a TempInitSpec exists, inheritance has already been resolved to
    a concrete strategy).
    """

    # Every concrete subclass, keyed by class name. Populated automatically on
    # subclass definition and used by SceneThermalConfig to rebuild a spec from
    # a serialized dict.
    _SUBCLASSES: ClassVar[Dict[str, Type["TempInitSpec"]]] = {}

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        TempInitSpec._SUBCLASSES[cls.__name__] = cls

    @staticmethod
    def named(type_name: str) -> Type["TempInitSpec"]:
        """ Look up a concrete spec class by its class name.

        :raises KeyError: no spec class of that name is defined.
        """
        try:
            return TempInitSpec._SUBCLASSES[type_name]
        except KeyError:
            raise KeyError(
                f"{type_name!r} is not a known TempInitSpec subclass. "
                f"Known: {sorted(TempInitSpec._SUBCLASSES)}"
            ) from None

    @property
    @abstractmethod
    def init_type(self) -> InitType:
        """ The ObjectTempInitType this spec implements. """
        raise NotImplementedError

    def validate(self) -> None:
        """ Raise ValueError if the spec's parameters are physically invalid.
        Subclasses should extend this rather than overriding it outright.
        """
        pass

    @staticmethod
    def get_vertex_group() -> Optional[str]:
        """ Returns true if the initialization strategy requires some kind of
        vertex weighing, which will be extracted from the returned value """
        return None


@dataclass(frozen=True)
class UniformTempSpec(TempInitSpec):
    """ Every point on the object starts at the same temperature. """
    value_k: float

    @property
    def init_type(self) -> InitType:
        return InitType.UNIFORM

    def validate(self) -> None:
        if not Conversions.is_physically_valid_kelvin(self.value_k):
            raise ValueError(f"UniformTempSpec.value_k ({self.value_k}K) is below absolute zero")


@dataclass(frozen=True)
class WeightPaintedTempSpec(TempInitSpec):
    """ Temperature is derived by remapping a vertex group's per-vertex
    weight (0-1) onto a [min_k, max_k] range.
    """
    vertex_group: str
    min_k: float
    max_k: float
    falloff: str = "LINEAR"  # matches a future Blender CurveMapping/enum choice

    @property
    def init_type(self) -> InitType:
        return InitType.WEIGHT_PAINTED

    def validate(self) -> None:
        if not self.vertex_group:
            raise ValueError("WeightPaintedTempSpec.vertex_group must not be empty")
        if (not Conversions.is_physically_valid_kelvin(self.min_k) or
                not Conversions.is_physically_valid_kelvin(self.max_k)):
            raise ValueError(f"Extrema values below absolute zero for the spec")
        if self.min_k > self.max_k:
            raise ValueError(f"WeightPaintedTempSpec.min_k ({self.min_k}) must be <= max_k ({self.max_k})")

    def get_vertex_group(self) -> str:
        """ This strategy requires weights. """
        return self.vertex_group


@dataclass(frozen=True)
class GradientTempSpec(TempInitSpec):
    """ Temperature varies linearly along the axis connecting two points in
    world space: `point_a` is pinned to `value_a_k`, `point_b` to `value_b_k`,
    and everything in between is linearly interpolated by projecting each
    vertex onto the (point_a -> point_b) axis. Vertices projecting outside
    the segment are clamped to the nearest endpoint's value.
    """
    point_a: Tuple[float, float, float]
    point_b: Tuple[float, float, float]
    value_a_k: float
    value_b_k: float

    # Since these specs are serializable, we have to be sure that we're handling
    # tuples and not random collections which cannot be easily compared with == or !=
    def __post_init__(self):
        object.__setattr__(self, "point_a", tuple(float(v) for v in self.point_a))

    @property
    def init_type(self) -> InitType:
        return InitType.GRADIENT

    def validate(self) -> None:
        if (not Conversions.is_physically_valid_kelvin(self.value_a_k) or
                not Conversions.is_physically_valid_kelvin(self.value_b_k)):
            raise ValueError("GradientTempSpec has a value below absolute zero")
        if self.point_a == self.point_b:
            raise ValueError(
                "GradientTempSpec.point_a and point_b must not coincide "
                "(degenerate gradient axis)"
            )

    def hot_cold_points(self) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
        """ Returns (hot_point, cold_point) by comparing value_a_k/value_b_k.

        """
        if self.value_a_k >= self.value_b_k:
            return self.point_a, self.point_b
        return self.point_b, self.point_a


@dataclass(frozen=True)
class AmbientTempSpec(TempInitSpec):
    """ Every point on every object in the scene starts at the same,
    single ambient temperature (e.g. the surrounding air). """
    value_k: float

    @property
    def init_type(self) -> InitType:
        return InitType.AMBIENT

    def validate(self) -> None:
        if not Conversions.is_physically_valid_kelvin(self.value_k):
            raise ValueError(f"AmbientTempSpec.value_k ({self.value_k}K) is below absolute zero")


@dataclass(frozen=True)
class EnvironmentFactorSpec(ABC):
    """ Base class for a single scene-level environmental condition (see
    EnvironmentSpecType)

    """

    @property
    @abstractmethod
    def factor_type(self) -> EnvironmentSpecType:
        """ The EnvironmentSpecType this spec implements. """
        raise NotImplementedError

    def validate(self) -> None:
        """ Raise ValueError if the spec's parameters are physically invalid.
        Subclasses should extend this rather than overriding it outright.
        """
        pass


@dataclass(frozen=True)
class AmbientTemperatureSpec(EnvironmentFactorSpec):
    """ Air temperature surrounding the scene, for convective/radiative
    exchange with the environment. """
    value_k: float

    @property
    def factor_type(self) -> EnvironmentSpecType:
        return EnvironmentSpecType.AMBIENT_TEMPERATURE

    def validate(self) -> None:
        if not Conversions.is_physically_valid_kelvin(self.value_k):
            raise ValueError(f"AmbientTemperatureSpec.value_k ({self.value_k}K) is below absolute zero")


@dataclass(frozen=True)
class DefaultInitializationSpec(EnvironmentFactorSpec):
    """ The default initialization strategy. Contains a TempInitSpec to
    hold an arbitrary temperature initialization specification"""
    init_spec: TempInitSpec

    @property
    def factor_type(self) -> EnvironmentSpecType:
        return EnvironmentSpecType.DEFAULT_INITIALIZATION

    def validate(self) -> None:
        self.init_spec.validate()


@dataclass
class ThermalProfile:
    """ Holds a complete profile: how an object's temperature is initialized,
    plus (in a later phase) how it evolves over time. Kept minimal for now -
    evolution strategy will be added once thermal_core/evolution.py is built out.
    """
    init_spec: TempInitSpec


class ThermalSpecs:
    """
    Holds purely physical thermal specs (emissivity, material properties,
    etc). Out of scope for Phase 1 - untouched here.
    """