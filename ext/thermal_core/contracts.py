""" The module containing all basic enums/ contracts between the pure-bpy
part of the code and the bpy-free part of the code, which will be hooked later
and which will be tested. """
from enum import Enum
from dataclasses import dataclass



class SpecScope(Enum):
    """ Where a temperature init spec is being attached/resolved. """
    OBJECT = "Object"
    COLLECTION = "Collection"
    # The root of the inheritance chain implemented as an
    # entry of the environmental factor stack
    SCENE = "Scene"


class InitType(Enum):
    """ Strategy used to initialize an object's starting temperature field.

    Not every strategy is valid at every configuration, for example
    WEIGHT_PAINTED depends on per-vertex data (a vertex group) that only exists on a
    mesh Object, so it can never be used as a Collection-level default.
    """
    # Keep this as the first attribute. Any object that does not have a set value
    # will inherit from something above it, eventually a
    # scene default value.
    INHERIT = "Inherit"


    UNIFORM = "Uniform"
    AMBIENT = "Ambient"
    GRADIENT = "Gradient"
    WEIGHT_PAINTED = "Weight Painted"

    @staticmethod
    def allowed_for_scope(scope: SpecScope) -> tuple:
        """ Return the subset of strategies that are legal at the given scope. """
        return _allowed_for_scope(
            _ALL_INITIALIZATION_STRATEGIES, _OBJECT_ONLY_STRATS, InitType.INHERIT, scope,
        )


# These have to be put at the module level as any variable inside an Enum is still treated
# as an enum value and that causes issues with type hinting
# Strategies that require per-object data and cannot be a Collection-level default.
_ALL_INITIALIZATION_STRATEGIES = tuple(i_t for i_t in InitType)
_OBJECT_ONLY_STRATS = frozenset({InitType.WEIGHT_PAINTED})


def _allowed_for_scope(members: tuple, object_only: frozenset, inherit: Enum,
                       scope: SpecScope) -> tuple:
    """ The scope filter shared by every strategy enum (InitType, EmissivityType).

    :param members: every member of the enum, INHERIT included.
    :param object_only: members that need per-object data (a vertex group),
        so a Collection or the Scene cannot offer them.
    :param inherit: the INHERIT member of the enum.
    :param scope: the scope to filter for.
    """
    if scope is SpecScope.OBJECT:
        return tuple(members)
    if scope is SpecScope.COLLECTION:
        return tuple(m for m in members if m not in object_only)
    if scope is SpecScope.SCENE:
        return tuple(m for m in members if m not in object_only and m is not inherit)
    raise ValueError(f"Unknown scope: {scope}")


class EmissivityType(Enum):
    """ Strategy used to give an object its per-vertex emissivity map.

    Parallel to InitType. The scene default is a scalar value used as default.
    """
    # Keep this as the first attribute: it is the default of the dropdown.
    INHERIT = "Inherit"

    UNIFORM = "Uniform"
    WEIGHT_PAINTED = "Weight Painted"

    @staticmethod
    def allowed_for_scope(scope: SpecScope) -> tuple:
        """ Return the subset of strategies that are legal at the given scope. """
        return _allowed_for_scope(
            _ALL_EMISSIVITY_STRATEGIES, _OBJECT_ONLY_EMISSIVITY, EmissivityType.INHERIT, scope,
        )


_ALL_EMISSIVITY_STRATEGIES = tuple(e_t for e_t in EmissivityType)
_OBJECT_ONLY_EMISSIVITY = frozenset({EmissivityType.WEIGHT_PAINTED})


class EnvironmentSpecType(Enum):
    """ Scene-level environmental condition shown in the Scene Properties
    dropdown

    """
    AMBIENT_TEMPERATURE = "Ambient Temperature"
    HUMIDITY = "Humidity"
    # The scene default strategy used by objects that resolve to
    # INHERIT and have no containing collection offering a concrete strategy
    DEFAULT_INITIALIZATION = "Default Initialization"

class ScopeMode(Enum):
    """ How a field operation picks the objects it acts on. """

    # Every object present in the bake.
    ALL = "All Objects"
    # Every object belonging to a named collection.
    COLLECTION = "Collection"
    # An explicit list of object keys.
    OBJECTS = "Objects"


