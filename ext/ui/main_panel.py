"""
Panel classes and composable UISections for the extension's UI.

"""

from abc import abstractmethod, ABCMeta
from typing import Callable, Iterable, List, Optional

from bpy.types import Panel, Context, ID, Object, Collection

from ..operators.names import Labels
from ..constants import *
from ..thermal_core.contracts import (
    InitType, SpecScope, ShadingType, TransferType, TerminalMode, EnvironmentSpecType,
)
from ..shaders.registry import ShaderRegistry
from ..shaders.transfer import TransferNodeRegistry
from .init_registry import InitStrategyRegistry
from .text_wrap_utils import WrapWidget
from .environment_registry import EnvironmentFactorRegistry
from .resolution import ConfigBuilder, SpecsResolver, SpecResolutionError
from .color_bar_gpu import left_bottom_color_bar


class UISection(metaclass=ABCMeta):
    """ A self-contained, composable piece of panel UI. """

    @abstractmethod
    def draw(self, context: Context, layout) -> None:
        """ Draw this section's contents into "layout" """
        raise NotImplementedError


class BakeSection(UISection):
    """ A section containing all options and buttons pertaining to
    scene baking, including specification resolution outputs and the
    baking itself.

    Includes a count and warnings about spec resolutions in the hierarchy.
    """

    @staticmethod
    def _count_ready(context: Context) -> tuple[int, int, int, int]:
        """ How many mesh objects would produce a field, out of how many exist.

        Counts through ConfigBuilder rather than resolving each object here, so
        the panel and the bake can never disagree about what is ready.
        """
        total_mesh = len(ConfigBuilder.mesh_objects(context.scene))
        config, unresolved, invalid = ConfigBuilder.from_scene(context.scene)

        return len(config.sources), len(unresolved), len(invalid), total_mesh



    def draw(self, context: Context, layout) -> None:
        ready, unresolved, invalid, total_mesh = self._count_ready(context)

        if total_mesh == 0:
            layout.label(text="No mesh objects in scene", icon='INFO')
        else:
            layout.label(
                text=f"{ready}/{total_mesh} mesh object(s) ready to bake ({unresolved} unresolved, {invalid} invalid)",
                icon='CHECKMARK' if ready == total_mesh else 'INFO',
            )

        layout.operator(
            Labels.BAKE_TEMPERATURE.value,
            text="Bake Initial Temperature",
            icon='RENDER_STILL',
        )


class SpecSection(UISection):
    """ Draws the temperature-init strategy dropdown and the active
    strategy's parameters for a single scoped target.

    A single class serves both Object and Collection scope (rather than two
    near-duplicate classes) - `scope` and `get_target` are supplied at
    construction time by whichever Panel is using it (see MainPanel /
    CollectionSpecPanel below).
    """

    def __init__(self, scope: SpecScope, get_target: Callable[[Context], Optional[ID]]):
        self._scope = scope
        self._get_target = get_target

    def draw(self, context: Context, layout) -> None:
        target = self._get_target(context)
        if target is None:
            layout.label(text=f"No active {self._scope.value.lower()}", icon='INFO')
            return

        strategy_props = target.thermal_init
        layout.prop(strategy_props, "init_type")

        init_type = InitType[strategy_props.init_type]

        if init_type is InitType.INHERIT:
            # Resolving what INHERIT actually evaluates to
            layout.label(text="Inherits from collection default", icon='INFO')
            return

        try:
            descriptor = InitStrategyRegistry.get_strategy(init_type)
        except NotImplementedError:
            layout.label(text=f'"{init_type.value}" is not implemented yet', icon='ERROR')
            return

        sub_props = getattr(strategy_props, descriptor.attr_name)
        descriptor.draw(layout, sub_props)


class EnvironmentSection(UISection):
    """ Draws the scene's environmental-factor stack: one box per active
    entry (its type, parameters or a "not implemented yet" notice, and a
    remove button), plus the add-dropdown at the bottom.

    """

    def draw(self, context: Context, layout) -> None:
        settings = context.scene.thermal_environment

        for index, item in enumerate(settings.factors):
            factor_type = EnvironmentSpecType[item.factor_type]

            box = layout.box()
            header = box.row()
            header.label(text=factor_type.value)
            remove = header.operator(Labels.ENVIRONMENT_FACTOR_REMOVE.value, text="", icon='X')
            remove.index = index

            try:
                descriptor = EnvironmentFactorRegistry.get(factor_type)
            except NotImplementedError:
                box.label(text=f'"{factor_type.value}" is not implemented yet', icon='ERROR')
                continue

            sub_props = getattr(item, descriptor.attr_name)
            descriptor.draw(box, sub_props)

        layout.operator_menu_enum(
            Labels.ENVIRONMENT_FACTOR_ADD.value, "factor_type",
            text="Add Environmental Factor", icon='ADD',
        )


