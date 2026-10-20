"""
Blender-facing PropertyGroups mirroring the temperature-initialization
strategies defined in thermal_core/specs.py.

These hold live, editable UI state (attached to Object and Collection - see
`data_properties` at the bottom). A later conversion-boundary function
builds the pure `thermal_core.specs` dataclasses from this state right
before baking; nothing here should be consumed directly by physics code.

Both Object and Collection share the *same* InitStrategyProperties class.
The set of strategies offered in the dropdown differs per scope (Collection
can't offer WEIGHT_PAINTED - see ObjectTempInitType.allowed_for_scope() in
thermal_core/contracts.py) - resolved dynamically at draw time by checking
the type of the owning ID datablock (`self.id_data`), so we don't need two
near-duplicate PropertyGroup classes.
"""

from bpy.types import PropertyGroup, NodeTree, Object, Collection, Scene
from bpy.props import (
    PointerProperty, StringProperty, FloatProperty, FloatVectorProperty, EnumProperty,
    CollectionProperty, IntProperty,
)

from ..thermal_core.contracts import (
    InitType, EmissivityType, SpecScope, ShadingType, TransferType, TerminalMode,
    EnvironmentSpecType,
)
from ..thermal_core.temperature import TempUnit, Conversions
from ..shaders.properties import RBFOTransferProperties, WienTransferProperties, RayleighJeansTransferProperties
from ..registration import PropertyRegistration


class SceneIgnoreRules(PropertyGroup):
    """ """
    pass


class UniformTempProperties(PropertyGroup):
    """ UI state for ObjectTempInitType.UNIFORM:
    a single scalar applied to every point on the object.
    """
    value: FloatProperty(                                               # type: ignore
        name="Temperature",
        description="Uniform starting temperature applied to every point on the object",
        default=293.15,  # 20C in Kelvin, stored/exposed per `unit` below
        soft_min=0.0,
    )
    unit: EnumProperty(                                                 # type: ignore
        name="Unit",
        description="Display unit for the temperature value above",
        items=[(u.name, u.value, "") for u in TempUnit],
        default=TempUnit.KELVIN.name,
    )


class AmbientTempProperties(PropertyGroup):
    """ UI state for ObjectTempInitType.AMBIENT: a single scalar applied to
    every point on every object in the scene (the surrounding air/environment).
    """
    pass



class GradientTempProperties(PropertyGroup):
    """ UI state for ObjectTempInitType.GRADIENT: temperature varies linearly
    between two points in world space, `point_a` -> value_a, `point_b` -> value_b.
    """
    point_a: FloatVectorProperty(                                                  # type: ignore
        name="Point A",
        description="World-space point pinned to Value A",
        subtype='XYZ',
        size=3,
    )
    point_b: FloatVectorProperty(                                                  # type: ignore
        name="Point B",
        description="World-space point pinned to Value B",
        subtype='XYZ',
        size=3,
        default=(1.0, 0.0, 0.0),
    )
    value_a: FloatProperty(                                                        # type: ignore
        name="Value A",
        description="Temperature at Point A",
        default=293.15,
    )
    value_b: FloatProperty(                                                        # type: ignore
        name="Value B",
        description="Temperature at Point B",
        default=310.15,
    )
    unit: EnumProperty(                                                            # type: ignore
        name="Unit",
        description="Display unit for the Value A/B temperatures above",
        items=[(u.name, u.value, "") for u in TempUnit],
        default=TempUnit.KELVIN.name,
    )


class WeightPaintedTempProperties(PropertyGroup):
    """ UI state for ObjectTempInitType.WEIGHT_PAINTED. Object-only - see
    ObjectTempInitType.allowed_for_scope() in thermal_core/contracts.py.
    Weights (0-1) from `vertex_group` are remapped onto [min_value, max_value].
    """
    vertex_group: StringProperty(                                                       # type: ignore
        name="Vertex Group",
        description="Vertex group whose weights (0-1) are remapped to a temperature range",
    )
    min_value: FloatProperty(                                                           # type: ignore
        name="Min Temperature",
        description="Temperature at vertex-group weight 0.0",
        default=293.15,
    )
    max_value: FloatProperty(                                                           # type: ignore
        name="Max Temperature",
        description="Temperature at vertex-group weight 1.0",
        default=310.15,
    )
    unit: EnumProperty(                                                                 # type: ignore
        name="Unit",
        description="Display unit for the min/max temperature values above",
        items=[(u.name, u.value, "") for u in TempUnit],
        default=TempUnit.KELVIN.name,
    )
    falloff: EnumProperty(                                                              # type: ignore
        name="Falloff",
        description="How intermediate weights are remapped between min and max",
        items=[
            ("LINEAR", "Linear", "Linear interpolation between min and max"),
            ("EASE_IN_OUT", "Ease In/Out", "Smoothstep interpolation between min and max"),
        ],
        default="LINEAR",
    )