class OpType(Enum):
    """ A transformation applied to the temperature field after every source
    strategy has been evaluated.

    Orthogonal to InitType: an InitType creates a field out of nothing, an
    OpType takes a field and returns a different one.
    """

    # Constrain every value into [min_k, max_k].
    CLAMP = "Clamp"
    # Average each vertex toward its neighbours.
    SMOOTH = "Smooth"
    # Warm receivers according to their proximity to sources.
    CONTACT_DIFFUSION = "Contact Diffusion"


class OpStage(Enum):
    """ How much of the scene an operation needs to see.

    PER_OBJECT operations are a formula over one object's field and geometry;
    the registry resolves their scope and loops for them. SCENE operations
    read and write across objects and resolve their own scopes, because some
    of them (contact diffusion) have more than one.
    """

    PER_OBJECT = "Per Object"
    SCENE = "Scene"


class ObjectTempEvolution(Enum):
    """

    """
    FREE = "Free"
    FIXED = "Fixed"

class SimulationType(Enum):
    """

    """
    STATIONARY = "Stationary"
    DYNAMIC = "Dynamic"

class ShadingType(Enum):
    """ Machinery used to evaluate a transfer and turn it into an image.

    Orthogonal to TransferType, which is the physics. NODE_SHADER and
    RAY_NODE_SHADER can run identical radiometry and still produce different
    images, because only one of them traces reflections.
    """
    # Use geometric/graphical nodes to construct the correct shader using
    # Cycles default ray tracing capabilities
    RAY_NODE_SHADER = "Ray Node Shader"
    # Same, but use OSL (can only work on GPU for OptiX
    RAY_OSL_SHADER = "Ray OSL Shader"

    # Custom implementation of ray shaders, potentially very slow.
    MANUAL_RAY = "Custom Ray"

    # Use nodes to perform a scalar mapping, factoring a surrogate reflected ambient temperature
    # with a global emissivity value.
    NODE_SURROGATE_REFLECTION = "Node Surrogate Reflection"

    # Use nodes to perform a scalar mapping
    NODE_PURE_EMITTANCE = "Node Pure Emittance"

    # Try to attempt a numpy per-pixel emittance computation
    NUMPY_SHADER = "NumPy Pure Emittance"
    # Just emit a temperature map for the scene

    TEMPERATURE_SHADER = "Temperature Shader"

    def uses_transfer(self) -> bool:
        """ Whether this path can use transfer functions to normalize
        """
        return self is not ShadingType.TEMPERATURE_SHADER

    def traces_reflections(self) -> bool:
        """ Whether this path gets the reflected emission of other bodies from
        light transport. Such a path needs a thermal World (the background)
        and render settings that keep pixel values linear.
        """
        return self in (
            ShadingType.RAY_NODE_SHADER,
            ShadingType.RAY_OSL_SHADER,
            ShadingType.MANUAL_RAY,
        )


class TerminalMode(Enum):
    """ What the end of a shader graph produces. """

    # The quantitative emissivity to be used for EXR output
    RAW = "Raw Signal"
    # Signal normalized and run through a palette. Used only for
    # viewport visualization of the baked temperature / emission map
    FALSE_COLOR = "False Color"


class TransferType(Enum):
    """ Radiometric transfer function used to turn a surface temperature into
    a sensor signal.

    A thermal camera does not measure temperature but measures radiated power
    inside a finite waveband and infers a temperature from it, up to the problem of
    emissivity.

    The transfer type is the law which maps from temperature to raw radiated power, before
    applying emissivity reduction.
    """

    # S = R / (exp(B/T) - F) + O. A narrow-band reduction of Planck's law,
    #   and the calibration form real LWIR cameras ship their constants in.
    # Taken from
    # https://device.report/m/bb0fb3a133c0e28de013f89093d51f0629ef0e14866976b11b9d92bc19177b85.pdf
    # GenICam ICD FLIR AX5 Camera
    RBFO = "Calibration (R/B/F/O)"

    # Planck's law multiplied by the sensor's spectral response and
    # integrated across the band, precomputed into a lookup table.
    PLANCK_LUT = "Band-integrated Planck"

    # from reference \cite{waldermar_et_dudzik}
    #
    WIEN = "Wien"

    # from reference \cite{waldermar_et_dudzik}
    #
    RAYLEIGH_JEANS = "Rayleigh-Jeans"

    # M = eps*sigma*T^4. Total radiated power across all wavelengths, from
    # reference \cite{waldermar_et_dudzik}
    STEFAN_BOLTZMANN = "Stefan-Boltzmann"