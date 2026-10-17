"""
Resolves an Object's *effective* temperature-init spec by walking the
inheritance chain, and is simultaneously the conversion boundary.
No bpy state should cross into thermal_core beyond this function - baking
code should only ever see the result of resolve_object_spec(), never touch the initialization
directly.

Chain walked for an object set to INHERIT:
    Object (if not INHERIT)
      -> Object's Collection(s) (if not INHERIT)
        -> Scene default (EnvironmentSpecType.DEFAULT_INITIALIZATION, if present)

"""

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, Iterable, List, Optional, Tuple, Type

import bpy
from bpy.types import Object, Collection

from ..thermal_core.config import SceneThermalConfig
from ..thermal_core.contracts import (
    InitType, EmissivityType, SpecScope, EnvironmentSpecType,
)
from ..thermal_core.emissivity import SceneEmissivityConfig
from ..thermal_core.field import ObjectKey
from ..thermal_core.specs import SpecBase, TempInitSpec, UniformEmissivitySpec
from .init_registry import InitStrategyRegistry
from .emissivity_registry import EmissivityStrategyRegistry
from .environment_registry import EnvSearch
from .strategy_registry import StrategyRegistryBase


class SpecResolutionError(Exception):
    """ Base class for errors raised while resolving an object's effective
    spec. """


class UnresolvedSpecError(SpecResolutionError):
    """ Raised when an object (transitively) resolves to INHERIT but no
    containing collection provides a concrete default.
    """


class AmbiguousInheritanceError(SpecResolutionError):
    """ Raised when an object belongs to multiple collections whose concrete
    specs disagree, so INHERIT has no single well-defined answer. Deliberately not resolved
    by picking one arbitrarily.
    """

    def __init__(self, obj: Object, candidates: List[Tuple[Collection, SpecBase]]):
        self.obj = obj
        self.candidates = candidates
        detail = ", ".join(f"{coll.name!r} -> {spec}" for coll, spec in candidates)
        super().__init__(
            f"{obj.name!r} is set to Inherit but belongs to multiple collections with disagreeing specs: "
            f"{detail}. Set an explicit strategy on the object, or make the collections agree."
        )


class InvalidCollectionSpecError(SpecResolutionError):
    """ Raised when a Collection's stored strategy type isn't legal at
    Collection scope.
    This shouldn't happen through the UI but can happen via a script or manual
    ID-property editing. Raised immediately to highlight the issue.
    """

    def __init__(self, collection: Collection, init_type: Enum):
        self.collection = collection
        self.init_type = init_type
        super().__init__(
            f"Collection {collection.name!r} has {init_type.value!r} "
            f"stored, but that strategy isn't valid at Collection scope."
        )


@dataclass(frozen=True)
class SpecChannel:
    """ A class to represent one per-vertex quantity that resolves through Object -> Collection(s)
    -> Scene default.

    :param label: human name, used in error messages.
    :param props_attr: attribute on Object/Collection holding the strategy
        PropertyGroup
    :param type_field: field on that group holding the enum name
    :param type_enum: the strategy enum (InitType, EmissivityType).
    :param registry: the StrategyRegistryBase subclass for type_enum.
    :param scene_default: returns the scene-wide spec, or None if the scene
        does not have a scene-wide specification for the given channel
    """
    label: str
    props_attr: str
    type_field: str
    type_enum: Type[Enum]
    registry: Type[StrategyRegistryBase]
    scene_default: Callable[[], Optional[SpecBase]]

    def props_of(self, owner):
        """ The strategy PropertyGroup on an Object or Collection. """
        return getattr(owner, self.props_attr)

    def type_of(self, owner) -> Enum:
        """ The strategy enum member stored on an Object or Collection. """
        return self.type_enum[getattr(self.props_of(owner), self.type_field)]


def _scene_default_temperature() -> Optional[TempInitSpec]:
    """ The Default Initialization environment factor, if configured. """
    default = EnvSearch.build(EnvironmentSpecType.DEFAULT_INITIALIZATION)
    return None if default is None else default.init_spec


def _scene_default_emissivity() -> UniformEmissivitySpec:
    """ The scene default emissivity. Always present, so emissivity never
    raises UnresolvedSpecError. """
    return UniformEmissivitySpec(value=float(bpy.context.scene.thermal_render.emissivity))


