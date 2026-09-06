""" This module contains bpy properties which mirror the ones
required to manage and apply post-bake oprations.

Scope lives inside each operation's own property group.

ThermalOpEntry holds a PointerProperty to every operation's parameter group
because a CollectionProperty can only store one PropertyGroup type. Only the
group matching op_type is drawn or read at any time.
"""

from bpy.types import PropertyGroup, Collection, Object, Scene
from bpy.props import (
    BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
    IntProperty, PointerProperty, StringProperty,
)

from ..thermal_core.contracts import OpType, ScopeMode
from ..thermal_core.operations import OpScope
from ..thermal_core.field import ObjectKey
from ..thermal_core.temperature import TempUnit, Conversions
from ..registration import PropertyRegistration


class ObjectRefProperties(PropertyGroup):
    """ One entry in an OpScopeProperties object list. """
    target: PointerProperty(                                            # type: ignore
        name="Object",
        type=Object,
    )


class OpScopeProperties(PropertyGroup):
    """ UI state for thermal_core.operations.OpScope """

    mode: EnumProperty(                                                 # type: ignore
        name="Scope",
        description="Which objects this operation acts on",
        items=[(m.name, m.value, "") for m in ScopeMode],
        default=ScopeMode.ALL.name,
    )
    collection: PointerProperty(                                        # type: ignore
        name="Collection",
        description="Objects belonging to this collection are affected",
        type=Collection,
    )
    objects: CollectionProperty(type=ObjectRefProperties)               # type: ignore
    active_object_index: IntProperty(default=0)                         # type: ignore

    # This performs a mapping between BPY side and backend side
    def to_spec(self) -> OpScope:
        """ Build the pure OpScope. Empty object slots are dropped. """
        mode = ScopeMode[self.mode]
        return OpScope(
            mode=mode,
            collection=self.collection.name if self.collection else "",
            objects=tuple(
                ObjectKey(ref.target.name) for ref in self.objects if ref.target
            ),
        )


class ClampOpProperties(PropertyGroup):
    """ UI state for thermal_core.operations.ClampOp. """

    scope: PointerProperty(type=OpScopeProperties)                      # type: ignore
    min_value: FloatProperty(                                           # type: ignore
        name="Min Temperature",
        description="Values below this are raised to it",
        default=0.0,
    )
    max_value: FloatProperty(                                           # type: ignore
        name="Max Temperature",
        description="Values above this are lowered to it",
        default=100.0,
    )
    unit: EnumProperty(                                                 # type: ignore
        name="Unit",
        description="Display unit for the bounds above",
        items=[(u.name, u.value, "") for u in TempUnit],
        default=TempUnit.CELSIUS.name,
    )

    def min_k(self) -> float:
        return Conversions.to_kelvin(self.min_value, TempUnit[self.unit])

    def max_k(self) -> float:
        return Conversions.to_kelvin(self.max_value, TempUnit[self.unit])


class SmoothOpProperties(PropertyGroup):
    """ UI state for thermal_core.operations.SmoothOp. """

    scope: PointerProperty(type=OpScopeProperties)                      # type: ignore
    iterations: IntProperty(                                            # type: ignore
        name="Iterations",
        description="Each pass spreads heat by one edge. This sets how far "
                    "smoothing reaches, not how strong it is",
        default=5,
        min=0,
        soft_max=50,
    )
    factor: FloatProperty(                                              # type: ignore
        name="Factor",
        description="How far toward the neighbour average each pass moves",
        default=0.5,
        min=0.0,
        max=1.0,
        soft_max=0.5,
    )


class ContactDiffusionOpProperties(PropertyGroup):
    """ UI state for thermal_core.operations.ContactDiffusionOp. """

    source: PointerProperty(type=OpScopeProperties)                     # type: ignore
    receiver: PointerProperty(type=OpScopeProperties)                   # type: ignore
    radius: FloatProperty(                                              # type: ignore
        name="Radius",
        description="World-space distance beyond which a receiver vertex is unaffected",
        default=0.1,
        min=0.0001,
        soft_max=2.0,
        unit='LENGTH',
    )
    strength: FloatProperty(                                            # type: ignore
        name="Strength",
        description="Maximum blend toward the source temperature, at zero distance",
        default=0.8,
        min=0.0,
        max=1.0,
    )
    falloff: EnumProperty(                                              # type: ignore
        name="Falloff",
        description="How the blend decays from the source out to the radius",
        items=[
            ("LINEAR", "Linear", "Linear decay to zero at the radius"),
            ("EASE_IN_OUT", "Ease In/Out", "Smoothstep decay to zero at the radius"),
        ],
        default="EASE_IN_OUT",
    )


class ThermalOpEntry(PropertyGroup):
    """ One entry in the scene's operation stack. """

    op_type: EnumProperty(                                              # type: ignore
        name="Operation",
        items=[(m.name, m.value, "") for m in OpType],
        default=OpType.CLAMP.name,
    )
    name: StringProperty(                                               # type: ignore
        name="Name",
        description="Label shown in the stack. Purely cosmetic",
        default="",
    )
    enabled: BoolProperty(                                              # type: ignore
        name="Enabled",
        description="Disabled operations stay in the stack but are skipped when baking",
        default=True,
    )
    seed: IntProperty(                                                  # type: ignore
        name="Seed",
        description="Random seed for operations with a random component",
        default=0,
    )

    # Whether this operation's panel entry has been extended in the UI to visualize.
    expanded: BoolProperty(default=True)                                # type: ignore


    # An ugly but easy solution: we carry an op_type enum and then go and read the property corresponding
    # to the op_type. Every operations needs to be added here.
    # This really takes at most 100 bytes per operation, negligible.
    clamp: PointerProperty(type=ClampOpProperties)                      # type: ignore
    smooth: PointerProperty(type=SmoothOpProperties)                    # type: ignore
    contact_diffusion: PointerProperty(type=ContactDiffusionOpProperties)   # type: ignore


class ThermalStackProperties(PropertyGroup):
    """ The scene's ordered operation stack. """

    entries: CollectionProperty(type=ThermalOpEntry)                    # type: ignore


stack_properties = (
    PropertyRegistration(
        owner=Scene, name="thermal_stack", value=PointerProperty(type=ThermalStackProperties)
    ),
)
