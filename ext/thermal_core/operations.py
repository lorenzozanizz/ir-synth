"""
Declarative descriptions of transformations applied to the temperature field
after every source strategy has evaluated.

"""

from abc import ABC, abstractmethod
from inspect import isabstract
from dataclasses import dataclass, fields as dataclass_fields
from typing import Any, ClassVar, Dict, Mapping, Tuple, Type

from .contracts import OpStage, OpType, ScopeMode
from .field import FieldSet, ObjectKey


@dataclass(frozen=True)
class OpScope:
    """ Which objects an operation acts on.

    :param mode: how the selection is expressed
    :param collection: collection name, used when mode is COLLECTION
    :param objects: explicit object keys, used when mode is OBJECTS
    """

    mode: ScopeMode = ScopeMode.ALL
    collection: str = ""
    objects: Tuple[ObjectKey, ...] = ()

    def validate(self) -> None:
        """ :raises ValueError: the selection cannot name anything. """
        if self.mode is ScopeMode.COLLECTION and not self.collection:
            raise ValueError("An OpScope in COLLECTION mode needs a collection name")
        if self.mode is ScopeMode.OBJECTS and not self.objects:
            raise ValueError("An OpScope in OBJECTS mode needs at least one object")

    def resolve(self, fields: FieldSet) -> Tuple[ObjectKey, ...]:
        """ The keys this scope selects, in the FieldSet's stable order.

        Keys that name an object absent from the bake are dropped rather than
        raising: an explicit scope naming a deleted object should narrow the
        operation, not break the whole stack.
        """
        if self.mode is ScopeMode.ALL:
            return fields.keys()

        if self.mode is ScopeMode.COLLECTION:
            return tuple(
                key for key in fields.keys()
                if self.collection in fields.collections_for(key)
            )

        if self.mode is ScopeMode.OBJECTS:
            selected = set(self.objects)
            return tuple(key for key in fields.keys() if key in selected)

        raise ValueError(f"Unknown scope mode: {self.mode}")

    def describe(self) -> str:
        """ Short label for a panel header. """
        if self.mode is ScopeMode.ALL:
            return "All"
        if self.mode is ScopeMode.COLLECTION:
            return self.collection or "<no collection>"
        count = len(self.objects)
        if count == 0:
            return "<no objects>"
        if count == 1:
            return self.objects[0]
        return f"{count} objects"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode.name,
            "collection": self.collection,
            "objects": list(self.objects),
        }

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "OpScope":
        return OpScope(
            mode=ScopeMode[data.get("mode", ScopeMode.ALL.name)],
            collection=data.get("collection", ""),
            objects=tuple(data.get("objects", ())),
        )


@dataclass(frozen=True)
class FieldOperation(ABC):
    """ Base class for one entry in the scene's operation stack.

    Every field carries a default so that subclasses can add their own
    parameters without fighting dataclass inheritance ordering.

    :param enabled: the UI mute toggle. A disabled operation is kept in the
        config, so muting is reversible and a hook can toggle it, but is
        skipped at evaluation time.
    :param seed: for operations with a random component. Present on the base
        class because retrofitting reproducibility later is far harder than
        carrying an unused integer now.
    """

    enabled: bool = True
    seed: int = 0

    # Every concrete subclass, keyed by class name. Populated on definition
    # and used by SceneThermalConfig to rebuild an operation from a dict.
    _SUBCLASSES: ClassVar[Dict[str, Type["FieldOperation"]]] = {}

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        FieldOperation._SUBCLASSES[cls.__name__] = cls

    @staticmethod
    def concrete_types() -> Dict[str, Type["FieldOperation"]]:
        """ Every instantiable operation class, keyed by class name.

        __init_subclass__ also catches the abstract intermediates
        (PerObjectOperation, SceneOperation), which are not operations a
        config can name. Abstractness is only decidable after the class body
        finishes, so the filtering happens here rather than at registration.
        """
        return {
            name: cls for name, cls in FieldOperation._SUBCLASSES.items()
            if not isabstract(cls)
        }

    @staticmethod
    def named(type_name: str) -> Type["FieldOperation"]:
        """ Look up a concrete operation class by its class name.

        :raises KeyError: no instantiable operation class of that name exists.
        """
        concrete = FieldOperation.concrete_types()
        try:
            return concrete[type_name]
        except KeyError:
            raise KeyError(
                f"{type_name!r} is not a known concrete FieldOperation subclass. "
                f"Known: {sorted(concrete)}"
            ) from None

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "FieldOperation":
        """ Rebuild an instance from the plain data produced by asdict().

        Nested OpScope dicts and JSON's lists-instead-of-tuples are converted
        back; unknown keys are ignored so an old config does not break when a
        parameter is removed.
        """
        kwargs: Dict[str, Any] = {}
        for field in dataclass_fields(cls):
            if field.name not in params:
                continue
            value = params[field.name]
            if field.type is OpScope or field.type == "OpScope":
                kwargs[field.name] = OpScope.from_dict(value)
            elif isinstance(value, list):
                kwargs[field.name] = tuple(value)
            else:
                kwargs[field.name] = value
        return cls(**kwargs)

    @property
    @abstractmethod
    def op_type(self) -> OpType:
        """ The OpType this operation implements. """
        raise NotImplementedError

    @property
    @abstractmethod
    def stage(self) -> OpStage:
        """ How much of the scene this operation needs to see. """
        raise NotImplementedError

    @abstractmethod
    def scopes(self) -> Tuple[OpScope, ...]:
        """ Every scope this operation carries, so generic code (validation,
        UI warnings) can check them without knowing the concrete type.
        """
        raise NotImplementedError

    def validate(self) -> None:
        """ Check parameters are physically meaningful.

        The base implementation validates every scope. Subclasses that
        override should call super().validate() first.

        :raises ValueError: any parameter is invalid.
        """
        for scope in self.scopes():
            scope.validate()

    def describe(self) -> str:
        """ One-line human summary for a panel header. """
        return self.op_type.value