class ShadingSection(UISection):
    """ Shading path, radiometric transfer, and the transfer's parameters.

    Dispatches through ShaderRegistry and TransferNodeRegistry the same way
    SpecSection dispatches through InitStrategyRegistry, so an unimplemented
    path reports itself rather than being hidden.
    """

    def draw(self, context: Context, layout) -> None:
        settings = context.scene.thermal_render
        layout.prop(settings, "shading_type")

        shading_type = ShadingType[settings.shading_type]
        if not ShaderRegistry.is_implemented(shading_type):
            layout.label(
                text=f'"{shading_type.value}" is not implemented yet', icon='ERROR',
            )
            return

        if not shading_type.uses_transfer():
            layout.label(text="Emits baked temperature directly", icon='INFO')
            return

        layout.prop(settings, "transfer_type")

        transfer_type = TransferType[settings.transfer_type]
        try:
            descriptor = TransferNodeRegistry.get(transfer_type)
        except NotImplementedError:
            layout.label(
                text=f'"{transfer_type.value}" is not implemented yet', icon='ERROR',
            )
            return

        props = getattr(settings, descriptor.attr_name)
        descriptor.draw(layout, props)

        # Surface a bad parameter here rather than letting the build fail.
        try:
            descriptor.build_spec(props).validate()
        except ValueError as error:
            WrapWidget.draw(layout, context, str(error), 'ERROR')


class SurfaceSection(UISection):
    """ Emissivity and the environment it mixes against.

    Hidden for shading paths with no transfer, where the two have no meaning.
    """

    # Below this, the surface reads mostly as a mirror of its surroundings.
    _MIRROR_THRESHOLD = 0.5

    def draw(self, context: Context, layout) -> None:
        settings = context.scene.thermal_render
        if not ShadingType[settings.shading_type].uses_transfer():
            layout.label(text="Not used by this shading path", icon='INFO')
            return

        layout.prop(settings, "emissivity", slider=True)

        row = layout.row(align=True)
        row.prop(settings, "reflected_temperature")
        row.prop(settings, "reflected_unit", text="")

        if settings.emissivity < SurfaceSection._MIRROR_THRESHOLD:
            WrapWidget.draw(
                layout, context,
                "Mostly reflective: the image will show the environment "
                "more than the object.",
                icon='INFO',
            )


class OutputSection(UISection):
    """ What the shader emits, and the display span when it emits colour. """

    def draw(self, context: Context, layout) -> None:
        settings = context.scene.thermal_render
        layout.prop(settings, "terminal_mode")

        if TerminalMode[settings.terminal_mode] is TerminalMode.FALSE_COLOR:
            OutputSection._draw_span(settings, layout, context)
        else:
            OutputSection._draw_raw_notes(context, layout)

    @staticmethod
    def _draw_span(settings, layout, context) -> None:
        row = layout.row(align=True)
        row.prop(settings, "span_min")
        row.prop(settings, "span_max")
        layout.prop(settings, "span_unit")

        layout.operator(
            Labels.FIT_DISPLAY_SPAN.value, text="Fit Span to Scene", icon='ARROW_LEFTRIGHT',
        )

        if settings.span_max <= settings.span_min:
            WrapWidget.draw(layout, context, "Span minimum must be below its maximum.")

    @staticmethod
    def _draw_raw_notes(context: Context, layout) -> None:
        WrapWidget.draw(
            layout, context, "Linear signal. Invertible back to temperature.", icon='INFO',
        )
        # AgX and Filmic tone-map the result, which destroys the measurement
        # in the viewport and in any 8-bit output.
        if context.scene.view_settings.view_transform != 'Standard':
            WrapWidget.draw(
                layout, context,
                "Set the view transform to Standard, in Render Properties > "
                "Color Management, or the values will be tone-mapped.",
                icon='ERROR',
            )


