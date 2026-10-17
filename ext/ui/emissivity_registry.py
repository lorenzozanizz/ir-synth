""" Central mapping from EmissivityType -> everything needed to work with
the required emissivity strategy
"""

from bpy.types import Object, UILayout

from ..thermal_core.contracts import EmissivityType
from ..thermal_core.specs import UniformEmissivitySpec, WeightPaintedEmissivitySpec
from .properties import UniformEmissivityProperties, WeightPaintedEmissivityProperties
from .strategy_registry import StrategyDescriptor, StrategyRegistryBase


class EmissivityStrategyRegistry(StrategyRegistryBase):
    """ The emissivity strategies. See StrategyRegistryBase. """
    type_enum = EmissivityType


@EmissivityStrategyRegistry.register(EmissivityType.UNIFORM)
class EmissivityUniform(StrategyDescriptor):
    """ One emissivity value for every point on the object. """

    emissivity_type = EmissivityType.UNIFORM
    property_group = UniformEmissivityProperties
    attr_name = "uniform"

    @staticmethod
    def draw(ui_layout: UILayout, props: UniformEmissivityProperties) -> None:
        ui_layout.prop(props, "value", slider=True)

    @staticmethod
    def build(props: UniformEmissivityProperties) -> UniformEmissivitySpec:
        return UniformEmissivitySpec(value=float(props.value))


@EmissivityStrategyRegistry.register(EmissivityType.WEIGHT_PAINTED)
class EmissivityWeightPainted(StrategyDescriptor):
    """ Vertex-group weights remapped onto an emissivity range. Object-only. """

    emissivity_type = EmissivityType.WEIGHT_PAINTED
    property_group = WeightPaintedEmissivityProperties
    attr_name = "weight_painted"

    @staticmethod
    def draw(ui_layout: UILayout, props: WeightPaintedEmissivityProperties) -> None:
        # Same as the temperature version: a searchable dropdown against the
        # object's real vertex groups, so a stale name cannot be entered.
        target = props.id_data
        if isinstance(target, Object) and target.type == 'MESH':
            ui_layout.prop_search(props, "vertex_group", target, "vertex_groups")
        else:
            ui_layout.prop(props, "vertex_group")
        ui_layout.prop(props, "min_value", slider=True)
        ui_layout.prop(props, "max_value", slider=True)
        ui_layout.prop(props, "falloff")

    @staticmethod
    def build(props: WeightPaintedEmissivityProperties) -> WeightPaintedEmissivitySpec:
        return WeightPaintedEmissivitySpec(
            vertex_group=props.vertex_group,
            min_value=float(props.min_value),
            max_value=float(props.max_value),
            falloff=props.falloff,
        )