# Needs to be declared at module level statically and cannot be put inside InitStrategyProperties due
# to blender registration requiring it
def _scope_for(owner) -> SpecScope:
    """ The scope implied by the ID datablock an InitStrategyProperties hangs off. """
    if isinstance(owner, Collection):
        return SpecScope.COLLECTION
    if isinstance(owner, Scene):
        return SpecScope.SCENE
    return SpecScope.OBJECT


def _init_type_items(self, _):
    """ Determines scope (Object vs Collection vs Scene) """
    return STRATEGIES_BY_SCOPE.get(_scope_for(self.id_data))

# Depending on the scope of the declaration (object or collection or something TBD)
# different strategies are available.
STRATEGIES_BY_SCOPE = {
    scope: [(m.name, m.value, "") for m in InitType.allowed_for_scope(scope)]
    for scope in SpecScope
}

class InitStrategyProperties(PropertyGroup):
    """ "Which strategy, and its parameters" container, attached to both
    Object and Collection (see `data_properties`). Only the sub-group
    matching `init_type` is meaningful at any given time; the UI dispatcher
    (Phase 4) draws just that one via the strategy registry (Phase 3).
    """
    init_type: EnumProperty(                                                    # type: ignore
        name="Initial Temperature",
        description="Strategy used to determine the starting temperature",
        items=_init_type_items,                                                 # type: ignore
    )
    uniform: PointerProperty(type=UniformTempProperties)                        # type: ignore
    ambient: PointerProperty(type=AmbientTempProperties)                        # type: ignore
    gradient: PointerProperty(type=GradientTempProperties)                      # type: ignore
    weight_painted: PointerProperty(type=WeightPaintedTempProperties)           # type: ignore


# ---------------------------------------------------------------- emissivity
#
# Parallel to the temperature groups above. The chain is
# Object -> Collection(s) -> ThermalRenderSettings.emissivity (scene default).

_FALLOFF_ITEMS = [
    ("LINEAR", "Linear", "Linear interpolation between min and max"),
    ("EASE_IN_OUT", "Ease In/Out", "Smoothstep interpolation between min and max"),
]


class UniformEmissivityProperties(PropertyGroup):
    """ UI state for EmissivityType.UNIFORM: one value for every point. """
    value: FloatProperty(                                                       # type: ignore
        name="Emissivity",
        description="Fraction of a blackbody's emission this surface radiates",
        default=0.95,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )


class WeightPaintedEmissivityProperties(PropertyGroup):
    """ UI state for EmissivityType.WEIGHT_PAINTED. Object-only.
    Weights (0-1) from `vertex_group` are remapped onto [min_value, max_value].
    """
    vertex_group: StringProperty(                                               # type: ignore
        name="Vertex Group",
        description="Vertex group whose weights (0-1) are remapped to an emissivity range",
    )
    min_value: FloatProperty(                                                   # type: ignore
        name="Min Emissivity",
        description="Emissivity at vertex-group weight 0.0",
        default=0.1,
        min=0.0, max=1.0,
        subtype='FACTOR',
    )
    max_value: FloatProperty(                                                   # type: ignore
        name="Max Emissivity",
        description="Emissivity at vertex-group weight 1.0",
        default=0.95,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )
    falloff: EnumProperty(                                                      # type: ignore
        name="Falloff",
        description="How intermediate weights are remapped between min and max",
        items=_FALLOFF_ITEMS,
        default="LINEAR",
    )


# Module level for the same reason as STRATEGIES_BY_SCOPE: Blender keeps no
# reference to the items returned by a dynamic enum callback.
EMISSIVITY_STRATEGIES_BY_SCOPE = {
    scope: [(m.name, m.value, "") for m in EmissivityType.allowed_for_scope(scope)]
    for scope in SpecScope
}


