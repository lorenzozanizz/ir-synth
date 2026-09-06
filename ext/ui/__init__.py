from .main_panel import (
    MainPanel, ThermographyPanel, InfoPanel, CollectionSpecPanel, BakePanel, EnvironmentPanel
)

from .op_properties import (
    stack_properties,
    ObjectRefProperties,
    OpScopeProperties,
    ClampOpProperties,
    ThermalOpEntry,
    ThermalStackProperties,
    ContactDiffusionOpProperties,
    SmoothOpProperties
)
from .op_registry import OperationRegistry, OperationDescriptor
from .stack_panel import AddOperationMenu, OperationStackPanel

from .properties import (
    data_properties,
    scene_properties,
    SceneIgnoreRules,
    UniformTempProperties,
    AmbientTempProperties,
    GradientTempProperties,
    WeightPaintedTempProperties,
    InitStrategyProperties,
    ThermalProperties,
    ThermalRenderSettings,
    EnvironmentAmbientTemperatureProperties,
    EnvironmentFactorItem,
    EnvironmentSettings,
)

properties = data_properties + scene_properties + stack_properties


# PropertyGroup classes referenced via PointerProperty (Uniform/WeightPainted) must be
# registered before the class that points to them (InitStrategyProperties). Likewise,
# EnvironmentAmbientTemperatureProperties must precede EnvironmentFactorItem, which must
# precede EnvironmentSettings.
classes = (
    SceneIgnoreRules,
    UniformTempProperties,
    AmbientTempProperties,
    GradientTempProperties,
    WeightPaintedTempProperties,
    InitStrategyProperties,
    ThermalProperties,
    ThermalRenderSettings,
    EnvironmentAmbientTemperatureProperties,
    EnvironmentFactorItem,
    EnvironmentSettings,
    ObjectRefProperties,
    OpScopeProperties,
    ClampOpProperties,
    SmoothOpProperties,
    ContactDiffusionOpProperties,
    ThermalOpEntry,
    ThermalStackProperties,
    MainPanel,
    AddOperationMenu,
    OperationStackPanel,
    ThermographyPanel,
    BakePanel,
    CollectionSpecPanel,
    EnvironmentPanel,
    InfoPanel,
)