@dataclass(frozen=True)
class PerObjectOperation(FieldOperation, ABC):
    """ An operation that is a formula over one object's field and geometry.

    Carries only the target object's scope.
    """

    scope: OpScope = OpScope()

    @property
    def stage(self) -> OpStage:
        return OpStage.PER_OBJECT

    def scopes(self) -> Tuple[OpScope, ...]:
        return (self.scope,)

    def describe(self) -> str:
        return f"{self.op_type.value} ({self.scope.describe()})"


@dataclass(frozen=True)
class SceneOperation(FieldOperation, ABC):
    """ An operation that reads and writes across objects.

    Resolves its own scopes, because some carry more than one (contact
    diffusion has sources and receivers, and only the operation knows which
    is which).
    """

    @property
    def stage(self) -> OpStage:
        return OpStage.SCENE


@dataclass(frozen=True)
class ClampOp(PerObjectOperation):
    """ Constrain every value into [min_k, max_k].

    :param min_k: lower bound in Kelvin.
    :param max_k: upper bound in Kelvin.
    """

    # Default values, they actually change as requested by the user in the chain.
    min_k: float = 0.0
    max_k: float = 1000.0

    @property
    def op_type(self) -> OpType:
        return OpType.CLAMP

    def validate(self) -> None:
        super().validate()
        if self.min_k < 0.0:
            raise ValueError(f"ClampOp.min_k ({self.min_k}K) is below absolute zero")
        if self.max_k <= self.min_k:
            raise ValueError(
                f"ClampOp.max_k ({self.max_k}K) must be above min_k ({self.min_k}K)"
            )

    def describe(self) -> str:
        return f"Clamp {self.min_k:g}-{self.max_k:g}K ({self.scope.describe()})"


@dataclass(frozen=True)
class SmoothOp(PerObjectOperation):
    """ Average each vertex toward its edge neighbours.

    :param iterations: how many averaging passes to run. Each pass spreads
        heat by one edge, so the distance smoothing reaches is set by this,
        not by factor.
    :param factor: how far toward the neighbour average each pass moves, in
        [0, 1]. Above ~0.5 successive passes can oscillate on irregular
        meshes, which is why the UI soft-caps it there.
    """

    iterations: int = 5
    factor: float = 0.5

    @property
    def op_type(self) -> OpType:
        return OpType.SMOOTH

    def validate(self) -> None:
        super().validate()
        if self.iterations < 0:
            raise ValueError(f"SmoothOp.iterations ({self.iterations}) cannot be negative")
        if not 0.0 <= self.factor <= 1.0:
            raise ValueError(f"SmoothOp.factor ({self.factor}) must be in [0, 1]")

    def describe(self) -> str:
        return f"Smooth x{self.iterations} ({self.scope.describe()})"


@dataclass(frozen=True)
class ContactDiffusionOp(SceneOperation):
    """ Warm receiver objects according to their proximity to source objects.
    This is a static approximation of an already-diffused state, not
    a simulation, there is no time or physicss.

    :param source: objects whose temperatures are read.
    :param receiver: objects whose temperatures are modified. An object in
        both scopes never acts as its own source.
    :param radius: metres, in world space. Beyond this a receiver vertex is
        not considered in the diffusion.
    :param strength: maximum blend toward the source temperature, at zero
        distance, in [0, 1].
    :param falloff: how the blend decays from 1 at zero distance to 0 at
        radius. Same names as the weight-paint falloffs.
    """

    source: OpScope = OpScope()
    receiver: OpScope = OpScope()
    radius: float = 0.1
    strength: float = 0.8
    falloff: str = "EASE_IN_OUT"

    @property
    def op_type(self) -> OpType:
        return OpType.CONTACT_DIFFUSION

    def scopes(self) -> Tuple[OpScope, ...]:
        return (self.source, self.receiver)

    def validate(self) -> None:
        super().validate()
        if self.radius <= 0.0:
            raise ValueError(f"ContactDiffusionOp.radius ({self.radius}) must be positive")
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError(
                f"ContactDiffusionOp.strength ({self.strength}) must be in [0, 1]"
            )

    def describe(self) -> str:
        return (
            f"Diffuse {self.source.describe()} -> {self.receiver.describe()} "
            f"@ {self.radius:g}m"
        )