# This channel is in charge of maintaining all temperature maps across the scene
TEMPERATURE_CHANNEL = SpecChannel(
    label="initial temperature",
    props_attr="thermal_init",
    type_field="init_type",
    type_enum=InitType,
    registry=InitStrategyRegistry,
    scene_default=_scene_default_temperature,
)

# This channel is in charge of maintaining emissivity maps over the scene.
# Note that internally the mappings have different capabilities, since emissivity is assumed
# to not change "dynamically"
EMISSIVITY_CHANNEL = SpecChannel(
    label="emissivity",
    props_attr="thermal_emissivity",
    type_field="emissivity_type",
    type_enum=EmissivityType,
    registry=EmissivityStrategyRegistry,
    scene_default=_scene_default_emissivity,
)


class SpecsResolver:

    @staticmethod
    def _build_spec_for(owner, strategy_type: Enum,
                        channel: SpecChannel = TEMPERATURE_CHANNEL) -> SpecBase:
        """ Look up the strategy descriptor for strategy_type and build a spec
        from the matching sub-PropertyGroup on the owner.

        :param owner: the Object or Collection which owns the properties
        :param strategy_type: the concrete strategy, cannot be INHERIT
        :param channel: which quantity to build
        """
        descriptor = channel.registry.get_strategy(strategy_type)
        sub_props = getattr(channel.props_of(owner), descriptor.attr_name)
        return descriptor.build(sub_props)

    @staticmethod
    def _candidate_specs_from_collections(
        obj: Object, channel: SpecChannel = TEMPERATURE_CHANNEL,
    ) -> List[Tuple[Collection, SpecBase]]:
        """ Gather a (Collection, spec) pair for every collection `obj`
        belongs to that itself resolves to a concrete (non-INHERIT) strategy.
        Collections set to INHERIT themselves are skipped (nothing to offer).
        """
        candidates: List[Tuple[Collection, SpecBase]] = []
        inherit = channel.type_enum.INHERIT
        # Go and iterate over all collections which contains said object, then see
        # which one of them has a defined specification. Otherwise this will go to the
        # default scene-wide configuration
        for collection in obj.users_collection:
            coll_type = channel.type_of(collection)
            if coll_type is inherit:
                continue
            if coll_type not in channel.type_enum.allowed_for_scope(SpecScope.COLLECTION):
                raise InvalidCollectionSpecError(collection, coll_type)
            candidates.append(
                (collection, SpecsResolver._build_spec_for(collection, coll_type, channel))
            )
        return candidates

    @staticmethod
    def resolve_object_spec(obj: Object, channel: SpecChannel = TEMPERATURE_CHANNEL) -> SpecBase:
        """ Resolve an object's effective spec for one channel.

        This is the ONLY place where we convert between bpy state and
        thermal_core. DO NOT read bpy properties directly.

        This function can fail in many different ways, depending on the overall settings.
        Wheter the object fails to bake also depends.

        :param channel: TEMPERATURE_CHANNEL (default) or EMISSIVITY_CHANNEL.

        :raises UnresolvedSpecError: INHERIT with no concrete collection
            default and no scene default.
        :raises AmbiguousInheritanceError: multiple collections disagree.
        :raises InvalidCollectionSpecError: a collection stores an
            object-only strategy (e.g. legacy WEIGHT_PAINTED data).
        :raises NotImplementedError: the resolved strategy has no
            StrategyDescriptor yet.
        """
        obj_type = channel.type_of(obj)

        if obj_type is not channel.type_enum.INHERIT:
            return SpecsResolver._build_spec_for(obj, obj_type, channel)

        candidates = SpecsResolver._candidate_specs_from_collections(obj, channel)

        # Last link in the chain: the scene-wide default.
        if not candidates:
            default = channel.scene_default()
            if default is not None:
                return default
            raise UnresolvedSpecError(
                f"{obj.name!r} is set to Inherit for {channel.label}, but no "
                f"containing collection provides a concrete value and the "
                f"scene has no default {channel.label} configured."
            )

        first_spec = candidates[0][1]
        if any(spec != first_spec for _, spec in candidates[1:]):
            raise AmbiguousInheritanceError(obj, candidates)

        return first_spec


