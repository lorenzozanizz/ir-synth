"""
Pure data contracts describing how an object's/collection's per-vertex
quantities are specified: the initial temperature field (TempInitSpec) and
the emissivity map (EmissivitySpec).

"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, fields as dataclass_fields
import math
from typing import Any, ClassVar, Dict, Mapping, Optional, Type, Tuple, Union

from .temperature import Conversions
from .contracts import InitType, EmissivityType, EnvironmentSpecType


@dataclass(frozen=True)
class SpecBase(ABC):
    """ Shared base of every serializable spec family (TempInitSpec,
    EmissivitySpec).

    Holds only what every family needs: a lookup of concrete classes by
    name for deserialization, and the validate/get_vertex_group defaults.
    """

    # Every subclass, keyed by class name. Populated automatically on subclass
    # definition and used by the scene configs to rebuild a spec from a
    # serialized dict. Class names must be unique across families.
    _SUBCLASSES: ClassVar[Dict[str, Type["SpecBase"]]] = {}

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        SpecBase._SUBCLASSES[cls.__name__] = cls

    @classmethod
    def _concrete_subclasses(cls) -> Dict[str, Type["SpecBase"]]:
        """ Concrete (non-abstract) classes of this family only. """
        return {
            name: found for name, found in SpecBase._SUBCLASSES.items()
            if issubclass(found, cls) and not getattr(found, "__abstractmethods__", None)
        }

    @classmethod
    def named(cls, type_name: str) -> Type["SpecBase"]:
        """ Look up a concrete spec class of this family by its class name.

        TempInitSpec.named never returns an EmissivitySpec, and the reverse.

        :raises KeyError: no concrete class of that name in this family.
        """
        family = cls._concrete_subclasses()
        try:
            return family[type_name]
        except KeyError:
            raise KeyError(
                f"{type_name!r} is not a known {cls.__name__} subclass. "
                f"Known: {sorted(family)}"
            ) from None

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "SpecBase":
        """ Rebuild an instance from the plain data produced by asdict().
        A *missing required* parameter is an error as the constructor raises TypeError,
        which the caller turns into a ConfigError.

        :param params: field name -> value.
        :raises TypeError: a required field is absent.
        """
        known = {field.name for field in dataclass_fields(cls)}
        kwargs: Dict[str, Any] = {
            name: (tuple(value) if isinstance(value, list) else value)
            for name, value in params.items()
            if name in known
        }
        return cls(**kwargs)

    @property
    # Dont make this abstract, not needed anymore
    # @abstractmethod
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
class TempInitSpec(SpecBase, ABC):
    """ Base class for a single temperature-initialization strategy.

    Concrete subclasses correspond 1:1 with an `ObjectTempInitType` member
    (excluding INHERIT, which is a resolution-time concept, not a spec - by
    the time a TempInitSpec exists, inheritance has already been resolved to
    a concrete strategy).
    """

    @property
    @abstractmethod
    def init_type(self) -> InitType:
        """ The ObjectTempInitType this spec implements. """
        raise NotImplementedError


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
    #
    # BOTH endpoints must be normalized. JSON has no tuple type, so a
    # deserialized point arrives as a list; leaving one of the two as a list
    # made a round-tripped spec compare unequal to the original, and made the
    # degenerate-axis check in validate() silently pass, because a tuple never
    # equals a list.
    def __post_init__(self):
        object.__setattr__(self, "point_a", tuple(float(v) for v in self.point_a))
        object.__setattr__(self, "point_b", tuple(float(v) for v in self.point_b))

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


def _is_valid_emissivity(value: float) -> bool:
    """ Emissivity is a fraction of blackbody emission: finite, in [0, 1]. """
    return math.isfinite(value) and 0.0 <= value <= 1.0


@dataclass(frozen=True)
class EmissivitySpec(SpecBase, ABC):
    """ Base class for a single emissivity strategy.

    Concrete subclasses correspond 1:1 with an EmissivityType member
    (excluding INHERIT, which is resolved before a spec exists).
    """

    @property
    @abstractmethod
    def emissivity_type(self) -> EmissivityType:
        """ The EmissivityType this spec implements. """
        raise NotImplementedError


@dataclass(frozen=True)
class UniformEmissivitySpec(EmissivitySpec):
    """ Every point on the object has the same emissivity. Also the spec
    that the scene default emissivity resolves to. """
    value: float

    @property
    def emissivity_type(self) -> EmissivityType:
        return EmissivityType.UNIFORM

    def validate(self) -> None:
        if not _is_valid_emissivity(self.value):
            raise ValueError(f"UniformEmissivitySpec.value ({self.value}) must be in [0, 1]")


@dataclass(frozen=True)
class WeightPaintedEmissivitySpec(EmissivitySpec):
    """ Emissivity is derived by remapping a vertex group's per-vertex
    weight (0-1) onto [min_value, max_value].
    """
    vertex_group: str
    min_value: float
    max_value: float
    falloff: str = "LINEAR"

    @property
    def emissivity_type(self) -> EmissivityType:
        return EmissivityType.WEIGHT_PAINTED

    def validate(self) -> None:
        if not self.vertex_group:
            raise ValueError("WeightPaintedEmissivitySpec.vertex_group must not be empty")
        if not (_is_valid_emissivity(self.min_value) and _is_valid_emissivity(self.max_value)):
            raise ValueError("WeightPaintedEmissivitySpec extrema must be in [0, 1]")
        if self.min_value > self.max_value:
            raise ValueError(
                f"WeightPaintedEmissivitySpec.min_value ({self.min_value}) must be "
                f"<= max_value ({self.max_value})"
            )

    def get_vertex_group(self) -> str:
        """ This strategy requires weights. """
        return self.vertex_group


class ThermalSpecs:
    """
    Holds purely physical thermal specs (emissivity, material properties,
    etc). Out of scope for Phase 1 - untouched here.
    """