def _emissivity_type_items(self, _):
    """ Determines scope (Object vs Collection) """
    return EMISSIVITY_STRATEGIES_BY_SCOPE.get(_scope_for(self.id_data))


class EmissivityStrategyProperties(PropertyGroup):
    """ "Which emissivity strategy, and its parameters" container, attached
    to both Object and Collection as `thermal_emissivity`. Only the sub-group
    matching `emissivity_type` is meaningful at any given time.
    """
    emissivity_type: EnumProperty(                                              # type: ignore
        name="Emissivity",
        description="Strategy used to determine the per-vertex emissivity",
        items=_emissivity_type_items,                                           # type: ignore
    )
    uniform: PointerProperty(type=UniformEmissivityProperties)                  # type: ignore
    weight_painted: PointerProperty(type=WeightPaintedEmissivityProperties)     # type: ignore


class EnvironmentAmbientTemperatureProperties(PropertyGroup):
    """ UI state for EnvironmentSpecType.AMBIENT_TEMPERATURE: the air
    temperature surrounding the whole scene, used for convective/radiative
    exchange with the environment.

    """
    value: FloatProperty(                                               # type: ignore
        name="Temperature",
        description="Ambient air temperature surrounding the scene",
        default=293.15,  # 20C in Kelvin, stored/exposed per `unit` below
        soft_min=0.0,
    )
    unit: EnumProperty(                                                 # type: ignore
        name="Unit",
        description="Display unit for the temperature value above",
        items=[(u.name, u.value, "") for u in TempUnit],
        default=TempUnit.KELVIN.name,
    )


class EnvironmentDefaultInitProperties(PropertyGroup):
    """ UI state for EnvironmentSpecType.DEFAULT_INITIALIZATION: the strategy
    an object falls back to when it resolves to INHERIT and no containing
    collection offers a concrete one.

    Reuses InitStrategyProperties rather than redeclaring parameters. Because
    its owning ID datablock is the Scene, _init_type_items offers only the
    strategies legal at SpecScope.SCENE.
    """
    init: PointerProperty(type=InitStrategyProperties)                                 # type: ignore


class EnvironmentFactorItem(PropertyGroup):
    """ One active entry in the scene's environmental-factor stack: which
    factor it is, and its parameters.

    """
    factor_type: EnumProperty(                                                      # type: ignore
        name="Factor",
        description="Which environmental condition this entry configures",
        items=[(f.name, f.value, "") for f in EnvironmentSpecType],
        default=EnvironmentSpecType.AMBIENT_TEMPERATURE.name,
    )
    ambient_temperature: PointerProperty(type=EnvironmentAmbientTemperatureProperties)  # type: ignore
    default_initialization: PointerProperty(type=EnvironmentDefaultInitProperties)      # type: ignore


class EnvironmentSettings(PropertyGroup):
    """ Scene-level stack of active environmental factors (see
    EnvironmentFactorItem above).

    """
    factors: CollectionProperty(type=EnvironmentFactorItem)                         # type: ignore
    active_index: IntProperty(                                                      # type: ignore
        name="Active Environmental Factor",
        description="Index of the selected entry in the list above, used by "
                    "the add/remove operators",
        default=0,
    )


class ThermalProperties(PropertyGroup):
    """ Reserved for future physical thermal specs (emissivity, material)
    """
    pass