class ConfigBuilder:
    """ Builds the scene configs (SceneThermalConfig, SceneEmissivityConfig)
    from the current bpy state.

    When this is created, bpy is not required anymore, allowing for decoupling of backend
    and BPY. This also allows a hook (TBI) substitute its own config without any of the pipeline
    noticing.
    """

    @staticmethod
    def object_key(obj: Object) -> ObjectKey:
        """ The FieldSet key for an object. """
        # Currently, the key is just its name, avoid using UUIDS which pollute the scene.
        return obj.name

    @staticmethod
    def mesh_objects(scene) -> Tuple[Object, ...]:
        """ Every object in the scene a temperature field can be baked onto. """
        # NOTE: This only selects objects which are of type MESH. this does not
        # take into considerations for example bezier curves or meshless planes.
        # This can cause unexpected behaviour and a user should be made aware
        # of this, TODO for docs
        return tuple(obj for obj in scene.objects if obj.type == 'MESH')

    @staticmethod
    def collection_membership(
        objects: Iterable[Object],
    ) -> Dict[ObjectKey, Tuple[str, ...]]:
        """ Object key -> the names of every collection it belongs to.

        Consumed by OpScope in COLLECTION mode. Collections are the mechanism
        the UI pushes users toward for selecting a set of objects, since they
        survive renames of their members and a hook can populate them.
        """
        return {
            ConfigBuilder.object_key(obj): tuple(c.name for c in obj.users_collection)
            for obj in objects
        }

    @staticmethod
    def _resolve_all(
        objects: Iterable[Object], channel: SpecChannel,
    ) -> Tuple[Dict[ObjectKey, SpecBase], Dict[ObjectKey, Exception], Dict[ObjectKey, Exception]]:
        """ Resolve and validate each object's spec for one channel.

        Objects whose spec cannot be resolved are left out and recorded in
        unresolved. Objects whose spec is invalid are recorded in invalid.
        One failure does not abort the whole scene.

        :return: (sources, unresolved, invalid)
        """
        sources: Dict[ObjectKey, SpecBase] = {}
        unresolved: Dict[ObjectKey, Exception] = {}
        invalid: Dict[ObjectKey, Exception] = {}

        for obj in objects:
            key = ConfigBuilder.object_key(obj)
            try:
                # Same as before the channel refactor: an invalid spec stays
                # in sources AND is recorded in invalid. The pipeline then
                # rejects it, and the bake report counts it.
                sources[key] = spec = SpecsResolver.resolve_object_spec(obj, channel)
                spec.validate()
            except (SpecResolutionError, NotImplementedError) as error:
                unresolved[key] = error
            except ValueError as validation_error:
                # Keep track of invalid objects
                invalid[key] = validation_error

        return sources, unresolved, invalid

    @staticmethod
    def from_objects(
        objects: Iterable[Object],
    ) -> Tuple[SceneThermalConfig, Dict[ObjectKey, Exception], Dict[ObjectKey, Exception]]:
        """ Resolve each object's effective temperature spec into a config.

        :return: (config, unresolved: key -> error, invalid: key -> error)
        """
        sources, unresolved, invalid = ConfigBuilder._resolve_all(objects, TEMPERATURE_CHANNEL)
        return SceneThermalConfig(sources=sources), unresolved, invalid

    @staticmethod
    def from_scene(scene) -> Tuple[SceneThermalConfig, Dict[ObjectKey, Exception], Dict[ObjectKey, Exception]]:
        """ The complete config: every mesh object's source, plus the scene's
        operation stack.

        Imported lazily because ui/op_registry.py is a UI concern and this
        module is imported by the bake path.
        """
        from .op_registry import OperationRegistry

        config, unresolved, invalid = ConfigBuilder.from_objects(ConfigBuilder.mesh_objects(scene))
        stack = getattr(scene, "thermal_stack", None)
        if stack is None:
            return config, unresolved, invalid
        return config.with_operations(OperationRegistry.build_stack(stack)), unresolved, invalid

    @staticmethod
    def emissivity_from_objects(
        objects: Iterable[Object],
    ) -> Tuple[SceneEmissivityConfig, Dict[ObjectKey, Exception], Dict[ObjectKey, Exception]]:
        """ Resolve each object's effective emissivity spec into a config.

        :return: (config, unresolved: key -> error, invalid: key -> error)
        """
        sources, unresolved, invalid = ConfigBuilder._resolve_all(objects, EMISSIVITY_CHANNEL)
        return SceneEmissivityConfig(sources=sources), unresolved, invalid

    @staticmethod
    def emissivity_from_scene(
        scene,
    ) -> Tuple[SceneEmissivityConfig, Dict[ObjectKey, Exception], Dict[ObjectKey, Exception]]:
        """ The emissivity config for every mesh object in the scene. """
        return ConfigBuilder.emissivity_from_objects(ConfigBuilder.mesh_objects(scene))