class RenderSection(UISection):
    """ Builds the thermal material and assigns it to every baked object. """

    def draw(self, context: Context, layout) -> None:
        col = layout.row(align=True)
        col.operator(
            Labels.VISUALIZE_TEMPERATURE.value,
            text="Build Thermal Material",
            icon='MATERIAL',
        )
        col.operator(
            Labels.HIDE_COLOR_BAR.value if left_bottom_color_bar.is_active() else
                Labels.SHOW_COLOR_BAR.value,
            text="", icon="COLOR"
        )
        WrapWidget.draw(
            layout, context,
            "Rebuild after changing any setting above. "
            "View in Material Preview or Rendered shading.",
            icon='INFO',
        )


class CentralPanel(UISection):
    """ Composes an ordered sequence of UISections into one draw() call each in its own box.
    This constructs the central panel holding generation information and (to be determined)
    hooks.
    """

    def __init__(self, sections: Iterable[UISection]):
        self._sections = tuple(sections)

    def draw(self, context: Context, layout) -> None:
        for section in self._sections:
            section.draw(context, layout.box())


class MainPanel(Panel):
    """  """
    bl_idname = "THERMAL_PT_main"
    bl_label = "Object"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = MAIN_PANEL_NAME
    bl_order = 0

    def draw(self, context: Context) -> None:
        panel = CentralPanel(sections=[
            SpecSection(scope=SpecScope.OBJECT, get_target=lambda ctx: ctx.object),
        ])
        panel.draw(context, self.layout)

class BakePanel(Panel):
    """

    """
    """  """
    bl_idname = "THERMAL_PT_bake"
    bl_label = "Baking"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = MAIN_PANEL_NAME
    # After Field Operations (bl_order 1): the bake is what you press once the
    # stack is how you want it.
    bl_order = 2

    def draw(self, context: Context) -> None:
        panel = CentralPanel(sections=[
            BakeSection(),
        ])
        panel.draw(context, self.layout)

class ThermographyPanel(Panel):
    """ Shading path, radiometry and output settings.

    Separate from MainPanel because these are scene-wide render settings,
    while MainPanel's contents follow the active object.
    """
    bl_idname = "THERMAL_PT_thermography"
    bl_label = "Thermography"
    bl_category = MAIN_PANEL_NAME
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_order = 3

    def draw(self, context: Context) -> None:
        panel = CentralPanel(sections=[
            ShadingSection(),
            SurfaceSection(),
            OutputSection(),
            RenderSection(),
        ])
        panel.draw(context, self.layout)


class CollectionSpecPanel(Panel):
    """ Properties Editor tab (shown when a Collection is the active
    outliner ID) for setting a collection's default initial temperature.
    """
    bl_idname = "THERMAL_PT_collection_spec"
    bl_label = "Thermal"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "collection"

    def draw(self, context: Context) -> None:
        panel = CentralPanel(sections=[
            SpecSection(scope=SpecScope.COLLECTION, get_target=lambda ctx: ctx.collection),
        ])
        panel.draw(context, self.layout)


class EnvironmentPanel(Panel):
    """ Properties Editor tab (shown when a Scene is the active outliner ID)
    for configuring scene-wide environmental conditions (e.g. ambient
    temperature) used for convective/radiative exchange with the scene.
    """
    bl_idname = "THERMAL_PT_environment"
    bl_label = "Thermal Environment"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "scene"

    def draw(self, context: Context) -> None:
        panel = CentralPanel(sections=[
            EnvironmentSection(),
        ])
        panel.draw(context, self.layout)


class InfoPanel(Panel):

    bl_idname = "THERMAL_PT_info"
    bl_label = "Info"
    bl_category = MAIN_PANEL_NAME
    bl_options = { 'DEFAULT_CLOSED' }
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_order = 4

    def draw(self, context):

        layout = self.layout

        # Title
        col = layout.column(align=True)
        col.label(text=MAIN_PANEL_NAME, icon='INFO')
        col.separator()

        # Version Info
        col.label(text=f"Version: {VERSION}")
        col.label(text=f"Tested on Blender {TARGET_VERSION}")
        col.separator()

        # Links section
        col = layout.column(align=True)
        col.label(text="Links:")

        row = col.row()
        op = row.operator(Labels.OPEN_URL.value, text="GitHub", icon='URL')
        op.url = REPO_URL
        op = row.operator(Labels.OPEN_URL.value, text="Documentation", icon='FILE_FOLDER')
        op.url = DOCU_URL

class SmoothSection(UISection):
    pass

class PropagateSection(UISection):
    pass

class TempEditorPanel(Panel):
    pass