class ThermalRenderSettings(PropertyGroup):
    """ Scene-level render configuration for
        - shading path
        - transfe,
        - and the surface/environment parameters the output is mixed with

    Attached to Scene and not individual objects because most of these is a
    property of the camera or the environment, not of a single mesh.

    The exception is emissivity, which is per-surface. The value here is the
    scene default: the last link of the emissivity chain, used by every
    object that resolves to INHERIT with no concrete collection value.
    """

    shading_type: EnumProperty(                                         # type: ignore
        name="Shading",
        description="How the thermal signal is evaluated and turned into an image",
        items=[(m.name, m.value, "") for m in ShadingType],
        default=ShadingType.NODE_SURROGATE_REFLECTION.name,
    )
    transfer_type: EnumProperty(                                        # type: ignore
        name="Transfer",
        description="Radiometric function converting surface temperature into "
                    "sensor signal",
        items=[(m.name, m.value, "") for m in TransferType],
        default=TransferType.RBFO.name,
    )
    rbfo: PointerProperty(type=RBFOTransferProperties)                  # type: ignore
    wien: PointerProperty(type=WienTransferProperties)                  # type: ignore
    rayleigh_jeans: PointerProperty(type=RayleighJeansTransferProperties)  # type: ignore

    emissivity: FloatProperty(                                          # type: ignore
        name="Default Emissivity",
        description="Scene default emissivity, used by every object set to "
                    "Inherit with no collection value. Fraction of a "
                    "blackbody's emission a surface actually radiates. The "
                    "remainder is reflected from the environment",
        default=0.95,
        min=0.0,
        max=1.0,
    )
    reflected_temperature: FloatProperty(                               # type: ignore
        name="Reflected Temperature",
        description="Apparent temperature of the surroundings, mixed in through "
                    "the (1 - emissivity) term. A single constant standing in "
                    "for the environment, as on a real camera",
        default=20.0,
    )
    reflected_unit: EnumProperty(                                       # type: ignore
        name="Unit",
        description="Display unit for the reflected temperature above",
        items=[(u.name, u.value, "") for u in TempUnit],
        default=TempUnit.CELSIUS.name,
    )

    # Ray-traced path only: shape of the (1 - emissivity) reflection.
    specular_fraction: FloatProperty(                                   # type: ignore
        name="Specular Fraction",
        description="Part of the reflection that is glossy. 0 is a fully "
                    "diffuse reflection, 1 is a fully glossy reflection",
        default=0.2,
        min=0.0,
        max=1.0,
    )
    reflection_roughness: FloatProperty(                                # type: ignore
        name="Reflection Roughness",
        description="Roughness of the glossy part of the reflection. 0 is a "
                    "mirror",
        default=0.3,
        min=0.0,
        max=1.0,
    )

    terminal_mode: EnumProperty(                                        # type: ignore
        name="Output",
        description="False colour is a viewport display choice "
                    "and discards recoverability",
        items=[(m.name, m.value, "") for m in TerminalMode],
        default=TerminalMode.RAW.name,
    )
    span_min: FloatProperty(                                            # type: ignore
        name="Span Min",
        description="Temperature shown at the cold end of the palette. Display "
                    "only, it never affects a raw render",
        default=0.0,
    )
    span_max: FloatProperty(                                            # type: ignore
        name="Span Max",
        description="Temperature shown at the hot end of the palette. Display "
                    "only, it never affects a raw render",
        default=100.0,
    )
    span_unit: EnumProperty(                                            # type: ignore
        name="Unit",
        description="Display unit for the span above",
        items=[(u.name, u.value, "") for u in TempUnit],
        default=TempUnit.KELVIN.name,
    )

    def reflected_temperature_k(self) -> float:
        """ The reflected temperature in Kelvin, whatever unit it is shown in. """
        return Conversions.to_kelvin(
            self.reflected_temperature, TempUnit[self.reflected_unit]
        )

    def span_min_k(self) -> float:
        """ Cold end of the display span, in Kelvin. """
        return Conversions.to_kelvin(self.span_min, TempUnit[self.span_unit])

    def span_max_k(self) -> float:
        """ Hot end of the display span, in Kelvin. """
        return Conversions.to_kelvin(self.span_max, TempUnit[self.span_unit])


data_properties = (
    PropertyRegistration(
        owner=Object, name="thermal_init", value=PointerProperty(type=InitStrategyProperties)
    ),
    PropertyRegistration(
        owner=Collection, name="thermal_init", value=PointerProperty(type=InitStrategyProperties)
    ),
    PropertyRegistration(
        owner=Object, name="thermal_emissivity",
        value=PointerProperty(type=EmissivityStrategyProperties),
    ),
    PropertyRegistration(
        owner=Collection, name="thermal_emissivity",
        value=PointerProperty(type=EmissivityStrategyProperties),
    ),
)

scene_properties = (
    PropertyRegistration(
        owner=Scene, name="thermal_render", value=PointerProperty(type=ThermalRenderSettings)
    ),
    PropertyRegistration(
        owner=Scene, name="thermal_environment", value=PointerProperty(type=EnvironmentSettings)
    ),
)