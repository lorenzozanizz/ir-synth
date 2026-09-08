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

from typing import Dict, Iterable, List, Tuple

from bpy.types import Object, Collection

from ..thermal_core.config import SceneThermalConfig
from ..thermal_core.contracts import InitType, SpecScope, EnvironmentSpecType
from ..thermal_core.field import ObjectKey
from ..thermal_core.specs import TempInitSpec
from .init_registry import InitStrategyRegistry
from .environment_registry import EnvSearch


class SpecResolutionError(Exception):
    """ Base class for errors raised while resolving an object's effective temperature-init
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

    def __init__(self, obj: Object, candidates: List[Tuple[Collection, TempInitSpec]]):
        self.obj = obj
        self.candidates = candidates
        detail = ", ".join(f"{coll.name!r} -> {spec}" for coll, spec in candidates)
        super().__init__(
            f"{obj.name!r} is set to Inherit but belongs to multiple collections with disagreeing specs: "
            f"{detail}. Set an explicit strategy on the object, or make the collections agree."
        )


class InvalidCollectionSpecError(SpecResolutionError):
    """ Raised when a Collection's stored init_type isn't legal at
    Collection scope.
    This shouldn't happen through the UI but can happen via a script or manual
    ID-property editing. Raised immediately to highlight the issue.
    """

    def __init__(self, collection: Collection, init_type: InitType):
        self.collection = collection
        self.init_type = init_type
        super().__init__(
            f"Collection {collection.name!r} has init_type={init_type.value!r} "
            f"stored, but that strategy isn't valid at Collection scope."
        )


class SpecsResolver:

    @staticmethod
    def _build_spec_for(object, init_type: InitType) -> TempInitSpec:
        """ Look up the strategy descriptor for init_type and build a spec
        from the matching sub-PropertyGroup on props_owner.thermal_init.

        :param object: The object which owns the properties
        :param init_type: The type of initializer for the object
        """
        descriptor = InitStrategyRegistry.get_strategy(init_type)
        # raises NotImplementedError for GRADIENT/AMBIENT
        sub_props = getattr(object.thermal_init, descriptor.attr_name)
        return descriptor.build(sub_props)

    @staticmethod
    def _candidate_specs_from_collections(obj: Object) -> List[Tuple[Collection, TempInitSpec]]:
        """ Gather a (Collection, TempInitSpec) pair for every collection `obj`
        belongs to that itself resolves to a concrete (non-INHERIT) strategy.
        Collections set to INHERIT themselves are skipped (nothing to offer).
        """
        candidates: List[Tuple[Collection, TempInitSpec]] = []
        for collection in obj.users_collection:
            coll_init_type = InitType[collection.thermal_init.init_type]
            if coll_init_type is InitType.INHERIT:
                continue
            if coll_init_type not in InitType.allowed_for_scope(SpecScope.COLLECTION):
                raise InvalidCollectionSpecError(collection, coll_init_type)
            candidates.append((collection, SpecsResolver._build_spec_for(collection, coll_init_type)))
        return candidates

    @staticmethod
    def resolve_object_spec(obj: Object) -> TempInitSpec:
        """ Resolve `obj`'s effective temperature-init spec.

        This is the single conversion boundary between bpy state and
        thermal_core: everything downstream (baking) should call this instead
        of reading `obj.thermal_init` directly.

        :raises UnresolvedSpecError: INHERIT with no concrete collection default.
        :raises AmbiguousInheritanceError: multiple collections disagree.
        :raises InvalidCollectionSpecError: a collection stores an
            object-only strategy (e.g. legacy WEIGHT_PAINTED data).
        :raises NotImplementedError: the resolved strategy has no
            StrategyDescriptor yet (e.g. GRADIENT, AMBIENT).
        """
        obj_init_type = InitType[obj.thermal_init.init_type]

        if obj_init_type is not InitType.INHERIT:
            return SpecsResolver._build_spec_for(obj, obj_init_type)

        candidates = SpecsResolver._candidate_specs_from_collections(obj)

        # Last link in the chain: the scene-wide default, carried as an entry of
        # the environmental-factor stack.
        if not candidates:
            default = EnvSearch.build(EnvironmentSpecType.DEFAULT_INITIALIZATION)
            if default is not None:
                return default.init_spec
            raise UnresolvedSpecError(
                f"{obj.name!r} is set to Inherit, but no containing collection "
                f"provides a concrete default and the scene has no Default "
                f"Initialization factor configured."
            )

        first_spec = candidates[0][1]
        if any(spec != first_spec for _, spec in candidates[1:]):
            raise AmbiguousInheritanceError(obj, candidates)

        return first_spec



class ConfigBuilder:
    """ Builds a full scene SceneThermalConfig from the current bpy state.

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
    def from_objects(
        objects: Iterable[Object],
    ) -> Tuple[SceneThermalConfig, Dict[ObjectKey, Exception], Dict[ObjectKey, Exception]]:
        """ Resolve each object's effective spec into a config.

        Objects whose spec cannot be resolved are left out of the config and
        recorded in the returned mapping, so the caller can report them
        without the resolution failure aborting the whole scene.

        :return: (config, object key -> the exception that excluded it)
        """
        # Basically, just iterate all objects and resolve for each its spec.
        sources: Dict[ObjectKey, TempInitSpec] = {}
        unresolved: Dict[ObjectKey, Exception] = {}
        invalid: Dict[ObjectKey, Exception] = {}

        for obj in objects:
            key = ConfigBuilder.object_key(obj)
            try:
                sources[key] = spec = SpecsResolver.resolve_object_spec(obj)
                spec.validate()
            except (SpecResolutionError, NotImplementedError) as error:
                unresolved[key] = error
            except ValueError as validation_error:
                # Keep track of invalid objects
                invalid[key] = validation_error

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
